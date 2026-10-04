import json
from pathlib import Path


class JsonlStore:
    """Append-only. Never rewrites or deletes a record — see artifact 1 spec 6.6.

    `record_cls` is the artifact's own record type: anything with a `to_dict()`
    method and a `from_dict()` classmethod. It is a constructor argument rather
    than a hard import of `RunRecord` so a second artifact can store its own
    record shape through the same file discipline -- the append-only rule and
    the truncated-line diagnostic below are what is worth sharing, and neither
    depends on what a record contains.
    """

    def __init__(self, path, record_cls):
        self.path = Path(path)
        self.record_cls = record_cls
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list:
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
                out.append(self.record_cls.from_dict(data))
        return out
