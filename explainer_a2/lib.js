/* Pure functions behind the page's widgets. No DOM, so Node can run them.
 *
 * Why a separate file: the tests load this exact text under Node and compare its
 * answers with the Python code it mirrors (pareto_frontier above all). Written
 * inline in the page, the same functions could only be tested by driving a
 * browser. Rejected: a Python port tested in place of the JS, which proves the
 * port and says nothing about what the page runs.
 */
const A2 = (function () {
  "use strict";

  /* ---- the measured service curve ------------------------------------ */

  // levels: [{c, lat, tps, util, ...}] ascending in c. Linear in c between
  // measured levels, which is how the simulator's ServiceCurve reads it.
  // Below the first level the curve runs from an idle point (nothing served,
  // no throughput) that is not a measured level. Above the last level there
  // is nothing: the curve is not extrapolated.
  function curveAt(levels, c, withIdle) {
    const first = levels[0];
    const last = levels[levels.length - 1];
    if (c > last.c) return null;
    if (c < first.c) {
      if (!withIdle || c < 0) return null;
      const f = c / first.c;
      return { c: c, lat: first.lat, tps: first.tps * f, util: first.util * f,
               perReq: first.tps / first.c, measured: false, below: true, lo: null, hi: first };
    }
    let i = 0;
    while (i < levels.length - 1 && levels[i + 1].c <= c) i++;
    const a = levels[i];
    if (a.c === c || i === levels.length - 1) {
      return { c: c, lat: a.lat, tps: a.tps, util: a.util, perReq: a.tps / a.c,
               measured: a.c === c, below: false, lo: a, hi: a };
    }
    const b = levels[i + 1];
    const f = (c - a.c) / (b.c - a.c);
    const lat = a.lat + f * (b.lat - a.lat);
    const tps = a.tps + f * (b.tps - a.tps);
    return { c: c, lat: lat, tps: tps, util: a.util + f * (b.util - a.util),
             perReq: tps / c, measured: false, below: false, lo: a, hi: b };
  }

  // Latency only, for the Little's Law comparison.
  function latencyAt(levels, c) {
    const r = curveAt(levels, c, false);
    return r ? r.lat : null;
  }

  /* ---- Little's Law --------------------------------------------------- */

  // Exactly one of L, lambda, W is null; solve it from the other two.
  function little(s) {
    const missing = ["L", "lambda", "W"].filter(function (k) { return s[k] === null; });
    if (missing.length !== 1) return null;
    const out = { L: s.L, lambda: s.lambda, W: s.W, solved: missing[0] };
    if (missing[0] === "L") out.L = s.lambda * s.W;
    else if (missing[0] === "lambda") out.lambda = s.W === 0 ? null : s.L / s.W;
    else out.W = s.lambda === 0 ? null : s.L / s.lambda;
    return out;
  }

  // probes: {"1": {"50": {offered, lambda, server_p50, workers: {"worker 1": mean}}}}
  function twoWorkerRows(probes, probeId) {
    const steps = probes[probeId];
    return Object.keys(steps).map(Number).sort(function (a, b) { return a - b; }).map(function (k) {
      const s = steps[String(k)];
      const names = Object.keys(s.workers).sort();
      const means = names.map(function (n) { return s.workers[n]; });
      const L = means.reduce(function (a, b) { return a + b; }, 0);
      const W = L / s.lambda;
      return { step: k, lambda: s.lambda, means: means, L: L, W: W,
               serverP50: s.server_p50, diff: (W - s.server_p50) / s.server_p50 };
    });
  }

  // One worker carried the step. L is that worker's mean in flight.
  function oneWorkerRows(probes, levels, probeIds) {
    const rows = [];
    probeIds.forEach(function (pid) {
      const steps = probes[pid];
      Object.keys(steps).map(Number).sort(function (a, b) { return a - b; }).forEach(function (k) {
        const s = steps[String(k)];
        const names = Object.keys(s.workers);
        if (names.length !== 1) return;
        const L = s.workers[names[0]];
        const W = L / s.lambda;
        const curve = latencyAt(levels, L);
        rows.push({ probe: pid, step: k, lambda: s.lambda, L: L, W: W,
                    serverP50: s.server_p50, curve: curve,
                    diffCurve: curve === null ? null : (W - curve) / curve });
      });
    });
    return rows;
  }

  /* ---- frontiers: a line-for-line mirror of autoscale.frontier -------- */

  const TIE_REL = 1e-9;
  function isClose(a, b) {
    return Math.abs(a - b) <= TIE_REL * Math.max(Math.abs(a), Math.abs(b));
  }

  // points: [{cost, p99, ...}]. Ascending by cost. Costs within TIE_REL count
  // as equal and only the best-p99 point of a tied group survives.
  function pareto(points) {
    if (!points.length) throw new Error("cannot compute a frontier from an empty point set");
    const ordered = points.slice().sort(function (a, b) {
      return (a.cost - b.cost) || (a.p99 - b.p99);
    });
    const frontier = [];
    let best = Infinity;
    ordered.forEach(function (p) {
      if (frontier.length && isClose(p.cost, frontier[frontier.length - 1].cost)) {
        if (p.p99 < frontier[frontier.length - 1].p99) {
          frontier[frontier.length - 1] = p;
          best = p.p99;
        }
        return;
      }
      if (p.p99 < best) {
        frontier.push(p);
        best = p.p99;
      }
    });
    return frontier;
  }

  // The pre-registered budget: the cheapest spend at which every signal has a policy.
  function isoBudget(frontiers) {
    let b = -Infinity;
    Object.keys(frontiers).forEach(function (s) {
      const floor = Math.min.apply(null, frontiers[s].map(function (p) { return p.cost; }));
      if (floor > b) b = floor;
    });
    return b;
  }

  function affordable(cost, budget) { return cost <= budget || isClose(cost, budget); }

  // Best p99 at or under `budget` on one frontier; null when none is affordable.
  function bestAtBudget(frontier, budget) {
    let best = null;
    frontier.forEach(function (p) {
      if (affordable(p.cost, budget) && (best === null || p.p99 < best.p99)) best = p;
    });
    return best;
  }

  // The whole frontier of one sweep: {signal: [points]} from {signal: [[cost,p99,up,down]]}.
  function sweepFrontiers(policies) {
    const out = {};
    Object.keys(policies).forEach(function (sig) {
      const pts = policies[sig].map(function (r) {
        return { cost: r[0], p99: r[1], up: r[2], down: r[3], signal: sig };
      });
      out[sig] = { points: pts, frontier: pareto(pts) };
    });
    return out;
  }

  // Dominated in the page's two-policy exercise: another is at least as good
  // on both axes and better on one.
  function dominatedFlags(pts) {
    return pts.map(function (p, i) {
      return pts.some(function (q, j) {
        return j !== i && q.cost <= p.cost && q.dmg <= p.dmg && (q.cost < p.cost || q.dmg < p.dmg);
      });
    });
  }

  /* ---- the toy fluid simulation (module 4) ---------------------------- */

  // One policy: add a replica when requests waiting per serving replica reach
  // `upAt`, at most one per `cooldown`, checked every `evalEvery` seconds. Scale-down
  // is left out, so the picture is of the spike itself. Rejected: a discrete-event
  // model like autoscale.sim, which would need the curve and per-request latency and
  // would stop being a toy that fits in this page.
  function toy(p) {
    const dt = 0.25;
    const n = Math.round(p.until / dt);
    const everyN = Math.round(p.evalEvery / dt);
    const peak = p.peakX * p.sat;
    let B = 0, ready = 1, requested = 1, last = null;
    const pending = [];
    const out = { t: [], lam: [], cap: [], requested: [], ready: [], wait: [], B: [] };
    let peakB = 0, peakWait = 0, above = 0, firstReq = null, firstReady = null;
    for (let i = 0; i <= n; i++) {
      const t = i * dt;
      while (pending.length && pending[0] <= t) {
        pending.shift();
        ready++;
        if (firstReady === null) firstReady = t;
      }
      if (i > 0 && i % everyN === 0) {
        const signal = B / ready;
        const cool = last === null || t - last >= p.cooldown;
        if (cool && signal >= p.upAt && requested < p.maxReplicas) {
          requested++;
          pending.push(t + p.lag);
          last = t;
          if (firstReq === null) firstReq = t;
        }
      }
      const lam = (t >= p.spikeStart && t < p.spikeStart + p.sustain) ? peak : p.base;
      const wait = B / (p.sat * ready);
      out.t.push(t); out.lam.push(lam); out.cap.push(p.sat * ready);
      out.requested.push(requested); out.ready.push(ready); out.wait.push(wait); out.B.push(B);
      if (B > peakB) peakB = B;
      if (wait > peakWait) peakWait = wait;
      if (wait > 1) above += dt;
      B = Math.max(0, B + (lam - p.sat * ready) * dt);
    }
    out.peakB = peakB;
    out.peakWait = peakWait;
    out.secondsAbove1 = above;
    out.requestedFinal = requested;
    out.needed = Math.ceil(p.peakX - 1e-9);
    out.firstReq = firstReq;
    out.firstReady = firstReady;
    out.peak = peak;
    return out;
  }

  /* ---- the validation gate's counting rule, as a Monte Carlo ---------- */

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function gauss(rng) {
    const u1 = Math.max(rng(), 1e-12);
    const u2 = rng();
    return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  }

  // Abramowitz and Stegun 7.1.26, error under 1.5e-7.
  function erf(x) {
    const s = x < 0 ? -1 : 1;
    const a = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * a);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
      + 0.254829592) * t * Math.exp(-a * a);
    return s * y;
  }
  function normCdf(x) { return 0.5 * (1 + erf(x / Math.SQRT2)); }

  // The chance a model with no error at all misses a bin: all three repeats
  // land more than `tol` above the prediction, or all three more than `tol`
  // below. It tends to 2 x (1/2)^3 = 1/4 as the spread dwarfs the margin.
  function perfectMissProb(spread, truth, tol) {
    if (spread <= 0) return 0;
    const q = 1 - normCdf(tol / (spread * truth));
    return 2 * q * q * q;
  }

  // One synthetic validation: p.bins bins, three repeats each.
  // A repeat is truth x (1 + spread x noise); the prediction is truth x factor.
  // A bin misses when every repeat is more than `tol` above, or every repeat is
  // more than `tol` below, the prediction (compare_per_repeat's rule).
  // `noise`, when given, is bins x 3 draws made earlier, so a page can move the
  // sliders over one fixed draw and only a rerun changes the luck.
  function mcNoise(rng, bins) {
    const out = [];
    for (let i = 0; i < bins * 3; i++) out.push(gauss(rng));
    return out;
  }

  function mcRun(p, rng, noise) {
    const bins = [];
    let misses = 0;
    for (let i = 0; i < p.bins; i++) {
      const pred = p.truth * p.factor;
      const reps = [0, 1, 2].map(function (k) {
        return p.truth * (1 + p.spread * (noise ? noise[i * 3 + k] : gauss(rng)));
      });
      const above = reps.every(function (r) { return r - p.tol > pred; });
      const below = reps.every(function (r) { return r + p.tol < pred; });
      const miss = above || below;
      if (miss) misses++;
      bins.push({ reps: reps, pred: pred, miss: miss, side: above ? 1 : (below ? -1 : 0) });
    }
    return { bins: bins, misses: misses };
  }

  // The gate passes when at least minBins bins are judged and no more than
  // maxMissFraction of them miss.
  function mcPasses(misses, judged, minBins, maxMissFraction) {
    return judged >= minBins && misses <= maxMissFraction * judged;
  }

  function mcMany(p, rng, runs) {
    let total = 0, passes = 0;
    const hist = new Array(p.bins + 1).fill(0);
    for (let r = 0; r < runs; r++) {
      const m = mcRun(p, rng).misses;
      total += m;
      hist[m]++;
      if (mcPasses(m, p.bins, p.minBins, p.maxMissFraction)) passes++;
    }
    return { meanMissFraction: total / (runs * p.bins), passShare: passes / runs, hist: hist };
  }

  /* ---- chart helpers --------------------------------------------------- */

  // matplotlib's symlog (base 10, linscale 0.5), the treatment the post's
  // residual figure uses: linear within +-lin, logarithmic beyond.
  const LINSCALE_ADJ = 0.5 / (1 - 1 / 10);
  function symlog(y, lin) {
    const a = Math.abs(y);
    if (a <= lin) return y / lin * LINSCALE_ADJ;
    return Math.sign(y) * (LINSCALE_ADJ + Math.log10(a / lin));
  }

  function niceTicks(lo, hi, n) {
    const span = hi - lo;
    const raw = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const out = [];
    for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) {
      out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    }
    return out;
  }

  return {
    curveAt: curveAt, latencyAt: latencyAt, little: little,
    twoWorkerRows: twoWorkerRows, oneWorkerRows: oneWorkerRows,
    isClose: isClose, pareto: pareto, isoBudget: isoBudget, affordable: affordable,
    bestAtBudget: bestAtBudget, sweepFrontiers: sweepFrontiers,
    dominatedFlags: dominatedFlags, toy: toy,
    mulberry32: mulberry32, gauss: gauss, erf: erf, normCdf: normCdf,
    perfectMissProb: perfectMissProb, mcNoise: mcNoise, mcRun: mcRun, mcPasses: mcPasses, mcMany: mcMany,
    symlog: symlog, niceTicks: niceTicks
  };
})();
