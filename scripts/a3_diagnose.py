"""Your tools, your scenarios, your failure taxonomy (August §7).

    .venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios \
        --model gpt-5.4-mini-2026-03-17 --reps 5 --approved-usd 1.00
    .venv/bin/python scripts/a3_diagnose.py --tools ... --scenarios ... --dry-run

Runs the baseline formulation only (rich descriptions and strict schemas by
default; change with --richness / --strictness). --dry-run uses the stub model
and makes no API call: use it to check your files before spending anything.
A real run spends money: it needs --approved-usd and the provider's API key in
the environment (OPENAI_API_KEY or ANTHROPIC_API_KEY).

The real run follows the runner's spend rules (toolcall/runner.py): the approval
must cover the estimate plus the spend guard's headroom; every call's worst case
is written to a durable ledger, `<store dir>/diagnose.spend.jsonl`, whose lock
is held for the whole run; and a --store or ledger that already holds anything
is refused, so a second run can never spend the approval again unseen.
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.diagnose import diagnose, report
from toolcall.formulation import Formulation
from toolcall.guard import GuardedClient, SpendGuard, SpendLedger, check_estimate
from toolcall.providers import PARSE, Client, ModelSettings, ScriptedClient
from toolcall.runner import plan_cost
from toolcall.scenarios import load_scenarios
from toolcall.stub import StubModel
from toolcall.tools import load_library


def _refuse_reuse(*paths: Path) -> None:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            raise ValueError(f"{path}: store exists; choose a new --store")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", type=Path, required=True)
    ap.add_argument("--scenarios", type=Path, required=True)
    ap.add_argument("--model", default="gpt-5.4-mini-2026-03-17")
    ap.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--richness", choices=["terse", "rich"], default="rich")
    ap.add_argument("--strictness", choices=["loose", "strict"], default="strict")
    ap.add_argument("--approved-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--store", type=Path)
    args = ap.parse_args(argv)
    if args.provider == "openai":
        settings = ModelSettings("openai", args.model, 0.0, reasoning_effort="none")
    else:
        settings = ModelSettings("anthropic", args.model, None, thinking="between_tools")
    library = load_library(args.tools)
    scenarios = load_scenarios(args.scenarios, library, factorial=False)
    cell = Formulation("low", args.richness, args.strictness)
    store = args.store or Path(tempfile.mkdtemp()) / "diagnose.jsonl"
    ledger_path = store.parent / "diagnose.spend.jsonl"
    if args.dry_run:
        _refuse_reuse(store)
        dry = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
        client = ScriptedClient(dry, StubModel(library, scenarios))
        summary = diagnose(client, args.tools, args.scenarios, store, reps=args.reps,
                           richness=args.richness, strictness=args.strictness)
    else:
        _refuse_reuse(store, ledger_path)
        calls, estimate, headroom = plan_cost(settings, library, scenarios, [cell], args.reps)
        print(f"{calls} calls, estimated ${estimate:.2f} + ${headroom:.2f} guard headroom; "
              f"approved ${args.approved_usd:.2f}")
        check_estimate(estimate + headroom, args.approved_usd)
        with SpendLedger(ledger_path, label="diagnose") as ledger:
            _refuse_reuse(store, ledger_path)  # again, now that the lock is held
            guard = SpendGuard(args.approved_usd, ledger=ledger)
            client = GuardedClient(Client(settings), guard, PARSE[settings.provider])
            summary = diagnose(client, args.tools, args.scenarios, store, reps=args.reps,
                               richness=args.richness, strictness=args.strictness)
        print(f"spent ${guard.spent:.4f} of ${args.approved_usd:.2f}; ledger: {ledger_path}")
    print(report(summary))
    print(f"\nrecords: {store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
