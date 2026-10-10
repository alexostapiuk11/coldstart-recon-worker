# toolcall

A deterministic harness for one question about tool-calling agents: what kind
of failure is your agent making, and does the way you present your tools change
it? Artifact 3 of this repository uses it for a pre-registered experiment. This
page is for running it on your own tools, which needs none of the experiment's
machinery.

## What it does

You describe your tools and some requests as plain JSON. The harness renders
the tools for the model, sends each request several times, and grades every
response that was not excluded (below) into exactly one of six categories.
The checks run in this order and the first that applies wins; there is no LLM
judge:

| Category | Meaning | What it points at |
|---|---|---|
| `MALFORMED` | not a valid call: a tool that was not shown to the model (even one in your library), a required argument missing, a wrong JSON type, arguments that are not an object | schema strictness, output format constraints |
| `SPURIOUS` | called a tool when none was needed | description scoping, guidance on when not to call |
| `MISSING` | answered without the call it needed | tool discoverability, description richness |
| `WRONG_TOOL` | a valid call to another tool that was shown | disambiguation between similar tools, fewer tools in context |
| `WRONG_PARAMS` | the right tool with a wrong value, or an argument the schema does not define | typing strictness, parameter naming and descriptions |
| `CORRECT` | matches one of the calls you listed as acceptable | |

Refusals, truncated outputs and provider errors are counted separately and
never graded. If a response holds more than one call, only the first is graded,
and the record flags it.

## Check your files first, for free

```bash
.venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios \
    --dry-run --store runs/dry-mine.jsonl
```

`--dry-run` answers with a stub model and makes no API call. It proves your
files load, render and grade. The stub draws categories from invented
probabilities (`toolcall/stub.py` is marked NOT DATA), so the table it prints
says nothing about any model; only the fact that it prints matters.

A dry run still validates `--provider` and `--model`. It ignores
`--approved-usd` and the API key. The store must be a path that does not exist
yet (or is empty): the script refuses a used one here too. Without `--store`, a
dry run writes its records to a fresh temporary directory.

To try it on the worked examples shipped here:

```bash
.venv/bin/python scripts/a3_diagnose.py --tools toolcall/data/tools \
    --scenarios toolcall/data/scenarios --dry-run --reps 3 --store runs/dry-examples.jsonl
```

That is 3 scenarios times 3 repetitions: 9 graded calls.

## Run it on your agent

```bash
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY with --provider anthropic
.venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios \
    --store runs/mine-1.jsonl --reps 5 --approved-usd 1.00
```

This spends money. The script does these things, in this order:

1. It parses the arguments. `--reps` must be at least 1, and a paid run
   requires `--store`. Pick a path that does not exist yet.
2. It validates `--model`, which defaults to a pinned model for the provider
   (`gpt-5.4-mini-2026-03-17` for `openai`, `claude-sonnet-5-5` for
   `anthropic`). Any other value must be one of the models priced in
   `toolcall/prices.py` for that provider, or the script refuses. An unpriced
   model cannot be metered.
3. It loads and validates your tool and scenario files.
4. It refuses a store or ledger that already holds anything. To run again,
   choose a new `--store`.
5. It checks that the provider's API key is set (`OPENAI_API_KEY` or
   `ANTHROPIC_API_KEY`). Only presence is checked, and an empty value counts as
   unset. This comes before any estimate, lock or call.
6. It prints the call count, the estimate and the guard headroom, then refuses
   to start unless `--approved-usd` covers the estimate plus that headroom. The
   headroom is the worst case of the largest single request, counting the SDK's
   two internal retries.
7. It opens a spend ledger beside the store, `<store>.spend.jsonl`, and holds a
   lock on it for the whole run. The lock is a separate file,
   `<store>.spend.lock`. It checks again that the store and ledger are unused.
8. For each call, the guard first checks whether that call's worst case could
   take spend past the approval. If it could, the run stops there. It does not
   wait for spend to reach the approval. Otherwise the worst case is written to
   the ledger before the call is made, and the metered cost is written after.

The output is the taxonomy: each category's share of the graded calls and the
intervention it points at, then a per-scenario table.

### When the guard stops the run

The guard can stop a run partway, for instance when the real token counts come
out well above the estimate. The script then prints `INCOMPLETE: stopped by the
spend guard after k calls` (k being the calls stored) to stdout and the guard's
message to stderr, summarises the calls already stored, prints that report with
the `records:` and ledger lines, and exits 3. The store and the ledger hold the
calls that were made. They count as used, so a rerun needs a new `--store`. A
dry run has no guard and has no such stop.

Exit codes: 0 for a run that graded at least one call; 1 if no call could be
graded (every call was excluded), and also when a refusal above raises an error
before any call is made (a used store, an unpriced model, a missing key, an
approval that is too small); 2 for a bad command line; 3 for a guard stop.

### What is being tested

By default, your tools at the low count (only the tools each scenario lists),
with rich descriptions and strict schemas. That is not the artifact's baseline
formulation, which is terse and loose. Change it with `--richness terse|rich`
and `--strictness loose|strict`. Strict renders enums, patterns, every required
parameter and `additionalProperties: false`; loose renders bare types and keeps
only each tool's first required parameter in `required`.

Calls are always graded against the strict form of each schema, whatever the
model was shown. Under `loose`, a model can therefore be marked wrong for a
constraint it was never shown, such as an enum or a required parameter. That
is the measurement of what loose schemas cost, not a bug, but keep it in mind
when you compare the two.

