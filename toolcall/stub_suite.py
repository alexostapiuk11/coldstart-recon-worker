"""A small synthetic suite for dry runs, the stub demo and tests. NOT DATA.

It exercises every branch of the loader, renderer, grader and recovery loop: a
confusable-heavy flight search, a no-call scenario and a recovery scenario, and
`synthetic_suite` clones them into as many distinct scenarios as a bootstrap
needs. The real suite lives in toolcall/data/ and is authored, not generated.
"""

import copy
import json
from pathlib import Path

from toolcall.scenarios import scenario_from_dict
from toolcall.tools import Library, tool_from_dict


def _p(name, type_, required, terse, rich, **kw):
    return {"name": name, "type": type_, "required": required, "terse": terse, "rich": rich, **kw}


IATA = "^[A-Z]{3}$"
DATE = "^\\d{4}-\\d{2}-\\d{2}$"

TRAVEL = {
    "domain": "travel",
    "tools": [
        {"name": "search_flights", "terse": "Search flights.",
         "rich": "Search scheduled passenger flights between two airports on one date. "
                 "Airports are three-letter IATA codes, for example JFK. Dates are YYYY-MM-DD. "
                 "Use flight_status, not this, for a flight that is already booked.",
         "params": [
             _p("origin", "string", True, "Origin.", "Departure airport, IATA code, e.g. JFK.",
                pattern=IATA),
             _p("destination", "string", True, "Destination.", "Arrival airport, IATA code.",
                pattern=IATA),
             _p("date", "string", True, "Date.", "Departure date, YYYY-MM-DD.", pattern=DATE),
             _p("cabin", "string", False, "Cabin.", "Cabin class. Defaults to economy.",
                enum=["economy", "premium", "business"]),
             _p("passengers", "integer", False, "Passengers.", "Number of travellers, 1-9."),
         ]},
        {"name": "flight_status", "terse": "Flight status.",
         "rich": "Live status of one flight by its flight number, such as UA123.",
         "params": [_p("flight_number", "string", True, "Flight.", "Carrier code and number.")]},
        {"name": "search_trains", "terse": "Search trains.",
         "rich": "Search rail journeys between two stations on one date.",
         "params": [_p("origin", "string", True, "From.", "Origin station name."),
                    _p("destination", "string", True, "To.", "Destination station name."),
                    _p("date", "string", True, "Date.", "YYYY-MM-DD.", pattern=DATE)]},
        {"name": "search_hotels", "terse": "Search hotels.",
         "rich": "Search hotels in a city for a check-in date and a number of nights.",
         "params": [_p("city", "string", True, "City.", "City name."),
                    _p("check_in", "string", True, "Check-in.", "YYYY-MM-DD.", pattern=DATE),
                    _p("nights", "integer", True, "Nights.", "Number of nights, at least 1.")]},
        {"name": "book_flight", "terse": "Book a flight.",
         "rich": "Book a flight already found with search_flights, by its offer id.",
         "params": [_p("offer_id", "string", True, "Offer.", "The id search_flights returned.")]},
        {"name": "flight_prices", "terse": "Flight prices.",
         "rich": "Cheapest fare per day for a route over a month, for flexible dates.",
         "params": [_p("origin", "string", True, "Origin.", "IATA code.", pattern=IATA),
                    _p("destination", "string", True, "Destination.", "IATA code.",
                       pattern=IATA),
                    _p("month", "string", True, "Month.", "YYYY-MM.")]},
        {"name": "airport_info", "terse": "Airport info.",
         "rich": "Terminals, lounges and transport for one airport by IATA code.",
         "params": [_p("code", "string", True, "Code.", "IATA code.", pattern=IATA)]},
        {"name": "get_currency_rate", "terse": "Currency rate.",
         "rich": "Exchange rate between two ISO 4217 currencies, for example USD to EUR.",
         "params": [_p("base", "string", True, "Base.", "ISO 4217 code."),
                    _p("quote", "string", True, "Quote.", "ISO 4217 code.")]},
    ],
}

MISC = {
    "domain": "misc",
    "tools": [
        {"name": f"misc_tool_{i:02d}", "terse": f"Misc {i}.",
         "rich": f"An unrelated utility, number {i}.",
         "params": [_p("value", "string", True, "Value.", "Any value.")]}
        for i in range(1, 17)
    ],
}

