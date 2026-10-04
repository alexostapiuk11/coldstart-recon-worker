"""Pull code out of the running source, by sentinel comment.

The explainer shows code. Copy-pasted snippets go stale silently -- and the
harness-extraction plan is about to rewrite import paths under every one of
them. Sentinels make that failure loud: the excerpt either comes from the file
that is executing, or the build stops.
"""

from pathlib import Path

OPEN = "# explainer:"
CLOSE = "# explainer:end"

SENTINELS: dict[str, str] = {
    "preflight-refuses": "harness/runpod/preflight.py",
    "cache-config-env": "coldstart/cache_config.py",
    "probe-markers": "worker/probe.py",
    "handler-snapshot-before": "worker/handler.py",
    "checks-rtt-floor": "coldstart/checks.py",
    "stub-endpoint": "coldstart/stubs/stub_endpoint.py",
}


def extract(slug: str, repo: Path) -> str:
    """The lines between `# explainer:<slug>` and `# explainer:end`, dedented.

    Raises rather than returning empty: an excerpt that silently vanishes from
    the page is the failure this module exists to prevent.
    """
    if slug not in SENTINELS:
        raise KeyError(f"unknown excerpt slug {slug!r}; known: {sorted(SENTINELS)}")
    path = Path(repo) / SENTINELS[slug]
    if not path.exists():
        raise LookupError(f"explainer:{slug}: {path} does not exist")
    lines = path.read_text().splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"{OPEN}{slug}"), None)
    if start is None:
        raise LookupError(f"explainer:{slug} sentinel not found in {SENTINELS[slug]}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == CLOSE), None)
    if end is None:
        raise LookupError(f"explainer:{slug} has no closing {CLOSE} in {SENTINELS[slug]}")
    body = lines[start + 1 : end]
    indent = min((len(l) - len(l.lstrip()) for l in body if l.strip()), default=0)
    return "\n".join(l[indent:] if l.strip() else "" for l in body)