A scenario's `confusables` are validated at load time against your tool
library, but this path does not show them to the model.

## The file formats

A tool-library file holds one domain's tools. The directory you pass as
`--tools` holds one such file per domain, and a tool name may appear only once
across them. This is the shipped `get_forecast`, from
`toolcall/data/tools/weather.json`:

```json
{"domain": "weather", "tools": [
  {"name": "get_forecast", "terse": "Weather forecast.",
   "rich": "Daily forecast for the next 1 to 10 days at one location: high, low, precipitation chance. For hour-by-hour detail use the hourly forecast tool.",
   "params": [
     {"name": "location", "type": "string", "required": true,
      "terse": "Location.",
      "rich": "City name; add the country when the city name alone could be ambiguous."},
     {"name": "days", "type": "integer", "required": true,
      "terse": "Days.", "rich": "Number of days ahead, 1 to 10."},
     {"name": "units", "type": "string", "required": false,
      "terse": "Units.",
      "rich": "metric (Celsius, km/h) or imperial (Fahrenheit, mph). Defaults to metric.",
      "enum": ["metric", "imperial"]}]}]}
```

Types are `string`, `integer`, `number`, `boolean`, or an `array` of one of
those (with `"items": "string"`, say). A string may carry an `enum` or a
`pattern`, not both. Names are snake_case, and a tool with parameters needs at
least one required parameter. Every tool and every parameter has a `terse` and
a `rich` description; `--richness` picks which the model sees.

A scenario file is one request and what counts as right. It needs `id`,
`source`, `domain`, `tools`, `confusables` (which may be `[]`),
`user_message`, `expectation` and `target_failure_mode`, which is one of the
five failure categories (`MALFORMED`, `SPURIOUS`, `MISSING`, `WRONG_TOOL`,
`WRONG_PARAMS`). This is the shipped
`toolcall/data/scenarios/weather-forecast-lisbon.json`, without its `notes` and
its optional `recovery` block (the recovery block belongs to the experiment's
recovery phase, and this path does not use it):

```json
{"id": "weather-forecast-lisbon",
 "source": {"kind": "authored"},
 "domain": "weather",
 "target_failure_mode": "WRONG_TOOL",
 "tools": ["get_forecast", "get_air_quality"],
 "confusables": ["get_current_weather", "get_hourly_forecast",
                 "get_historical_weather", "get_climate_normals"],
 "user_message": "What will the weather be like in Lisbon over the next three days?",
 "expectation": {"acceptable_calls": [{
   "tool": "get_forecast",
   "args": {"location": {"pattern": "lisbon(,\\s*portugal)?", "example": "Lisbon"},
            "days": 3},
   "may_include": {"units": {"one_of": ["metric", "imperial"]}}}]}}
```

`tools` are the tools the model is shown. Acceptable calls use only those tools
and give every required parameter of the tool in `args`. Each acceptable call
lists in `args` what must be present and match, and in `may_include` what may
also appear. A value is a literal, `{"one_of": [...]}`, or a case-insensitive
`{"pattern": ..., "example": ...}` that must match the whole string; the
example is one value that matches. For a request that needs no tool, write
`"expectation": {"no_call_expected": true}` and set `target_failure_mode` to
`SPURIOUS`, as `weather-thanks-no-call.json` does. A scenario has either
acceptable calls or `no_call_expected`, not both. The file name (without
`.json`) must equal the `id`.

Scenarios are checked when they load, before anything is sent: an acceptable
call that is itself malformed, a tool or confusable that is not in the library,
or a pattern whose example does not match all fail at once. A `recovery`
block, if a file has one, is validated too, even though this path does not use
it.

## How values are compared

The rules are in `toolcall/normalize.py` (`RULES`, version 1), in force for
every number this harness produces:

- R1: enum values compare case-insensitively.
- R2: strings are trimmed and internal whitespace collapses. Free text
  compares case-sensitively; enum values and your patterns compare
  case-insensitively.
- R3: numbers compare numerically (tolerance 1e-9), so 3 equals 3.0; an
  integer parameter accepts a float with no fractional part.
- R4: a number sent as a string is a type error, so `"3"` for an integer is
  `MALFORMED`.
- R5: an explicit null for an optional parameter is the same as omitting it; a
  null for a required one is a missing parameter.
- R6: key order does not matter.
- R7: a key the schema does not define is `WRONG_PARAMS`.
- R8: arrays compare element by element, in order.
- R9: a value is correct only if it also satisfies the tool's strict schema
  (its `enum` and `pattern`). Your acceptable values are checked against it when
  the scenario loads.
- R10: duplicate keys in a call's arguments resolve last-wins, as JSON parsers
  do.

Changing a rule changes every number, so the version is stored with every
graded record.

## Read the result honestly

Repetitions of one request are not independent: a request the model finds
confusing fails every time for the same reason. The summary computes a Wilson
interval per category over all graded calls pooled, which treats repetitions as
independent, so those intervals are narrower than they should be (the printed
report shows shares and a note to that effect, not the intervals). Read the
per-scenario table the report prints below the taxonomy first: a category
that comes from one scenario is a fact about that scenario, not a rate. The
artifact's own analysis bootstraps over scenarios, not calls
(`toolcall/effects.py`), and a handful of scenarios supports only a rough
diagnosis. Add scenarios before you trust a share.
