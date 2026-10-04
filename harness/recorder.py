import time


class StageRecorder:
    """Clock B. Monotonic marks relative to t0.

    Wall time is captured once at start for correlation with other clocks only.
    It is never used for arithmetic — see spec 6.5 rule 1.
    """

    def __init__(self, clock=time.monotonic, wall_clock=time.time):
        self._clock = clock
        self._wall_clock = wall_clock
        self._t0 = None
        self._t0_wall = None
        self._marks: list[dict] = []

    def start(self) -> None:
        self._t0 = self._clock()
        self._t0_wall = self._wall_clock()

    def mark(self, stage: str) -> float:
        if self._t0 is None:
            raise RuntimeError("start() must be called before mark()")
        if any(m["stage"] == stage for m in self._marks):
            raise ValueError(f"stage {stage!r} already marked")
        t = self._clock() - self._t0
        self._marks.append({"stage": stage, "t_mono": t})
        return t

    def now(self) -> float:
        """Current clock-B instant, relative to t0, without naming a stage.

        `worker/probe.py` needs this for each warmup request's
        `t_dispatch_mono`. It must share `mark()`'s origin, not be a raw
        `time.monotonic()`: `metrics.t_fast_seconds` subtracts the dispatch
        instant from the `S7_warmup_done` mark, and `bundle()` stores marks
        relative to t0, so an absolute value would make the tail negative by
        the process uptime and raise on every real run.
        """
        if self._t0 is None:
            raise RuntimeError("start() must be called before now()")
        return self._clock() - self._t0

    def at(self, stage: str) -> float:
        for m in self._marks:
            if m["stage"] == stage:
                return m["t_mono"]
        raise KeyError(stage)

    def duration(self, start_stage: str, end_stage: str) -> float:
        return self.at(end_stage) - self.at(start_stage)

    def bundle(self) -> dict:
        return {"t0_wall": self._t0_wall, "marks": list(self._marks)}
