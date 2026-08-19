from dataclasses import asdict, dataclass, field

from coldstart import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "RunRecord"]


@dataclass
class RunRecord:
    """One measurement run. The interface between worker, driver, store, analysis."""

    run_id: str
    run_index: int
    arm: str
    clock_A: dict
    clock_C: dict
    clock_B: dict
    warmup: list
    engine: dict
    host: dict
    config: dict
    status: dict
    schema_version: int = field(default=SCHEMA_VERSION)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {d.get('schema_version')!r}; "
                f"this build reads {SCHEMA_VERSION}"
            )
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
