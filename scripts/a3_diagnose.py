"""Your tools, your scenarios, your failure taxonomy (August §7).

    .venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios \
        --store runs/mine.jsonl --reps 5 --approved-usd 1.00
    .venv/bin/python scripts/a3_diagnose.py --tools ... --scenarios ... --dry-run

Runs your tools in one formulation: low tool count, rich descriptions and strict
schemas by default (change with --richness / --strictness). That is not the
factorial's baseline cell. --dry-run uses the stub model and makes no API call:
use it to check your files before spending anything. A real run spends money:
it needs --approved-usd, a new --store, and the provider's API key in the
environment (OPENAI_API_KEY or ANTHROPIC_API_KEY; only its presence is checked).

The real run follows the runner's spend rules (toolcall/runner.py): the approval
must cover the estimate plus the spend guard's headroom; every call's worst case
is written to a durable ledger, `<store>.spend.jsonl`, whose lock is held for the
whole run; and a --store or ledger that already holds anything is refused, so a
second run can never spend the approval again unseen. It exits 1 if no call
could be graded.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.diagnose import diagnose, report
from toolcall.formulation import Formulation
from toolcall.guard import GuardedClient, SpendGuard, SpendLedger, check_estimate
from toolcall.prices import PRICES
from toolcall.providers import PARSE, Client, ModelSettings, ScriptedClient
from toolcall.runner import plan_cost
from toolcall.scenarios import load_scenarios
from toolcall.stub import StubModel
from toolcall.tools import load_library

DEFAULT_MODEL = {"openai": "gpt-5.4-mini-2026-03-17", "anthropic": "claude-sonnet-5-5"}
API_KEY = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
# toolcall.prices records no provider, so the pinned ids are split by their prefix.
PREFIX = {"openai": "gpt-", "anthropic": "claude-"}


def _refuse_reuse(*paths: Path) -> None:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            raise ValueError(f"{path}: store exists; choose a new --store")


def _pinned(provider: str) -> list[str]:
    return sorted(m for m in PRICES if m.startswith(PREFIX[provider]))


def _settings(provider: str, model: str) -> ModelSettings:
    if model not in _pinned(provider):
        raise ValueError(f"{model!r} is not a pinned model for provider {provider}; "
                         f"pinned: {', '.join(_pinned(provider))}")
    if provider == "openai":
        return ModelSettings("openai", model, 0.0, reasoning_effort="none")
    return ModelSettings("anthropic", model, None, thinking="between_tools")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", type=Path, required=True)
    ap.add_argument("--scenarios", type=Path, required=True)
    ap.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    ap.add_argument("--model", help="default: the provider's pinned model "
                                    f"({DEFAULT_MODEL})")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--richness", choices=["terse", "rich"], default="rich")
    ap.add_argument("--strictness", choices=["loose", "strict"], default="strict")
    ap.add_argument("--approved-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--store", type=Path, help="required unless --dry-run")
    args = ap.parse_args(argv)
    if args.reps < 1:
        ap.error("--reps must be at least 1")
    if args.store is None and not args.dry_run:
        ap.error("--store is required for a paid run (a new file; the spend ledger goes "
                 "beside it)")
    settings = _settings(args.provider, args.model or DEFAULT_MODEL[args.provider])
    library = load_library(args.tools)
    scenarios = load_scenarios(args.scenarios, library, factorial=False)
    cell = Formulation("low", args.richness, args.strictness)
    store = args.store or Path(tempfile.mkdtemp()) / "diagnose.jsonl"
    ledger_path = store.with_name(store.name + ".spend.jsonl")
    kw = {"reps": args.reps, "richness": args.richness, "strictness": args.strictness}
    if args.dry_run:
        _refuse_reuse(store)
        dry = ModelSettings("openai", DEFAULT_MODEL["openai"], 0.0, reasoning_effort="none")
        client = ScriptedClient(dry, StubModel(library, scenarios))
        summary = diagnose(client, library, scenarios, store, **kw)
    else:
        _refuse_reuse(store, ledger_path)
        if not os.environ.get(API_KEY[args.provider]):
            raise ValueError(f"{API_KEY[args.provider]} is not set in the environment")
        calls, estimate, headroom = plan_cost(settings, library, scenarios, [cell], args.reps)
        print(f"{calls} calls, estimated ${estimate:.2f} + ${headroom:.2f} guard headroom; "
              f"approved ${args.approved_usd:.2f}")
        check_estimate(estimate + headroom, args.approved_usd)
        with SpendLedger(ledger_path, label="diagnose") as ledger:
            _refuse_reuse(store, ledger_path)  # again, now that the lock is held
            guard = SpendGuard(args.approved_usd, ledger=ledger)
            client = GuardedClient(Client(settings), guard, PARSE[settings.provider])
            summary = diagnose(client, library, scenarios, store, **kw)
        print(f"spent ${guard.spent:.4f} of ${args.approved_usd:.2f}; ledger: {ledger_path}")
    print(report(summary))
    print(f"\nrecords: {store}")
    if summary["graded"] == 0:
        print("no graded calls: every call was excluded (API error, refusal or truncation); "
              "see the records", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
