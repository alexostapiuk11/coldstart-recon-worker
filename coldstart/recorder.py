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

    def at(self, stage: str) -> float:
        for m in self._marks:
            if m["stage"] == stage:
                return m["t_mono"]
        raise KeyError(stage)

    def duration(self, start_stage: str, end_stage: str) -> float:
        return self.at(end_stage) - self.at(start_stage)

    def bundle(self) -> dict:
        return {"t0_wall": self._t0_wall, "marks": list(self._marks)}
