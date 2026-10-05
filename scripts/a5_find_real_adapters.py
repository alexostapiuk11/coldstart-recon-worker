"""Search the Hugging Face Hub for public LoRA adapters the equivalence gate
can use (R10), and record the choice with its reasons.

    .venv/bin/python scripts/a5_find_real_adapters.py --base Qwen/Qwen3-4B \
        --rank 16 --modules q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj --count 4

Writes fixtures/a5/real_adapter_candidates.json: every candidate seen, the
selected (repo, commit) pairs, and each rejection's reason. Pinned to commits,
so the gate serves exactly these adapters however the repos change later.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.adapters import select_real_adapters

HUB = "https://huggingface.co"
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "a5" / "real_adapter_candidates.json"


def candidates(base: str, limit: int) -> list[dict]:
    found = []
    for variant in (base, f"{base}-Base", f"{base}-Instruct-2507"):
        r = requests.get(f"{HUB}/api/models", params={
            "filter": f"base_model:adapter:{variant}", "limit": limit}, timeout=30)
        r.raise_for_status()
        for model in r.json():
            info = requests.get(f"{HUB}/api/models/{model['id']}", timeout=30).json()
            sha = info.get("sha")
            cfg = requests.get(f"{HUB}/{model['id']}/resolve/{sha}/adapter_config.json", timeout=30)
            if cfg.status_code != 200:
                continue
            found.append({"id": model["id"], "sha": sha, "base": variant, "config": cfg.json()})
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--rank", type=int, required=True)
    ap.add_argument("--modules", required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    seen = candidates(args.base, args.limit)
    result = select_real_adapters(
        seen, rank=args.rank, target_modules=args.modules.split(","), count=args.count
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"query": vars(args), "seen": seen, **result}, indent=1, sort_keys=True))
    print(f"{len(seen)} seen, {len(result['selected'])} selected, enough={result['enough']}: {OUT}")
    return 0 if result["enough"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