FLIGHT = {
    "id": "travel-flight-search",
    "source": {"kind": "authored"},
    "domain": "travel",
    "target_failure_mode": "WRONG_TOOL",
    "tools": ["search_flights", "search_hotels"],
    "confusables": ["flight_status", "flight_prices", "search_trains", "book_flight"],
    "user_message": "Find me a flight from JFK to SFO on 2026-11-03, two of us, economy.",
    "expectation": {"acceptable_calls": [{
        "tool": "search_flights",
        "args": {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"},
        "may_include": {"passengers": 2, "cabin": "economy"},
    }]},
}

SMALLTALK = {
    "id": "travel-no-call",
    "source": {"kind": "authored"},
    "domain": "travel",
    "target_failure_mode": "SPURIOUS",
    "tools": ["search_flights", "airport_info"],
    "confusables": ["flight_status", "flight_prices", "search_trains", "book_flight"],
    "user_message": "Thanks, that's all I needed today.",
    "expectation": {"no_call_expected": True},
}

RECOVERY = {
    "id": "travel-recover-passengers",
    "source": {"kind": "authored"},
    "domain": "travel",
    "target_failure_mode": "WRONG_PARAMS",
    "tools": ["search_flights", "search_hotels"],
    "confusables": ["flight_status", "flight_prices", "search_trains", "book_flight"],
    "user_message": "Flights from BOS to ORD on 2026-12-01, just for me.",
    "expectation": {"acceptable_calls": [{
        "tool": "search_flights",
        "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01"},
        "may_include": {"passengers": 1, "cabin": "economy"},
    }]},
    "recovery": {
        "error_kind": "invalid_parameter",
        "param": "passengers",
        "expected": "this service requires the number of travellers, 1-9",
        "acceptable_recovery_calls": [{
            "tool": "search_flights",
            "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01",
                     "passengers": 1},
            "may_include": {"cabin": "economy"},
        }],
        "success_result": {"offers": [{"offer_id": "OF-1", "price_usd": 212}]},
        "success_claim_pattern": "\\bOF-\\d+\\b|\\$\\s?212",
    },
}



def library() -> Library:
    tools = {}
    for data in (TRAVEL, MISC):
        for d in data["tools"]:
            tools[d["name"]] = tool_from_dict(d, data["domain"])
    return Library(tools)


AIRPORTS = ("JFK", "SFO", "BOS", "ORD", "LAX", "SEA", "DEN", "ATL", "MIA", "DFW", "IAD", "PHX")


def synthetic_suite(n_call: int = 24, n_no_call: int = 4) -> list[dict]:
    """Distinct scenarios cloned from the three templates. Every third
    call scenario carries the recovery block, so recovery has as many
    scenarios as the bootstrap floor needs when n_call >= 60."""
    out = []
    for i in range(n_call):
        a, b = AIRPORTS[i % len(AIRPORTS)], AIRPORTS[(i * 5 + 1) % len(AIRPORTS)]
        if a == b:
            b = AIRPORTS[(i + 3) % len(AIRPORTS)]
        day = f"2026-11-{(i % 27) + 1:02d}"
        template = RECOVERY if i % 3 == 0 else FLIGHT
        d = copy.deepcopy(template)
        d["id"] = f"synthetic-call-{i:03d}"
        d["user_message"] = f"Flights from {a} to {b} on {day}, just for me. (#{i})"
        d["expectation"]["acceptable_calls"][0]["args"] = {
            "origin": a, "destination": b, "date": day}
        d["expectation"]["acceptable_calls"][0]["may_include"] = {
            "passengers": 1, "cabin": "economy"}
        if "recovery" in d:
            d["recovery"]["acceptable_recovery_calls"][0]["args"] = {
                "origin": a, "destination": b, "date": day, "passengers": 1}
        out.append(d)
    for i in range(n_no_call):
        d = copy.deepcopy(SMALLTALK)
        d["id"] = f"synthetic-nocall-{i:03d}"
        d["user_message"] = f"Thanks, that is everything for today. (#{i})"
        out.append(d)
    return out


def scenarios(dicts=None):
    lib = library()
    return [scenario_from_dict(d, lib) for d in (dicts or synthetic_suite())]


def write_suite(root: Path, dicts=None) -> tuple[Path, Path]:
    """Write the library and scenarios as files, the way toolcall/data/ holds them."""
    tools_dir, sc_dir = Path(root) / "tools", Path(root) / "scenarios"
    tools_dir.mkdir(parents=True, exist_ok=True)
    sc_dir.mkdir(parents=True, exist_ok=True)
    for data in (TRAVEL, MISC):
        (tools_dir / f"{data['domain']}.json").write_text(json.dumps(data))
    for d in dicts or (FLIGHT, SMALLTALK, RECOVERY):
        (sc_dir / f"{d['id']}.json").write_text(json.dumps(d))
    return tools_dir, sc_dir
