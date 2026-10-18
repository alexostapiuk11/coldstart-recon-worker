/* The page's widgets. DOM and SVG only; every calculation is in lib.js (A2) and every
 * number comes from the embedded data (D), which the build derived from committed
 * files. Charts are drawn at the container's pixel width, so text stays 12 px on a
 * phone instead of shrinking with a scaled viewBox. */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const D = JSON.parse(document.getElementById("a2-data").textContent);
  const $ = function (id) { return document.getElementById(id); };

  /* ---- small helpers ---------------------------------------------------- */

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(parent, x, y, s, cls, anchor, rot) {
    const t = el("text", { x: x, y: y, "text-anchor": anchor || "start" }, parent);
    if (cls) t.setAttribute("class", cls);
    if (rot) t.setAttribute("transform", "rotate(" + rot + " " + x + " " + y + ")");
    t.textContent = s;
    return t;
  }
  function fmt(n, d) {
    return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function sig4(n) { return String(Number(n.toPrecision(4))); }
  function pct(x, d) { return fmt(x * 100, d) + "%"; }
  function signedPct(x) {
    const a = Math.abs(x) * 100;
    return (fmt(a, 1) === "0.0" ? "" : (x >= 0 ? "+" : "−")) + fmt(a, 1) + "%";
  }
  function svgRoot(host, w, h, label) {
    host.textContent = "";
    const s = el("svg", { viewBox: "0 0 " + w + " " + h, width: w, height: h, role: "img",
                          "aria-label": label });
    host.appendChild(s);
    return s;
  }
  function path(parent, pts, cls) {
    const d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join("");
    return el("path", { d: d, class: cls }, parent);
  }
  // Marker shapes carry the signal as well as colour: circle for queue depth,
  // square for in-flight concurrency, triangle for utilisation.
  const SIG = {
    queue_depth: { cls: "sq", line: "line-q", name: "queue depth", shape: "circle" },
    in_flight_concurrency: { cls: "sf", line: "line-f", name: "in-flight concurrency", shape: "square" },
    utilization: { cls: "su", line: "line-u", name: "utilisation", shape: "tri" }
  };
  function mark(parent, shape, x, y, r, cls, hollow) {
    let e;
    if (shape === "circle") e = el("circle", { cx: x, cy: y, r: r }, parent);
    else if (shape === "square") e = el("rect", { x: x - r, y: y - r, width: 2 * r, height: 2 * r }, parent);
    else e = el("path", { d: "M" + x + " " + (y - r * 1.2) + "L" + (x + r * 1.15) + " " + (y + r * 0.85) + "L" + (x - r * 1.15) + " " + (y + r * 0.85) + "Z" }, parent);
    e.setAttribute("class", hollow ? "grey" : cls);
    return e;
  }
  // Re-draw a chart whenever its container's width changes. Returns a function that
  // forces a redraw after state changes.
  function responsive(host, draw) {
    let last = -1;
    function run(force) {
      const w = Math.floor(host.clientWidth);
      if (w > 0 && (force === true || w !== last)) { last = w; draw(w); }
    }
    if ("ResizeObserver" in window) new ResizeObserver(function () { run(false); }).observe(host);
    window.addEventListener("resize", function () { run(false); });
    run(true);
    return function () { run(true); };
  }
  function on(id, ev, fn) { $(id).addEventListener(ev, fn); }

  const LV = D.curve.levels;
  const PEAK_TPS = Math.max.apply(null, LV.map(function (l) { return l.tps; }));

  /* ---- module 1: the service curve ------------------------------------ */

  (function () {
    const state = { c: 64, failed: false };
    const slider = $("w1-conc");
    const snaps = $("w1-snaps");
    const ex = D.curve.excluded;
    const buttons = [];
    LV.concat([{ c: ex.c, fail: true }]).forEach(function (lv) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn"; b.textContent = String(lv.c);
      b.setAttribute("aria-pressed", "false");
      if (lv.fail) b.setAttribute("aria-label", lv.c + ", the level that could not be served");
      b.addEventListener("click", function () {
        state.failed = !!lv.fail;
        if (!lv.fail) { state.c = lv.c; slider.value = String(Math.round(Math.log2(lv.c) * 100)); }
        update();
      });
      snaps.appendChild(b);
      buttons.push({ b: b, lv: lv });
    });

    function update() {
      const c = state.c;
      slider.setAttribute("aria-valuetext", state.failed ? String(ex.c) + ", not served" : c + " in flight");
      $("w1-out-conc").textContent = state.failed ? String(ex.c) : String(c);
      const msg = $("w1-msg");
      msg.className = "msg";
      if (state.failed) {
        msg.className = "msg fail";
        msg.textContent = ex.c + " could not be served: the engine ran out of memory at its first step in "
          + ex.runs + " of " + ex.runs + " runs, and 0 of " + fmt(ex.requests, 0) + " requests were served. max-num-seqs was "
          + D.curve.max_num_seqs + ", so the engine would have accepted that many at once.";
        $("w1-lat").textContent = "none"; $("w1-lat-sub").textContent = "no request was served";
        $("w1-tps").textContent = "none"; $("w1-tps-sub").textContent = "";
        $("w1-per").textContent = "none"; $("w1-per-sub").textContent = "";
      } else {
        const r = A2.curveAt(LV, c, false);
        $("w1-lat").textContent = fmt(r.lat, 3) + " s";
        $("w1-tps").textContent = fmt(r.tps, 0) + " tokens/s";
        $("w1-per").textContent = fmt(r.perReq, 1) + " tokens/s";
        if (r.measured) {
          msg.textContent = c + " in flight is a measured level (" + D.curve.levels[0].c + " to "
            + LV[LV.length - 1].c + " were measured).";
          $("w1-lat-sub").textContent = "runs: " + fmt(r.lo.lat_lo, 3) + " to " + fmt(r.lo.lat_hi, 3) + " s";
          $("w1-tps-sub").textContent = "runs: " + fmt(r.lo.tps_lo, 0) + " to " + fmt(r.lo.tps_hi, 0);
          $("w1-per-sub").textContent = "throughput ÷ " + c;
        } else {
          msg.textContent = c + " in flight is between the measured levels " + r.lo.c + " and "
            + r.hi.c + ", so these are straight-line interpolations.";
          $("w1-lat-sub").textContent = "interpolated";
          $("w1-tps-sub").textContent = "interpolated";
          $("w1-per-sub").textContent = "throughput ÷ " + c;
        }
      }
      buttons.forEach(function (o) {
        const on = o.lv.fail ? state.failed : (!state.failed && o.lv.c === c);
        o.b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      redraw();
    }
    slider.addEventListener("input", function () {
      state.failed = false;
      state.c = Math.max(1, Math.min(128, Math.round(Math.pow(2, Number(slider.value) / 100))));
      update();
    });

    function draw(w) {
      const phone = w < 540;
      const ml = phone ? 46 : 58, mr = phone ? 12 : 18, top = 22, ph = phone ? 104 : 118, gap = 32, bot = 34;
      const H = top + 3 * ph + 2 * gap + bot;
      const svg = svgRoot($("w1-chart"), w, H,
        "Three stacked charts against requests in flight, 1 to 128 measured and 256 not served: latency, total throughput and per-request speed.");
      const lx = Math.log2(256);
      const X = function (c) { return ml + (Math.log2(c) / lx) * (w - ml - mr); };
      const panels = [
        { label: "latency (s)", max: 0.7, ticks: [0, 0.2, 0.4, 0.6], f: function (r) { return r.lat; }, d: 1,
          bars: function (l) { return [l.lat_lo, l.lat_hi]; }, val: function (l) { return l.lat; } },
        { label: "throughput (tokens/s)", max: 3600, ticks: [0, 1000, 2000, 3000], f: function (r) { return r.tps; }, d: 0,
          bars: function (l) { return [l.tps_lo, l.tps_hi]; }, val: function (l) { return l.tps; } },
        { label: "per request (tokens/s)", max: 60, ticks: [0, 20, 40, 60], f: function (r) { return r.perReq; }, d: 0,
          bars: null, val: function (l) { return l.tps / l.c; } }
      ];
      panels.forEach(function (p, i) {
        const y0 = top + i * (ph + gap);
        const Y = function (v) { return y0 + ph - (v / p.max) * ph; };
        // the level that could not be served
        const xa = X(128), xb = X(256);
        el("rect", { x: xa, y: y0, width: xb - xa, height: ph, class: "shade" }, svg);
        for (let k = 0; k <= 8; k++) el("line", { x1: X(Math.pow(2, k)), x2: X(Math.pow(2, k)), y1: y0, y2: y0 + ph, class: "grid" }, svg);
        p.ticks.forEach(function (t) {
          el("line", { x1: ml, x2: w - mr, y1: Y(t), y2: Y(t), class: "grid" }, svg);
          txt(svg, ml - 6, Y(t) + 4, t >= 1000 ? fmt(t, 0) : String(t), "", "end");
        });
        el("line", { x1: ml, x2: ml, y1: y0, y2: y0 + ph, class: "axis" }, svg);
        txt(svg, ml, y0 - 7, p.label, "title");
        // the curve, sampled on a log grid so the drawn line is the one the readout interpolates
        const pts = [];
        for (let k = 0; k <= 140; k++) {
          const c = Math.pow(2, (k / 140) * 7);
          pts.push([X(c), Y(p.f(A2.curveAt(LV, Math.min(c, 128), false)))]);
        }
        path(svg, pts, "line-ink");
        LV.forEach(function (l) {
          if (p.bars) {
            const b = p.bars(l);
            el("line", { x1: X(l.c), x2: X(l.c), y1: Y(b[0]), y2: Y(b[1]), class: "bar" }, svg);
          }
          el("circle", { cx: X(l.c), cy: Y(p.val(l)), r: 4, class: "dot-open" }, svg);
        });
        if (i === 0) {
          const cx = (xa + xb) / 2;
          txt(svg, cx + 4, y0 + ph - 8, "not served", "fail", "start", -90);
        }
        // cursor
        if (state.failed) {
          el("line", { x1: X(256), x2: X(256), y1: y0, y2: y0 + ph, class: "fail" }, svg);
        } else {
          const r = A2.curveAt(LV, state.c, false);
          el("line", { x1: X(state.c), x2: X(state.c), y1: y0, y2: y0 + ph, class: "cursor" }, svg);
          el("circle", { cx: X(state.c), cy: Y(p.f(r)), r: 5, class: "dot-ink" }, svg);
        }
      });
      const yb = top + 3 * ph + 2 * gap;
      el("line", { x1: ml, x2: w - mr, y1: yb, y2: yb, class: "axis" }, svg);
      [1, 2, 4, 8, 16, 32, 64, 128, 256].forEach(function (c) {
        if (phone && (c === 2 || c === 8 || c === 32)) return;
        txt(svg, X(c), yb + 16, String(c), c === 256 ? "fail" : "", "middle");
      });
      txt(svg, (ml + w - mr) / 2, yb + 31, "requests in flight (log scale)", "", "middle");
    }
    const redraw = responsive($("w1-chart"), draw);
    update();
  })();

  /* ---- module 2: Little's Law ----------------------------------------- */

  (function () {
    const ids = { L: "w2-l", lambda: "w2-lambda", W: "w2-w" };
    const sym = { L: "L", lambda: "λ", W: "W" };
    function solveKey() {
      return document.querySelector('input[name="w2-solve"]:checked').value;
    }
    function calc() {
      const k = solveKey();
      const v = {};
      Object.keys(ids).forEach(function (n) {
        const inp = $(ids[n]);
        inp.readOnly = n === k;
        inp.setAttribute("aria-readonly", n === k ? "true" : "false");
        v[n] = n === k ? null : parseFloat(inp.value);
      });
      const ok = Object.keys(v).every(function (n) { return n === k || isFinite(v[n]); });
      const out = $("w2-arith");
      if (!ok) { out.textContent = "Enter a number in the other two boxes."; return; }
      const r = A2.little(v);
      if (r === null || r[k] === null || !isFinite(r[k])) { out.textContent = "Dividing by zero has no answer here."; return; }
      $(ids[k]).value = sig4(r[k]);
      if (k === "L") out.textContent = "L = λ × W = " + sig4(r.lambda) + " × " + sig4(r.W) + " = " + sig4(r.L);
      else if (k === "lambda") out.textContent = "λ = L ÷ W = " + sig4(r.L) + " ÷ " + sig4(r.W) + " = " + sig4(r.lambda);
      else out.textContent = "W = L ÷ λ = " + sig4(r.L) + " ÷ " + sig4(r.lambda) + " = " + sig4(r.W);
    }
    Object.keys(ids).forEach(function (n) { $(ids[n]).addEventListener("input", calc); });
    document.querySelectorAll('input[name="w2-solve"]').forEach(function (r) { r.addEventListener("change", calc); });
    function preset(label, solve, vals) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn"; b.textContent = label;
      b.addEventListener("click", function () {
        document.querySelector('input[name="w2-solve"][value="' + solve + '"]').checked = true;
        Object.keys(vals).forEach(function (n) { $(ids[n]).value = String(Number(vals[n].toPrecision(5))); });
        calc();
      });
      $("w2-presets").appendChild(b);
    }
    const r1 = A2.twoWorkerRows(D.probes, "1");
    const r50 = r1.filter(function (r) { return r.step === 50; })[0];
    preset("Probe 1 at 50 req/s offered: solve for W", "W", { L: r50.L, lambda: r50.lambda });
    preset("The cap: " + D.cap_example.in_flight + " in flight at " + D.cap_example.w + " s: solve for λ", "lambda",
      { L: D.cap_example.in_flight, W: D.cap_example.w });
    calc();

    // table 1: probe 1
    const t1 = $("w2-t1");
    t1.innerHTML = "<caption>Probe 1: time in the engine per request</caption><thead><tr>"
      + "<th>Offered (req/s)</th><th>Delivered λ (req/s)</th><th>Worker 1, mean in flight</th>"
      + "<th>Worker 2, mean in flight</th><th>L, the sum</th><th>W = L ÷ λ (s)</th>"
      + "<th>Engine&rsquo;s own p50 (s)</th><th>W against p50</th></tr></thead><tbody></tbody>";
    const tb1 = t1.querySelector("tbody");
    r1.forEach(function (r) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r.step + "</td><td>" + fmt(r.lambda, 2) + "</td><td>" + fmt(r.means[0], 2)
        + "</td><td>" + fmt(r.means[1], 2) + "</td><td>" + fmt(r.L, 2) + "</td><td>" + fmt(r.W, 3)
        + "</td><td>" + fmt(r.serverP50, 3) + "</td><td>" + signedPct(r.diff) + "</td>";
      tb1.appendChild(tr);
    });
    $("w2-arith1").textContent = "At 50 req/s offered: (" + fmt(r50.means[0], 2) + " + " + fmt(r50.means[1], 2)
      + ") ÷ " + fmt(r50.lambda, 2) + " = " + fmt(r50.W, 3) + " s in the engine, against the engine's p50 of "
      + fmt(r50.serverP50, 3) + " s.";

    // table 2: one worker, against the curve
    const rows = A2.oneWorkerRows(D.probes, LV, ["2", "3"]);
    const t2 = $("w2-t2");
    t2.innerHTML = "<caption>Probes 2 and 3: one worker, against the service curve</caption><thead><tr>"
      + "<th>Probe</th><th>Offered (req/s)</th><th>Delivered λ (req/s)</th><th>Mean in flight, L</th>"
      + "<th>W = L ÷ λ (s)</th><th>Engine&rsquo;s own p50 (s)</th><th>Curve&rsquo;s latency at L (s)</th>"
      + "<th>W against the curve</th></tr></thead><tbody></tbody>";
    const tb2 = t2.querySelector("tbody");
    rows.forEach(function (r) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r.probe + "</td><td>" + r.step + "</td><td>" + fmt(r.lambda, 2) + "</td><td>" + fmt(r.L, 2)
        + "</td><td>" + fmt(r.W, 3) + "</td><td>" + fmt(r.serverP50, 3) + "</td><td>" + fmt(r.curve, 3)
        + "</td><td>" + signedPct(r.diffCurve) + "</td>";
      tb2.appendChild(tr);
    });
    const ex = rows.filter(function (r) { return r.probe === "2" && r.step === 100; })[0];
    if (ex) {
      const cv = A2.curveAt(LV, ex.L, false);
      $("w2-arith2").textContent = "Probe 2 at 100 req/s: W = " + fmt(ex.L, 2) + " ÷ " + fmt(ex.lambda, 2) + " = " + fmt(ex.W, 3)
        + " s. The curve at " + fmt(ex.L, 2) + " in flight lies between " + cv.lo.c + " (" + fmt(cv.lo.lat, 3) + " s) and "
        + cv.hi.c + " (" + fmt(cv.hi.lat, 3) + " s), which interpolates to " + fmt(ex.curve, 3) + " s. W is "
        + fmt(Math.abs(ex.diffCurve) * 100, 1) + "% below it.";
    }
  })();

  /* ---- module 3: why utilisation is blind ----------------------------- */

  (function () {
    const gu = D.grids.util, gf = D.grids.flight;
    const su = $("w3-u"), sf = $("w3-f");
    function update() {
      const tu = gu[Number(su.value)], tf = gf[Number(sf.value)];
      $("w3-out-u").textContent = String(tu);
      $("w3-out-f").textContent = String(tf);
      // Utilisation reads 0 when idle and 1.0 at the first measured level, so the
      // straight line between them reaches a threshold t at t requests in flight.
      const cu = tu / LV[0].util;
      const cf = tf;
      function describe(c, id) {
        const r = A2.curveAt(LV, c, true);
        $(id).textContent = fmt(c, c < 1 ? 2 : 0) + (c === 1 ? " request in flight" : " in flight");
        $(id + "-sub").textContent = fmt(r.tps, 0) + " tokens/s, " + pct(r.tps / PEAK_TPS, 1) + " of the peak "
          + fmt(PEAK_TPS, 0) + "; latency " + fmt(r.lat, 3) + " s";
      }
      describe(cu, "w3-cu");
      describe(cf, "w3-cf");
      state.tu = tu; state.tf = tf; state.cu = cu; state.cf = cf;
      redraw();
    }
    const state = {};
    su.addEventListener("input", update);
    sf.addEventListener("input", update);

    function draw(w) {
      if (state.tu === undefined) return;
      const phone = w < 540;
      const ml = phone ? 46 : 58, mr = phone ? 12 : 18, top = 22, ph1 = phone ? 96 : 110, ph2 = phone ? 130 : 150, gap = 32, bot = 34;
      const H = top + ph1 + gap + ph2 + bot;
      const svg = svgRoot($("w3-chart"), w, H,
        "Two charts against load on one replica, on a log scale. Top: utilisation reads 1.0 from one request in flight. Bottom: requests in flight per replica rise to 128, and requests waiting rise after that.");
      const lo = Math.log2(0.25), hi = Math.log2(192);
      const X = function (c) { return ml + ((Math.log2(c) - lo) / (hi - lo)) * (w - ml - mr); };
      const y1 = top, y2 = top + ph1 + gap;
      const U = function (v) { return y1 + ph1 - v * ph1; };
      const R = function (v) { return y2 + ph2 - (v / 140) * ph2; };
      [[y1, ph1], [y2, ph2]].forEach(function (pp) {
        el("rect", { x: X(128), y: pp[0], width: X(192) - X(128), height: pp[1], class: "shade" }, svg);
        [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128].forEach(function (c) {
          el("line", { x1: X(c), x2: X(c), y1: pp[0], y2: pp[0] + pp[1], class: "grid" }, svg);
        });
        el("line", { x1: ml, x2: ml, y1: pp[0], y2: pp[0] + pp[1], class: "axis" }, svg);
      });
      [0, 0.5, 1].forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: U(v), y2: U(v), class: "grid" }, svg);
        txt(svg, ml - 6, U(v) + 4, String(v), "", "end");
      });
      [0, 40, 80, 120].forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: R(v), y2: R(v), class: "grid" }, svg);
        txt(svg, ml - 6, R(v) + 4, String(v), "", "end");
      });
      txt(svg, ml, y1 - 7, "utilisation (0 to 1)", "title");
      txt(svg, ml, y2 - 7, "requests per replica", "title");
      // utilisation: dashed from idle to the first level, then the measured levels
      el("line", { x1: X(0.25), y1: U(0.25), x2: X(LV[0].c), y2: U(LV[0].util), class: "line-u dot" }, svg);
      path(svg, LV.map(function (l) { return [X(l.c), U(l.util)]; }), "line-u");
      LV.forEach(function (l) { mark(svg, "tri", X(l.c), U(l.util), 5, "su"); });
      // in flight and waiting
      const fl = [], wq = [];
      for (let k = 0; k <= 120; k++) {
        const c = Math.pow(2, lo + (k / 120) * (hi - lo));
        fl.push([X(c), R(Math.min(c, 128))]);
        if (c >= 128) wq.push([X(c), R(c - 128)]);
      }
      path(svg, fl, "line-f");
      path(svg, wq, "line-q");
      LV.forEach(function (l) { mark(svg, "square", X(l.c), R(l.c), 4, "sf"); });
      txt(svg, X(128) + (X(192) - X(128)) * 0.32, R(26), "waiting", "", "start", -90);
      txt(svg, X(192) - 4, R(138), "in flight, capped", "", "end");
      txt(svg, X(128) - 6, y1 + ph1 - 6, "past the curve ›", "", "end");
      // thresholds
      el("line", { x1: ml, x2: w - mr, y1: U(state.tu), y2: U(state.tu), class: "line-u dash" }, svg);
      el("line", { x1: X(state.cu), x2: X(state.cu), y1: y1, y2: y1 + ph1, class: "line-u dash" }, svg);
      el("line", { x1: ml, x2: w - mr, y1: R(state.tf), y2: R(state.tf), class: "line-f dash" }, svg);
      el("line", { x1: X(state.cf), x2: X(state.cf), y1: y2, y2: y2 + ph2, class: "line-f dash" }, svg);
      el("line", { x1: X(state.cu), x2: X(state.cu), y1: y2, y2: y2 + ph2, class: "line-u dash" }, svg);
      const yb = y2 + ph2;
      el("line", { x1: ml, x2: w - mr, y1: yb, y2: yb, class: "axis" }, svg);
      [0.5, 1, 4, 16, 64, 128].forEach(function (c) { txt(svg, X(c), yb + 16, String(c), "", "middle"); });
      txt(svg, (ml + w - mr) / 2, yb + 31, "requests offered to one replica (log scale)", "", "middle");
    }
    const redraw = responsive($("w3-chart"), draw);
    update();
  })();

  /* ---- module 4: the toy ------------------------------------------------ */

  (function () {
    const T = D.toy;
    const lag = $("w4-lag"), cool = $("w4-cool"), peak = $("w4-peak");
    let res = null;
    // The slider moves in whole seconds; the snap buttons set the measured median
    // exactly, which the slider's step cannot hold, so the exact lag lives here.
    let lagS = T.lag_A;
    lag.value = String(Math.round(lagS));
    function update() {
      $("w4-out-lag").textContent = (lagS % 1 ? fmt(lagS, 2) : fmt(lagS, 0)) + " s";
      $("w4-out-cool").textContent = cool.value + " s";
      $("w4-out-peak").textContent = Number(peak.value).toFixed(2) + "×";
      res = A2.toy({ lag: lagS, cooldown: Number(cool.value), peakX: Number(peak.value),
        sat: T.sat, base: T.base, sustain: T.sustain, until: T.until, evalEvery: T.eval_every,
        maxReplicas: T.max_replicas, spikeStart: T.spike_start, upAt: T.up_at });
      $("w4-r-b").textContent = fmt(res.peakB, 0);
      $("w4-r-w").textContent = fmt(res.peakWait, 1) + " s";
      $("w4-r-t").textContent = fmt(res.secondsAbove1, 0) + " s";
      $("w4-r-n").textContent = String(res.requestedFinal);
      const over = res.requestedFinal - res.needed;
      $("w4-r-n-sub").textContent = res.needed + " needed for the peak" + (over > 0 ? ", " + over + " more than that" : "");
      if (res.firstReq === null) {
        $("w4-r-d").textContent = "none"; $("w4-r-d-sub").textContent = "no replica was requested";
      } else if (res.firstReady === null) {
        $("w4-r-d").textContent = "never"; $("w4-r-d-sub").textContent = "the window ended first";
      } else {
        $("w4-r-d").textContent = fmt(res.firstReady - res.firstReq, 0) + " s";
        $("w4-r-d-sub").textContent = "asked at " + fmt(res.firstReq, 0) + " s, ready at " + fmt(res.firstReady, 0) + " s";
      }
      redraw();
    }
    [cool, peak].forEach(function (s) { s.addEventListener("input", update); });
    lag.addEventListener("input", function () { lagS = Number(lag.value); update(); });
    on("w4-snapA", "click", function () { lagS = T.lag_A; lag.value = String(Math.round(lagS)); update(); });
    on("w4-snapC", "click", function () { lagS = T.lag_C; lag.value = String(Math.round(lagS)); update(); });
    on("w4-peak-reset", "click", function () { peak.value = String(T.peak_x.toFixed(2)); update(); });

    function draw(w) {
      if (!res) return;
      const phone = w < 540;
      const ml = phone ? 46 : 58, mr = phone ? 12 : 18, top = 22, ph = phone ? 96 : 108, gap = 32, bot = 34;
      const H = top + 3 * ph + 2 * gap + bot;
      const svg = svgRoot($("w4-chart"), w, H,
        "Three stacked charts over the 400 second window. Traffic against ready capacity, replicas requested against ready, and queue wait in seconds.");
      const X = function (t) { return ml + (t / T.until) * (w - ml - mr); };
      const P = [top, top + ph + gap, top + 2 * (ph + gap)];
      P.forEach(function (y0) {
        for (let t = 0; t <= T.until; t += 50) el("line", { x1: X(t), x2: X(t), y1: y0, y2: y0 + ph, class: "grid" }, svg);
        el("line", { x1: ml, x2: ml, y1: y0, y2: y0 + ph, class: "axis" }, svg);
      });
      // spike marker band
      P.forEach(function (y0) {
        el("rect", { x: X(T.spike_start), y: y0, width: X(T.spike_start + T.sustain) - X(T.spike_start), height: ph, class: "shade" }, svg);
      });
      const idx = []; for (let i = 0; i < res.t.length; i += 1) idx.push(i);
      // panel 1: traffic and capacity
      const maxRate = Math.max.apply(null, res.lam.concat(res.cap)) * 1.08;
      const Y1 = function (v) { return P[0] + ph - (v / maxRate) * ph; };
      niceTicksFor(0, maxRate, 3).forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: Y1(v), y2: Y1(v), class: "grid" }, svg);
        txt(svg, ml - 6, Y1(v) + 4, fmt(v, 0), "", "end");
      });
      // where traffic exceeds capacity
      const over = [[X(0), Y1(0)]];
      let area = "";
      idx.forEach(function (i) {
        const lamv = res.lam[i], capv = res.cap[i];
        if (lamv > capv) area += (area ? "L" : "M") + X(res.t[i]).toFixed(1) + " " + Y1(lamv).toFixed(1);
      });
      let back = "";
      for (let k = idx.length - 1; k >= 0; k--) {
        const i = idx[k];
        if (res.lam[i] > res.cap[i]) back += "L" + X(res.t[i]).toFixed(1) + " " + Y1(res.cap[i]).toFixed(1);
      }
      if (area) el("path", { d: area + back + "Z", class: "toy-fill" }, svg);
      path(svg, idx.map(function (i) { return [X(res.t[i]), Y1(res.lam[i])]; }), "line-soft");
      path(svg, idx.map(function (i) { return [X(res.t[i]), Y1(res.cap[i])]; }), "line-ink");
      txt(svg, ml, P[0] - 7, "req/s: traffic, ready capacity", "title");
      // panel 2: replicas
      const maxRep = Math.max(res.requestedFinal, res.needed) + 1;
      const Y2 = function (v) { return P[1] + ph - (v / maxRep) * ph; };
      niceTicksFor(0, maxRep, 4).filter(function (v) { return v === Math.round(v); }).forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: Y2(v), y2: Y2(v), class: "grid" }, svg);
        txt(svg, ml - 6, Y2(v) + 4, String(v), "", "end");
      });
      let gapPath = "M" + X(0) + " " + Y2(res.requested[0]);
      idx.forEach(function (i) { gapPath += "L" + X(res.t[i]).toFixed(1) + " " + Y2(res.requested[i]).toFixed(1); });
      for (let k = idx.length - 1; k >= 0; k--) { gapPath += "L" + X(res.t[idx[k]]).toFixed(1) + " " + Y2(res.ready[idx[k]]).toFixed(1); }
      el("path", { d: gapPath + "Z", class: "toy-gap" }, svg);
      path(svg, idx.map(function (i) { return [X(res.t[i]), Y2(res.requested[i])]; }), "line-soft dash");
      path(svg, idx.map(function (i) { return [X(res.t[i]), Y2(res.ready[i])]; }), "line-ink");
      txt(svg, ml, P[1] - 7, "replicas: requested, ready", "title");
      // panel 3: queue wait
      const maxW = Math.max(res.peakWait * 1.1, 1.6);
      const Y3 = function (v) { return P[2] + ph - (Math.min(v, maxW) / maxW) * ph; };
      niceTicksFor(0, maxW, 3).forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: Y3(v), y2: Y3(v), class: "grid" }, svg);
        txt(svg, ml - 6, Y3(v) + 4, fmt(v, v < 5 ? 1 : 0), "", "end");
      });
      let hi = ""; let hiBack = "";
      idx.forEach(function (i) { if (res.wait[i] > 1) hi += (hi ? "L" : "M") + X(res.t[i]).toFixed(1) + " " + Y3(res.wait[i]).toFixed(1); });
      for (let k = idx.length - 1; k >= 0; k--) { if (res.wait[idx[k]] > 1) hiBack += "L" + X(res.t[idx[k]]).toFixed(1) + " " + Y3(1).toFixed(1); }
      if (hi) el("path", { d: hi + hiBack + "Z", class: "toy-fill" }, svg);
      el("line", { x1: ml, x2: w - mr, y1: Y3(1), y2: Y3(1), class: "line-soft dash" }, svg);
      path(svg, idx.map(function (i) { return [X(res.t[i]), Y3(res.wait[i])]; }), "line-q");
      txt(svg, ml, P[2] - 7, "queue wait (s)", "title");
      const yb = P[2] + ph;
      el("line", { x1: ml, x2: w - mr, y1: yb, y2: yb, class: "axis" }, svg);
      for (let t = 0; t <= T.until; t += phone ? 100 : 50) txt(svg, X(t), yb + 16, String(t), "", "middle");
      txt(svg, (ml + w - mr) / 2, yb + 31, "time (s); the spike is the shaded band", "", "middle");
    }
    function niceTicksFor(lo, hi, n) { return A2.niceTicks(lo, hi, n); }
    const redraw = responsive($("w4-chart"), draw);
    update();
  })();

  /* ---- module 5: frontiers --------------------------------------------- */

  (function () {
    const sel = $("w5-sweep"), bud = $("w5-budget");
    D.sweeps.forEach(function (s, i) {
      const o = document.createElement("option");
      o.value = String(i); o.textContent = s.label;
      sel.appendChild(o);
    });
    const F = D.sweeps.map(function (s) { return A2.sweepFrontiers(s.policies); });
    const order = ["queue_depth", "in_flight_concurrency", "utilization"];
    function cur() { return Number(sel.value); }

    function update() {
      const i = cur();
      const b = Number(bud.value);
      $("w5-out-budget").textContent = fmt(b, 0);
      const fr = {};
      order.forEach(function (s) { fr[s] = F[i][s].frontier; });
      $("w5-rule").textContent = fmt(A2.isoBudget(fr), 0);
      const box = $("w5-readouts");
      box.textContent = "";
      order.forEach(function (s) {
        const best = A2.bestAtBudget(fr[s], b);
        const d = document.createElement("div");
        d.className = "readout";
        const cheapest = Math.min.apply(null, fr[s].map(function (p) { return p.cost; }));
        d.innerHTML = "<span>" + SIG[s].name + ", best p99 within the spend</span><b>"
          + (best ? fmt(best.p99, best.p99 < 1 ? 3 : 2) + " s" : "none") + "</b><small>"
          + (best ? "at " + fmt(best.cost, 0) + " replica-seconds" : "its cheapest policy costs " + fmt(cheapest, 0)) + "</small>";
        box.appendChild(d);
      });
      redraw(); redrawStrip();
    }
    sel.addEventListener("change", update);
    bud.addEventListener("input", update);
    on("w5-snap", "click", function () {
      bud.value = String(Math.round(D.budget)); update();
    });

    function draw(w) {
      const phone = w < 540;
      const ml = 64, mr = phone ? 12 : 18, top = 22, ph = phone ? 270 : 330, bot = 40;
      const H = top + ph + bot;
      const i = cur();
      const svg = svgRoot($("w5-chart"), w, H,
        "Scatter of policies for " + D.sweeps[i].label + ": median cost in replica-seconds against median p99 in seconds, one mark per policy, frontier marks filled.");
      let ymin = Infinity, ymax = -Infinity;
      order.forEach(function (s) { F[i][s].points.forEach(function (p) { ymin = Math.min(ymin, p.p99); ymax = Math.max(ymax, p.p99); }); });
      const pad = (ymax - ymin) * 0.06 || 0.1;
      ymin = Math.max(0, ymin - pad); ymax += pad;
      const xmax = 3300;
      const X = function (c) { return ml + (c / xmax) * (w - ml - mr); };
      const Y = function (v) { return top + ph - ((v - ymin) / (ymax - ymin)) * ph; };
      A2.niceTicks(ymin, ymax, 5).forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: Y(v), y2: Y(v), class: "grid" }, svg);
        txt(svg, ml - 6, Y(v) + 4, fmt(v, (ymax - ymin) < 3 ? 2 : (ymax - ymin) < 12 ? 1 : 0), "", "end");
      });
      [0, 500, 1000, 1500, 2000, 2500, 3000].forEach(function (c) {
        el("line", { x1: X(c), x2: X(c), y1: top, y2: top + ph, class: "grid" }, svg);
        if (!phone || c % 1000 === 0) txt(svg, X(c), top + ph + 16, fmt(c, 0), "", "middle");
      });
      el("line", { x1: ml, x2: ml, y1: top, y2: top + ph, class: "axis" }, svg);
      el("line", { x1: ml, x2: w - mr, y1: top + ph, y2: top + ph, class: "axis" }, svg);
      txt(svg, (ml + w - mr) / 2, top + ph + 34, "median cost (replica-seconds)", "", "middle");
      txt(svg, 12, top + ph / 2, "median p99 (s)", "", "middle", -90);
      const b = Number(bud.value);
      order.forEach(function (s) {
        const fp = F[i][s].frontier;
        const onFront = new Set(fp);
        // staircase through the frontier
        const pts = [];
        fp.forEach(function (p, k) {
          pts.push([X(p.cost), Y(p.p99)]);
          if (k + 1 < fp.length) pts.push([X(fp[k + 1].cost), Y(p.p99)]);
        });
        pts.push([X(xmax), Y(fp[fp.length - 1].p99)]);
        path(svg, pts, SIG[s].line);
        F[i][s].points.forEach(function (p) {
          if (onFront.has(p)) return;
          const m = mark(svg, SIG[s].shape, X(p.cost), Y(p.p99), 4, SIG[s].cls, true);
          const t = el("title", {}, m);
          t.textContent = SIG[s].name + ", scale up at " + p.up + ", down at " + p.down + ": cost " + fmt(p.cost, 0) + ", p99 " + fmt(p.p99, 2) + " s (dominated)";
        });
        fp.forEach(function (p) {
          const m = mark(svg, SIG[s].shape, X(p.cost), Y(p.p99), 6, SIG[s].cls, false);
          const t = el("title", {}, m);
          t.textContent = SIG[s].name + ", scale up at " + p.up + ", down at " + p.down + ": cost " + fmt(p.cost, 0) + ", p99 " + fmt(p.p99, 2) + " s (on the frontier)";
        });
      });
      el("line", { x1: X(b), x2: X(b), y1: top, y2: top + ph, class: "cursor" }, svg);
      txt(svg, Math.min(X(b) + 4, w - mr - 4), top - 6, "spend " + fmt(b, 0), "strong", X(b) > w * 0.7 ? "end" : "start");
      if (X(b) > w * 0.7) svg.lastChild.setAttribute("x", X(b) - 4);
      order.forEach(function (s) {
        const best = A2.bestAtBudget(F[i][s].frontier, b);
        if (best) el("circle", { cx: X(best.cost), cy: Y(best.p99), r: 10, class: "ring" }, svg);
      });
    }
    const redraw = responsive($("w5-chart"), draw);

    /* the strip: utilisation's policies, and where the other two signals reached */
    function drawStrip(w) {
      const i = cur();
      const phone = w < 540;
      const ml = phone ? 12 : 16, mr = phone ? 12 : 16, rowH = 86, top = 8, bot = 40;
      const H = top + 3 * rowH + bot;
      const svg = svgRoot($("w5-strip"), w, H,
        "Strip of utilisation's policies' p99 for " + D.sweeps[i].label + ", with the p99 each other signal reached.");
      const up = F[i].utilization.points.map(function (p) { return p.p99; }).sort(function (a, b) { return a - b; });
      const reached = {};
      order.forEach(function (s) { reached[s] = A2.bestAtBudget(F[i][s].frontier, D.budget).p99; });
      const utilBest = reached.utilization;
      let lo = Math.min(up[0], reached.in_flight_concurrency), hi = Math.max(up[up.length - 1], reached.in_flight_concurrency);
      const q = reached.queue_depth;
      const qIn = q >= lo - (hi - lo) * 1.2 && q <= hi + (hi - lo) * 1.2;
      if (qIn) { lo = Math.min(lo, q); hi = Math.max(hi, q); }
      const span = hi - lo || 0.01;
      lo -= span * 0.08; hi += span * 0.12;
      const X = function (v) { return ml + ((v - lo) / (hi - lo)) * (w - ml - mr); };
      const rows = [
        { y: top, s: "utilization", label: "utilisation: " + up.length + " policies at the cap, one dot each" },
        { y: top + rowH, s: "in_flight_concurrency", label: "in-flight concurrency, best reached" },
        { y: top + 2 * rowH, s: "queue_depth", label: "queue depth, best reached" }
      ];
      el("line", { x1: X(utilBest), x2: X(utilBest), y1: top, y2: top + 3 * rowH, class: "line-u dash" }, svg);
      A2.niceTicks(lo, hi, phone ? 4 : 6).forEach(function (v) {
        el("line", { x1: X(v), x2: X(v), y1: top, y2: top + 3 * rowH, class: "grid" }, svg);
        txt(svg, X(v), top + 3 * rowH + 16, fmt(v, span < 1.5 ? 2 : 1), "", "middle");
      });
      txt(svg, (ml + w - mr) / 2, top + 3 * rowH + 33, "p99 (s)", "", "middle");
      rows.forEach(function (r) {
        txt(svg, ml, r.y + 13, r.label, "strong");
        if (r.s === "utilization") {
          // a simple beeswarm: step the dot down while it would touch a neighbour
          const placed = [];
          F[i].utilization.points.slice().sort(function (a, b) { return a.p99 - b.p99; }).forEach(function (p) {
            let lane = 0;
            while (placed.some(function (q2) { return q2.lane === lane && Math.abs(q2.x - X(p.p99)) < 9; })) lane++;
            placed.push({ x: X(p.p99), lane: lane });
            const m = mark(svg, "tri", X(p.p99), r.y + 26 + lane * 8, 4, "su", false);
            const t = el("title", {}, m);
            t.textContent = "utilisation, scale up at " + p.up + ", down at " + p.down + ": p99 " + fmt(p.p99, 3) + " s";
          });
        } else {
          const v = reached[r.s];
          const diff = (utilBest - v) * 1000;
          const inRange = v >= lo && v <= hi;
          if (inRange) {
            mark(svg, SIG[r.s].shape, X(v), r.y + 34, 7, SIG[r.s].cls, false);
            el("line", { x1: X(utilBest), x2: X(v), y1: r.y + 50, y2: r.y + 50, class: "bar" }, svg);
            el("line", { x1: X(utilBest), x2: X(utilBest), y1: r.y + 45, y2: r.y + 55, class: "bar" }, svg);
            el("line", { x1: X(v), x2: X(v), y1: r.y + 45, y2: r.y + 55, class: "bar" }, svg);
            const mid = Math.max(ml + 90, Math.min(w - mr - 90, (X(utilBest) + X(v)) / 2));
            txt(svg, mid, r.y + 72, "utilisation's best is " + fmt(Math.abs(diff), 0) + " ms " + (diff >= 0 ? "higher" : "lower"), "", "middle");
          } else {
            txt(svg, w - mr, r.y + 40, fmt(v, 2) + " s, off this scale, " + (v > hi ? "to the right" : "to the left"), "", "end");
          }
        }
      });
    }
    const redrawStrip = responsive($("w5-strip"), drawStrip);

    // note under the strip
    function note() {
      const i = cur();
      const up = F[i].utilization.points.map(function (p) { return p.p99; }).sort(function (a, b) { return a - b; });
      $("w5-strip-note").textContent = up.length + " utilisation policies, p99 from " + fmt(up[0], 2) + " to "
        + fmt(up[up.length - 1], 2) + " s, a spread of " + fmt(up[up.length - 1] - up[0], 2) + " s, all at the same cost of "
        + fmt(F[i].utilization.frontier[0].cost, 0) + " replica-seconds. The dashed line is utilisation's best.";
    }
    sel.addEventListener("change", note);
    note();
    update();

    /* self-check 7 as a widget */
    (function () {
      const A = D.exercise.a, B0 = D.exercise.b;
      const bc = $("w5c-bc"), bd = $("w5c-bd");
      let revealed = false;
      bc.value = String(B0[0]); bd.value = String(B0[1]);
      function pts() { return [{ cost: A[0], dmg: A[1] }, { cost: Number(bc.value), dmg: Number(bd.value) }]; }
      function mark2() {
        return [document.querySelector('input[name="w5c-a"]:checked'), document.querySelector('input[name="w5c-b"]:checked')]
          .map(function (r) { return r ? r.value : null; });
      }
      function moved() {
        $("w5c-out-bc").textContent = bc.value; $("w5c-out-bd").textContent = bd.value;
        $("w5c-b-lab").textContent = "cost " + bc.value + ", damage " + bd.value;
        if (revealed) { revealed = false; $("w5c-msg").textContent = "B moved. Mark again and press Check."; }
        redrawC();
      }
      bc.addEventListener("input", moved); bd.addEventListener("input", moved);
      document.querySelectorAll('input[name="w5c-a"],input[name="w5c-b"]').forEach(function (r) {
        r.addEventListener("change", function () { if (revealed) { revealed = false; $("w5c-msg").textContent = ""; redrawC(); } });
      });
      on("w5c-check", "click", function () {
        const m = mark2();
        if (m[0] === null || m[1] === null) { $("w5c-msg").textContent = "Mark both policies first."; return; }
        const P = pts();
        const flags = A2.dominatedFlags(P);
        const names = ["A", "B"];
        $("w5c-msg").textContent = names.map(function (n, k) {
          const right = (m[k] === "dom") === flags[k];
          return "Policy " + n + " is " + (flags[k] ? "dominated" : "on the frontier") + (right ? " (you marked it so)." : " (you marked the other way).");
        }).join(" ");
        revealed = true;
        redrawC();
      });
      on("w5c-reset", "click", function () {
        document.querySelectorAll('input[name="w5c-a"],input[name="w5c-b"]').forEach(function (r) { r.checked = false; });
        revealed = false; $("w5c-msg").textContent = ""; redrawC();
      });
      function drawC(w) {
        const ml = 46, mr = 14, top = 12, ph = 190, bot = 38;
        const svg = svgRoot($("w5c-chart"), w, top + ph + bot, "Two policies plotted by cost and damage, lower is better on both axes.");
        const X = function (v) { return ml + ((v - 60) / 100) * (w - ml - mr); };
        const Y = function (v) { return top + ph - ((v - 25) / 40) * ph; };
        [70, 90, 110, 130, 150].forEach(function (v) {
          if (v > 160) return;
          el("line", { x1: X(v), x2: X(v), y1: top, y2: top + ph, class: "grid" }, svg);
          txt(svg, X(v), top + ph + 16, String(v), "", "middle");
        });
        [30, 40, 50, 60].forEach(function (v) {
          el("line", { x1: ml, x2: w - mr, y1: Y(v), y2: Y(v), class: "grid" }, svg);
          txt(svg, ml - 6, Y(v) + 4, String(v), "", "end");
        });
        el("line", { x1: ml, x2: ml, y1: top, y2: top + ph, class: "axis" }, svg);
        el("line", { x1: ml, x2: w - mr, y1: top + ph, y2: top + ph, class: "axis" }, svg);
        txt(svg, (ml + w - mr) / 2, top + ph + 33, "cost", "", "middle");
        txt(svg, 12, top + ph / 2, "damage", "", "middle", -90);
        const P = pts();
        const flags = revealed ? A2.dominatedFlags(P) : [false, false];
        P.forEach(function (p, k) {
          const m = mark(svg, "circle", X(p.cost), Y(p.dmg), 7, "dot-ink", revealed && flags[k]);
          if (!(revealed && flags[k])) m.setAttribute("class", "dot-ink");
          txt(svg, X(p.cost) + 11, Y(p.dmg) + 4, "policy " + (k ? "B" : "A") + (revealed ? (flags[k] ? ", dominated" : ", frontier") : ""), "strong");
        });
      }
      const redrawC = responsive($("w5c-chart"), drawC);
      $("w5c-out-bc").textContent = bc.value; $("w5c-out-bd").textContent = bd.value;
    })();
  })();

  /* ---- module 6: the validation gate ----------------------------------- */

  (function () {
    const M = D.mc;
    const fac = $("w6-factor"), spr = $("w6-spread");
    let noise = A2.mcNoise(A2.mulberry32(1), M.bins);
    let manySeed = 7;
    function params() {
      return { bins: M.bins, truth: M.truth, factor: Number(fac.value), spread: Number(spr.value) / 100,
               tol: M.tol, minBins: M.min_bins, maxMissFraction: M.max_miss_fraction };
    }
    let run = null, many = null;
    function update() {
      const p = params();
      $("w6-out-factor").textContent = p.factor.toFixed(2);
      $("w6-out-spread").textContent = (p.spread * 100).toFixed(1) + "%";
      run = A2.mcRun(p, null, noise);
      const pass = A2.mcPasses(run.misses, M.bins, M.min_bins, M.max_miss_fraction);
      $("w6-r-miss").textContent = run.misses + " of " + M.bins;
      const limit = Math.floor(M.max_miss_fraction * M.bins);
      $("w6-r-lim").textContent = "at most " + limit + " allowed";
      $("w6-r-verdict").textContent = pass ? "passes" : "fails";
      $("w6-r-why").textContent = pass ? "no more than half missed" : "more than half missed";
      $("w6-r-exp").textContent = fmt(A2.perfectMissProb(p.spread, p.truth, p.tol) * 100, 0) + "%";
      many = A2.mcMany(p, A2.mulberry32(manySeed), M.runs);
      $("w6-r-many").textContent = fmt(many.meanMissFraction * 100, 0) + "% missed";
      $("w6-r-many-sub").textContent = "passed in " + fmt(many.passShare * 100, 0) + "% of reruns";
      redraw();
    }
    fac.addEventListener("input", update); spr.addEventListener("input", update);
    on("w6-f1", "click", function () { fac.value = "1"; update(); });
    on("w6-fe", "click", function () { fac.value = String(Math.min(1.2, Math.max(0.8, M.factor_engine)).toFixed(2)); update(); });
    on("w6-fc", "click", function () { fac.value = String(Math.min(1.2, Math.max(0.8, M.factor_calibrated)).toFixed(2)); update(); });
    on("w6-rerun", "click", function () {
      noise = A2.mcNoise(A2.mulberry32(Math.floor(Math.random() * 1e9)), M.bins); update();
    });
    on("w6-many", "click", function () {
      manySeed = Math.floor(Math.random() * 1e9);
      noise = A2.mcNoise(A2.mulberry32(manySeed + 1), M.bins); update();
    });

    function draw(w) {
      if (!run || !many) return;
      const phone = w < 540;
      const ml = phone ? 46 : 56, mr = phone ? 8 : 14, top = 24, ph = phone ? 190 : 230;
      const histH = 70, bot = 30, gap = 46;
      const H = top + ph + gap + histH + bot;
      const svg = svgRoot($("w6-chart"), w, H,
        "One column per bin. Three dots per column show the repeats against the prediction in milliseconds. Below, how many bins missed across " + M.runs + " reruns.");
      const p = params();
      const LIN = 0.001;
      const S = function (dev) { return A2.symlog(dev, LIN); };
      const smax = A2.symlog(0.2, LIN);
      const Y = function (dev) { return top + ph / 2 - (Math.max(-smax, Math.min(smax, S(dev))) / smax) * (ph / 2); };
      const colW = (w - ml - mr) / M.bins;
      const X = function (i) { return ml + (i + 0.5) * colW; };
      el("rect", { x: ml, y: Y(LIN), width: w - ml - mr, height: Y(-LIN) - Y(LIN), class: "shade" }, svg);
      [-0.1, -0.01, -0.001, 0, 0.001, 0.01, 0.1].forEach(function (v) {
        el("line", { x1: ml, x2: w - mr, y1: Y(v), y2: Y(v), class: v === 0 ? "axis" : "grid" }, svg);
        txt(svg, ml - 6, Y(v) + 4, (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v) * 1000, Math.abs(v) < 0.01 ? (Math.abs(v) === 0.001 ? 0 : 0) : 0), "", "end");
      });
      txt(svg, ml, top - 8, "repeat minus prediction (ms)", "title");
      run.bins.forEach(function (b, i) {
        if (b.miss) el("rect", { x: X(i) - colW / 2, y: top, width: colW, height: ph, class: "synth-col" }, svg);
        b.reps.forEach(function (r, k) {
          const cx = X(i) + (k - 1) * Math.min(2.6, colW / 3.2);
          el("circle", { cx: cx, cy: Y(r - b.pred), r: Math.max(1.6, Math.min(2.4, colW / 3.6)), class: b.miss ? "synth-fill" : "synth-open" }, svg);
        });
      });
      txt(svg, (ml + w - mr) / 2, top + ph + 16, M.bins + " bins, left to right", "", "middle");
      // histogram of misses over the 1,000 reruns
      const y0 = top + ph + gap, max = Math.max.apply(null, many.hist);
      const bw = (w - ml - mr) / (M.bins + 1);
      const HX = function (k) { return ml + k * bw; };
      many.hist.forEach(function (n, k) {
        if (!n) return;
        const h = (n / max) * (histH - 14);
        el("rect", { x: HX(k) + 0.5, y: y0 + histH - h, width: Math.max(1, bw - 1), height: h, class: "synth-fill" }, svg);
      });
      el("line", { x1: ml, x2: w - mr, y1: y0 + histH, y2: y0 + histH, class: "axis" }, svg);
      const lim = Math.floor(M.max_miss_fraction * M.bins) + 1;
      el("line", { x1: HX(lim), x2: HX(lim), y1: y0, y2: y0 + histH, class: "line-soft dash" }, svg);
      txt(svg, HX(lim) + 4, y0 + 10, "more than half: fails", "", "start");
      txt(svg, ml, y0 - 6, "bins missed, over " + fmt(M.runs, 0) + " reruns", "title");
      [0, 10, 20, 30].forEach(function (k) { txt(svg, HX(k) + bw / 2, y0 + histH + 14, String(k), "", "middle"); });
      txt(svg, w - mr, y0 + histH + 14, "of " + M.bins, "", "end");
    }
    const redraw = responsive($("w6-chart"), draw);
    update();

    /* the real residuals, two panels on one symlog axis */
    const V = D.validation;
    function drawRes(w) {
      const stack = w < 640;
      const ml = 62, mr = 12, top = 24, ph = 230, bot = 36, gapP = 30;
      const pw = stack ? w : w;
      const H = stack ? top + 2 * (ph + bot) + gapP : top + ph + bot;
      const svg = svgRoot($("w6-res"), w, H,
        "Residuals, real minus predicted p50 per bin, for the two attempts on one logarithmic-beyond-zero axis. Attempt 1 sits below zero, attempt 2 above.");
      const LIN = 0.01;
      const all = [];
      ["engine", "calibrated"].forEach(function (n) { V[n].residuals.forEach(function (r) { r.forEach(function (q) { if (q[1] !== null) all.push(Math.abs(q[1])); }); }); });
      const smax = A2.symlog(Math.max.apply(null, all) * 1.15, LIN);
      const panels = [["engine", "attempt 1"], ["calibrated", "attempt 2"]];
      panels.forEach(function (pn, k) {
        const x0 = stack ? ml : (k === 0 ? ml : w / 2 + ml / 2);
        const x1 = stack ? w - mr : (k === 0 ? w / 2 - 6 : w - mr);
        const y0 = stack ? top + k * (ph + bot + gapP) : top;
        const X = function (t) { return x0 + (t / 400) * (x1 - x0); };
        const Y = function (v) { return y0 + ph / 2 - (A2.symlog(v, LIN) / smax) * (ph / 2); };
        txt(svg, x0, y0 - 8, pn[1] + " · " + V[pn[0]].misses + " of " + V[pn[0]].compared + " miss", "title");
        [-6, -1, -0.1, -0.01, 0, 0.01, 0.1, 1, 6].forEach(function (v) {
          el("line", { x1: x0, x2: x1, y1: Y(v), y2: Y(v), class: v === 0 ? "axis" : "grid" }, svg);
          if (k === 0 || stack) txt(svg, x0 - 6, Y(v) + 4, (v < 0 ? "−" : "") + String(Math.abs(v)), "", "end");
        });
        [0, 100, 200, 300, 400].forEach(function (t) {
          txt(svg, X(t), y0 + ph + 16, String(t), "", "middle");
        });
        V[pn[0]].residuals.forEach(function (rep) {
          let seg = [];
          const flush = function () { if (seg.length > 1) path(svg, seg, "meas"); seg = []; };
          rep.forEach(function (q) {
            if (q[1] === null) { flush(); return; }
            seg.push([X(q[0] + 5), Y(q[1])]);
          });
          flush();
          rep.forEach(function (q) { if (q[1] !== null) el("circle", { cx: X(q[0] + 5), cy: Y(q[1]), r: 2.2, class: "meas-fill" }, svg); });
        });
        txt(svg, (x0 + x1) / 2, y0 + ph + 31, "engine arrival time (s)", "", "middle");
      });
      txt(svg, 12, top + ph / 2, "real − predicted p50 (s)", "", "middle", -90);
    }
    responsive($("w6-res"), drawRes);

    // verdict cards
    const vbox = $("w6-verdicts");
    [["engine", "Attempt 1"], ["calibrated", "Attempt 2"]].forEach(function (pn) {
      const v = V[pn[0]];
      const off = (1 - v.median_ratio) * 100;
      const d = document.createElement("div");
      d.className = "readout";
      d.innerHTML = "<span>" + pn[1] + "</span><b>" + v.misses + " of " + v.compared + " bins miss</b><small>the engine's median latency was "
        + fmt(Math.abs(off), 0) + "% " + (off > 0 ? "below" : "above") + " the prediction; the largest miss was " + fmt(v.max_miss_s, v.max_miss_s < 0.1 ? 3 : 2) + " s</small>";
      vbox.appendChild(d);
    });

    // host speed table
    (function () {
      const H = D.host_speed, ex = H.exploratory;
      const t = $("w6-hosts");
      const lvl = ["32", "64", "128"];
      function cells(o) { return lvl.map(function (l) { return "<td>" + (o && o[l] ? fmt(o[l].ratio, 2) : "—") + "</td>"; }).join(""); }
      const cal = H.calibrated_ratios_by_host;
      const calHost = Object.keys(cal)[0];
      function range(a) { const lo = Math.min.apply(null, a), hi = Math.max.apply(null, a); return fmt(lo, 2) === fmt(hi, 2) ? fmt(lo, 2) : fmt(lo, 2) + " to " + fmt(hi, 2); }
      const a1 = H.attempt1_at_100_in_flight;
      const curveHost = H.curve_hosts["128"][0];
      const exHost = Object.keys(ex.maxseqs128)[0];
      t.innerHTML = "<caption>Latency on each host divided by the curve&rsquo;s host, at 32, 64 and 128 in flight</caption><thead><tr><th>Host</th><th>How it was measured</th><th>32</th><th>64</th><th>128</th></tr></thead><tbody>"
        + "<tr><td><code>" + curveHost + "</code></td><td>the service curve (1.00 by definition)</td><td>1.00</td><td>1.00</td><td>1.00</td></tr>"
        + "<tr><td><code>" + exHost + "</code></td><td>re-measured, max-num-seqs 128</td>" + cells(ex.maxseqs128[exHost]) + "</tr>"
        + "<tr><td><code>" + exHost + "</code></td><td>re-measured, max-num-seqs 256</td>" + cells(ex.maxseqs256[exHost]) + "</tr>"
        + "<tr><td><code>" + calHost + "</code></td><td>before each replay of attempt 2, three repeats</td><td>—</td><td>" + range(cal[calHost]["64"]) + "</td><td>" + range(cal[calHost]["128"]) + "</td></tr>"
        + "<tr><td><code>" + a1.host + "</code></td><td>attempt 1&rsquo;s own records at " + a1.band[0] + " to " + a1.band[1] + " in flight: "
        + fmt(a1.median_server_latency_s, 3) + " s against the curve&rsquo;s " + fmt(a1.curve_interpolated_s, 3) + " s at 100</td><td colspan=\"3\" style=\"text-align:center\">ratio "
        + fmt(a1.median_server_latency_s / a1.curve_interpolated_s, 2) + " at about 100</td></tr></tbody>";
    })();
  })();

  /* ---- glossary: one open at a time (artifact 1's mechanism) ------------- */

  (function () {
    const terms = document.querySelectorAll(".term");
    function closeAll(except) {
      terms.forEach(function (b) {
        if (b === except) return;
        b.setAttribute("aria-expanded", "false");
        b.nextElementSibling.hidden = true;
      });
    }
    terms.forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        const open = b.getAttribute("aria-expanded") === "true";
        closeAll(b);
        b.setAttribute("aria-expanded", String(!open));
        b.nextElementSibling.hidden = open;
      });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeAll(null); });
    document.addEventListener("click", function () { closeAll(null); });
  })();
})();
