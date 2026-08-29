import json
from pathlib import Path

from coldstart.schema import RunRecord


class JsonlStore:
    """Append-only. Never rewrites or deletes a record — see spec 6.6."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: RunRecord) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list[RunRecord]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open() as f:
            for lineno, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"{self.path}: line {lineno} is not valid JSON ({e}). "
                        "A line truncated mid-write is the signature of a "
                        "process killed mid-append (e.g. an interrupted "
                        "campaign); if this is the last line in the file, "
                        "truncating it is the fix -- read_all() will not "
                        "silently drop it for you."
                    ) from e
                out.append(RunRecord.from_dict(data))
        return out
