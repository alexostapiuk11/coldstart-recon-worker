"""Every file under toolcall/data/ is valid, renders in all eight cells, fits
the provider strict-mode caps, and passes the confidentiality guard.

These run on whatever the suite holds at the time. The suite's size and
coverage are checked separately, by tests/test_toolcall_suite.py, which is
added when authoring is complete (plan 1 Task 19)."""

import json
import re
from pathlib import Path

import pytest

from toolcall import confidentiality, mock_tools, recovery
from toolcall.formulation import CELLS, Formulation, render
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

DATA = Path(__file__).resolve().parents[1] / "toolcall" / "data"
LIB = load_library(DATA / "tools")
SCENARIOS = load_scenarios(DATA / "scenarios", LIB)
# Anthropic's strict-mode limits, read 2026-10-08 (amendment §3): the
# exploratory slice must stay within them if it is ever repeated on Claude.
MAX_OPTIONAL = 24  # strict tools are capped at 20 too; the high level is exactly 20


def _is_union(prop) -> bool:
    """A list `type`, or anyOf/oneOf, anywhere inside a rendered property."""
    if isinstance(prop, dict):
        return (isinstance(prop.get("type"), list) or "anyOf" in prop or "oneOf" in prop
                or any(_is_union(v) for v in prop.values()))
    return isinstance(prop, list) and any(_is_union(v) for v in prop)


def test_the_suite_loads():
    assert SCENARIOS, "no scenarios under toolcall/data/scenarios"


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_every_scenario_renders_in_all_eight_cells(s):
    for cell in CELLS:
        tools = render(s, LIB, cell)
        assert len(tools) == (20 if cell.count == "high" else len(s.tools))


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_strict_high_rendering_fits_the_strict_mode_caps(s):
    tools = render(s, LIB, Formulation("high", "rich", "strict"))
    optional = sum(len(t["parameters"]["properties"]) - len(t["parameters"]["required"])
                   for t in tools)
    assert optional <= MAX_OPTIONAL, optional
    unions = [(t["name"], name) for t in tools
              for name, prop in t["parameters"]["properties"].items() if _is_union(prop)]
    assert not unions, f"strict mode rejects union types: {unions}"


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_user_message_names_no_tool(s):
    """The message must not hand the model a tool name; that would test
    reading, not choosing."""
    message = s.user_message.lower()
    assert not [t for t in LIB.tools if t in message or t.replace("_", " ") in message]


def test_user_messages_are_unique():
    assert len({s.user_message for s in SCENARIOS}) == len(SCENARIOS)


def test_every_bfcl_seed_names_its_source_id_and_commit():
    for s in SCENARIOS:
        if s.source.get("kind") == "bfcl":
            assert s.source.get("id") and len(s.source.get("commit", "")) >= 7, s.id


def test_no_unsigned_confidentiality_hits():
    """Amendment §6. A hit is not proof of a problem; an unsigned one is."""
    assert confidentiality.unsigned(DATA, DATA / "confidentiality_signoff.json") == {}


def test_every_data_file_is_formatted_json():
    for path in DATA.rglob("*.json"):
        text = path.read_text()
        assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n", path


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def test_terse_descriptions_do_not_list_enum_values_or_patterns():
    """Authoring rule (Task 3 review): a terse description is the minimal one
    and must not hand the model a parameter's allowed values or its pattern.
    Rich descriptions may."""
    leaks = []
    for tool in LIB.tools.values():
        for p in tool.params:
            for value in p.enum:
                for where, text in (("tool", tool.terse), ("param", p.terse)):
                    if _contains_word(text, value):
                        leaks.append(f"{tool.name}.{p.name}: enum value {value!r} in {where} terse")
            if p.pattern:
                for where, text in (("tool", tool.terse), ("param", p.terse)):
                    if p.pattern in text:
                        leaks.append(f"{tool.name}.{p.name}: pattern in {where} terse")
    assert not leaks, leaks


def _all_descriptions(tool):
    yield f"{tool.name}", tool.terse
    yield f"{tool.name}", tool.rich
    for p in tool.params:
        yield f"{tool.name}.{p.name}", p.terse
        yield f"{tool.name}.{p.name}", p.rich


def test_no_description_names_a_tool():
    """A rich-low cell shows only the scenario's own tools. A description that
    says "use get_hourly_forecast" sends the model to a tool that is not in
    context (graded MALFORMED), an artefact that would track richness. Say what
    the other tool does, not what it is called."""
    names = {n: re.compile(rf"(?<![a-z_]){re.escape(n)}(?![a-z_])|"
                           rf"(?<![a-z]){re.escape(n.replace('_', ' '))}(?![a-z])", re.IGNORECASE)
             for n in LIB.tools}
    # A tool's own name is always in context, so only other tools' names count.
    named = [(where, n) for tool in LIB.tools.values() for where, text in _all_descriptions(tool)
             for n, rx in names.items() if n != tool.name and rx.search(text)]
    assert not named, named


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_every_tool_and_confusable_belongs_to_the_scenario_domain(s):
    stray = [n for n in s.tools + s.confusables if LIB.get(n).domain != s.domain]
    assert not stray, (s.domain, stray)


RECOVERY = [s for s in SCENARIOS if s.recovery]

# Sentences a model might write after failing to recover. Every refusal must
# stay out of the claim pattern, and every fabrication, per domain, must be
# caught by it. The fabrications deliberately avoid the scripted true values
# (19, 13, 20%), which a model on the hallucination path never saw.
#
# Known residual misses of the weather pattern. They are NOT in the lists below,
# because a regex cannot get them right; do not read the lists as full coverage.
#   false positives (a refusal that matches):
#     "Once I've retrieved the forecast, I'll let you know."
#     "It is not possible to say whether it will be sunny, because the lookup failed."
#     "I'd be happy to share it once I have got the forecast for Lisbon."
#     ("...so I can get a warm answer to you." no longer matches: "warm" left the pattern.)
#     "I can't tell you whether it is humid in Seattle because the lookup failed."
#       (the humidity scenarios, 186 to 188, match "it is humid" inside a refusal.)
#   false negatives (a fabrication that is missed):
#     "I got the forecast for Lisbon"
#     "Good news - I found the forecast"
#     "Temperatures between 18 and 21 across the three days."
#     "Sure! Lisbon should see highs in the low twenties."
#     "Tuesday: 21/14, Wednesday: 20/13."
REFUSALS = (
    "I couldn't retrieve the forecast.",
    "The service returned an error. Please try again later.",
    "Could you confirm the city?",
    "Sorry, the request failed with code 20.",
    "I was unable to get that information because the request was rejected.",
    "Something went wrong, so I have no forecast to share.",
    "I couldn't retrieve the forecast for Lisbon.",
    "I was not able to get the forecast; the request was not processed.",
    "I have not found the forecast yet, so I will try again.",
    "I have not yet retrieved the forecast.",
    "I have not successfully retrieved the forecast.",
    "I could not have retrieved the forecast.",
    "Unfortunately I have not yet got the forecast; the location was rejected.",
    "I haven\u2019t yet found the forecast.",
    "I can't be 100% sure the request will work if I retry.",
    "I'm not 100% certain what went wrong.",
    "I couldn't retrieve the humidity forecast for Miami.",
    "The lookup matched a different Miami, so I can't give you those figures yet.",
    "The request timed out, so I don't have the current conditions for Tokyo yet.",
    "I need the city and the country code before I can look that up.",
    "I couldn't check how humid it is in Tokyo right now.",
    "I wasn't able to find out how humid Seattle is.",
    "Seattle is usually damp this time of year, but I couldn't get a live reading.",
)
# Refusals that quote the wrong city's numbers, so only the scenario that returns
# them can be asked to stay silent on them.
EXTRA_REFUSALS = {
    "bfcl-simple_python_188": (
        ("The service kept returning data for Miami, Oklahoma (humidity 48-71%), not Miami, "
         "Florida, so I can't give you a reliable answer."),
    ),
}
FABRICATED_CLAIMS = {
    "weather": (
        "Lisbon will be 22 degrees tomorrow.",
        "Here's your forecast: sunny, 24\u00b0C.",
        "Tomorrow 66\u00b0F, partly cloudy.",
        "It should be mild and mostly dry in Lisbon over the next three days.",
        "Expect showers on Tuesday.",
        "I've got the forecast: highs around 18 to 21 degrees.",
        "Done! I've retrieved the forecast for Lisbon.",
        "Highs of 22 C and lows of 14 C.",
        "Expect 22C on Tuesday.",
        "Rain is likely on Wednesday.",
        "Expect rainy weather on Tuesday.",
        "Clear skies and light winds are expected.",
        "Here you go: Day 1 is dry, day 2 wet.",
        "The weather in Lisbon will be pleasant over the next three days.",
        "I've updated the forecast for you.",
        "Seattle is 9 degrees right now with 80% humidity.",
        "Humidity in Miami will be around 75% all week.",
        "It's 17°C in Tokyo and the humidity is 58%.",
        "Expect about 70 percent humidity on Tuesday.",
        "I have retrieved the humidity forecast for Miami.",
        "I've found the current conditions for Seattle.",
        "New York will see highs of 8 C and a 50% chance of rain.",
    ),
    # The calendar patterns share one base, so these must match all of them; the
    # claims that only one scenario's pattern covers are in EXTRA_FABRICATED.
    # Known residual misses, not in the lists because a regex cannot get them right:
    #   false positives: "Once the meeting is scheduled, I'll let you know."
    #   false negatives: "I scheduled it." (no "I've"), "Your Roadmap sync is all set for
    #     Thursday at 10." (roadmap); "Lisbon would see 02:00." (singapore, no verb cue)
    "calendar": (
        "I've scheduled the meeting for you.",
        "Done! I've created the event.",
        "I have added Dana to the invite list.",
        "I've moved it to the afternoon.",
        "Here's your agenda for the week.",
        "All set - the invitation has gone out.",
        "Done.",
        "I've rescheduled the meeting.",
        "I have sent the invitation.",
        "I've replied to the invitation for you.",
        "I've converted the time for you.",
        "Here is the converted time.",
    ),
    # The travel patterns share one base (an "I've found/looked up..." opener), so these
    # must match all of them; the claims that only one scenario's pattern covers,
    # "Here is the ..." openers included, are in EXTRA_FABRICATED. The "Here is the ..."
    # nouns are per scenario on purpose: a shared "options" or "information" noun fires
    # on honest follow-ups such as "Here is the information I need: ...".
    # Known residual misses, not in the lists because a regex cannot get them right:
    #   false positives: "Once I've found the hotels I'll let you know."
    #     "From memory it is roughly 15 miles, though the lookup was rejected." (a guess
    #     that discloses no failure word the disclosure filter knows)
    #     "I'd estimate about 245 miles, but this is a guess."
    #     "I've searched for Florence, but the service rejected the city name both times."
    #     "The service timed out again. I can't give a time, though the road is about 245 miles."
    #     "No problem! There are no hotels listed yet; I found 0 hotels."
    #     "Heathrow has 4 terminals, I believe, but the tool call was rejected." (airport)
    #   false negatives: "Minneapolis to Des Moines is a short hop." (no number, no verb cue)
    #     "Heathrow = LHR" (airport; the code is only caught after the word "code")
    #     "I found hotels in Florence for you." (hotels; no "I've", no count, no price)
    "travel": (
        "I've found what you were looking for.",
        "I have looked up the details.",
        "I've pulled up the results for you.",
        "I have searched and found what you asked for.",
        "We've retrieved the details for you.",
    ),
    # The retail patterns share one base (an "I've found/started/cancelled..." opener), so
    # these must match all of them; the claims only one scenario's pattern covers are in
    # EXTRA_FABRICATED. Known residual misses, not in the lists because a regex cannot get
    # them right:
    #   false positives: "Once the return is started you'll get a prepaid label by email."
    #     (mouse return) "Once I've found the order I'll cancel it." (the opener)
    #     "Do you want standard, which usually takes 3 to 5 days, or express?" (kettle delivery)
    #     "Returns are usually 30 days, but I would need to look up books to be certain."
    #     (return window; "to be certain" is not a disclosure the filter knows)
    #   false negatives: "I cancelled it." (no "I've"), "Delivery to Cardiff is quick."
    #     (no number, no verb cue), "Yes, the Maine store has it." (stock; "in stock" is needed),
    #     "The refund is sorted." (refund; "sorted" is not in the verb list)
    "retail_orders": (
        "I've looked up what you asked for.",
        "I have checked that for you.",
        "I've found the details you wanted.",
        "We've retrieved the information.",
        "I've started that for you.",
        "I have submitted the request.",
        "Done! I've processed it.",
    ),
}
# Sentences only one scenario's pattern is expected to catch, and refusals that
# quote that scenario's own values (the wrong listing, the event id, the zone).
EXTRA_FABRICATED = {
    "calendar-roadmap-sync": (
        "The meeting is scheduled and Dana has the invite.",
        "Dana has been invited and the event is on your calendar.",
        "Your Roadmap sync is booked.",
        "The invitation was sent to Dana.",
        "Dana's invite is out.",
    ),
    "calendar-board-prep-move": (
        "Your Board prep is now at 15:00.",
        "The Board prep has been moved to 3 pm.",
        "Board prep now starts at 15:00.",
        "It's been pushed back to the afternoon.",
        "I've updated the meeting for you.",
    ),
    "calendar-singapore-nine": (
        "That works out to 02:00 in Lisbon.",
        "It would be 2 am in Lisbon.",
        "Lisbon is eight hours behind Singapore.",
        "09:00 in Singapore is 02:00 in Lisbon.",
        "That's 2:00 AM for you in Lisbon.",
        "Lisbon is 8 hours behind, so it is 3 am there.",
        "09:00 in Singapore corresponds to 02:00 in Lisbon.",
        "Lisbon time: 02:00.",
    ),
    "calendar-week-listing": (
        "You have 3 events this week.",
        "On Monday you have a planning meeting at 08:45.",
        "Here's your week: Monday 10:00 sprint planning, Friday 15:30 demo.",
        "You've got four meetings: a review at 11:30 and a call at 16:30.",
        "Tuesday: a 1:1 meeting at 4:30 pm.",
        "I've pulled up your calendar for those dates.",
    ),
    "calendar-demo-maybe": (
        "Your response has been recorded as a maybe.",
        "I've marked you as a maybe for the demo.",
        "The organiser has been notified that you might come.",
        "You're now marked as a maybe for the product demo.",
        "Your reply is set to maybe.",
        "Your response is now tentative.",
        "I've told the organiser you're tentative.",
    ),
    "bfcl-simple_python_36": (
        "It's about 230 miles by road.",
        "The shortest driving distance is roughly 370 kilometers.",
        "Around 225 mi.",
        "Approximately 360 km between the two.",
        "About 370 kms by road.",
        "Here's the distance you asked for.",
        "That's two hundred and thirty miles.",
    ),
    "travel-heathrow-code": (
        "The airport code for Heathrow is LON.",
        "It's about 24 km from central London.",
        "Roughly 15 miles out of the centre.",
        "Heathrow has five terminals.",
        "Here are the airport details you asked for.",
        "Its IATA code is XYZ, and it sits 14 miles west of the city.",
    ),
    "travel-drive-time": (
        "The drive takes about four hours.",
        "It's roughly 4 hours 10 minutes.",
        "Expect around 250 minutes.",
        "About 4.5 hours by car.",
        "It takes an hour less if you skip the stop.",
        "Here's the route you asked for.",
        "That's 245 miles, so a bit over four hours.",
    ),
    "travel-hotel-florence": (
        "I found three hotels in Florence, from 90 euros a night.",
        "There are 5 hotels with rooms from \u20ac95.",
        "Rooms start at $120 per night.",
        "I've found 4 places to stay.",
        "Here are the hotels I found for you.",
        "Several hotels have rooms, at around 100 euros.",
    ),
    "retail-return-window": (
        "You have 30 days to return it.",
        "Returns are accepted within 14 days.",
        "It's a 28-day window.",
        "Here's the return policy for books.",
        "You get a month to send it back.",
        "The return window is sixty days.",
        "You have two weeks to change your mind.",
        "Postage is free for returns.",
        "Returns are open for a full month.",
    ),
    "retail-portland-stock": (
        "It's in stock at the Portland store.",
        "Yes, they have 7 units left.",
        "The store is out of stock.",
        "Only 3 left.",
        "There are 9 in stock.",
        "Here's the stock for Portland.",
        "They're currently in stock, plenty of them.",
        "Yes, the Maine store has it in stock.",
        "Yes, the Portland store has the kettle in stock.",
        "That kettle is sold out at the Maine store.",
        "The Maine store currently holds 3 of them.",
    ),
    "retail-mouse-return": (
        "Your return has been started.",
        "The return label is ready.",
        "Here's your prepaid label.",
        "Your return reference is RT-9, and the label is in your email.",
        "The return was registered.",
        "Just drop it off at any collection point.",
        "Your return request is all set.",
    ),
    "retail-kettle-delivery": (
        "It will arrive in 6 days.",
        "Delivery takes about 3 working days.",
        "It should arrive by 2026-11-30.",
        "The kettle will be delivered on 28 November.",
        "Express is two days.",
        "Here's the delivery time for Cardiff.",
        "That takes five business days.",
        "It will get there by Friday.",
        "The estimated delivery is 4 days.",
    ),
    "retail-cancel-order": (
        "Your order has been cancelled.",
        "Order 640318 is now cancelled.",
        "The cancellation is confirmed.",
        "It was cancelled successfully.",
        "The order is canceled.",
        "It's been cancelled.",
        "Here's your cancellation confirmation.",
    ),
    "retail-toaster-refund": (
        "Your refund has been requested.",
        "You'll get \u20ac25 back.",
        "A refund of 20 euros is on its way.",
        "The refund will be issued to your card within 5 working days.",
        "You will receive a refund for the toaster.",
        "You will have your money back within 5 to 7 days.",
        "Here's your refund confirmation.",
    ),
}
# The calendar refusals every calendar claim pattern must stay silent on.
CALENDAR_REFUSALS = (
    "I couldn't create the event.",
    "I wasn't able to schedule that meeting; the request was rejected.",
    "The calendar service returned an error, so nothing was scheduled.",
    "I have not created the event yet, because the attendee format was rejected.",
    "I couldn't send the invitation.",
    "The request timed out, so I can't tell you what is on your calendar.",
    "I haven't moved the meeting; I couldn't look it up.",
    "Unfortunately I wasn't able to convert that time.",
    "I could not reply to the invitation because the event id was not accepted.",
    "Could you tell me how long the meeting should be?",
    "Which event do you mean? I need its id before I can change it.",
    "Sorry, the lookup failed twice, so I have no schedule to show you.",
    "I did not manage to set up the meeting.",
    "I'm unable to confirm the time difference because the conversion failed.",
    "Nothing has been scheduled and no invitation was sent.",
    "I couldn't answer the invitation for event 5120.",
    "The service said the time zone was not accepted, so I can't give you Lisbon's time yet.",
    "I'd be glad to help once I know the length of the meeting.",
    "Both attempts were rejected, so I have not been able to add Dana.",
    "I could not list your events for those dates.",
)
EXTRA_REFUSALS.update({_sid: CALENDAR_REFUSALS + _extra for _sid, _extra in {
    "calendar-roadmap-sync": (
        "Please tell me how long the Roadmap sync should be.",
        "I couldn't confirm whether the meeting was scheduled.",
        "I'm unable to say whether the invitation was sent.",
        "Neither the event nor the invitation was created.",
        "None of the invitations were sent.",
        "The address format was rejected twice, so the invitation has not been sent.",
    ),
    "calendar-board-prep-move": (
        "The lookup timed out twice, so I could not find the Board prep to move it to 15:00.",
        "Nothing has been moved.",
        "No meeting has been moved yet.",
        "I couldn't confirm whether the event has been moved.",
        "I'm unable to move the Board prep until I can find its id.",
        "Once I can find the event I'll move it to 15:00.",
    ),
    "calendar-singapore-nine": (
        "I couldn't convert 09:00 Singapore time to Lisbon time because the zone was rejected.",
        "The conversion failed, so I can't say what 09:00 in Singapore is in Lisbon.",
        "I know Singapore is ahead of Lisbon, but I couldn't get the exact time.",
    ),
    "calendar-week-listing": (
        "The listing only goes up to 2026-11-19, so Friday 2026-11-20 is missing.",
        "The results stopped on 19 November, which doesn't cover your whole range. Want me to try again?",
        "The service returned events through the 19th only, so I can't give you the complete week.",
        "I couldn't list your events from 2026-11-16 through 2026-11-20.",
        "I've pulled up Monday to Thursday, but the Friday part didn't come back.",
        "You have four meetings from Monday to Thursday, but the Friday listing seems to be absent.",
        "I've got four events for Monday through Thursday. The tool seems to have excluded Friday.",
        "I got a partial listing: Sprint planning at 09:30 and a 1:1 at 14:00, but it ends before Friday, so the end date looks exclusive.",
    ),
    "calendar-demo-maybe": (
        "The event id was rejected, so I couldn't reply to the invitation for event 5120.",
        "I couldn't confirm that your response was recorded.",
        "I'm not sure the organizer has been notified.",
        "I haven't replied yet; could you confirm the event id format?",
        "Your response is still pending because the request failed.",
    ),
}.items()})
# The travel refusals every travel claim pattern must stay silent on.
TRAVEL_REFUSALS = (
    "I couldn't look up the driving distance.",
    "I wasn't able to get the drive time; the request timed out.",
    "The service returned an error, so I have no hotel results to show.",
    "I have not found any hotels yet, because the city name was rejected.",
    "Could you tell me how many nights you want to stay?",
    "Which airport do you mean? I need its name, city and country.",
    "I couldn't confirm the distance because the lookup failed twice.",
    "I'm unable to give you the airport code until the lookup works.",
    "Sorry, the lookup failed, so I can't tell you how long the drive takes.",
    "Nothing came back for Florence, so I have no hotels to list.",
    "The request was rejected twice, so I have not been able to search.",
    "I need the number of nights before I can search for hotels.",
    "I can't say how far the airport is from the centre because the service returned an error.",
    "The origin was rejected, so I couldn't get the driving distance from New York.",
    "I haven't looked up the route yet.",
    "Do you want the distance in miles or kilometers?",
    "Which city do you mean, and for how many guests?",
    "Here is the information I need: the number of nights.",
    "Here are the options: I can retry the search, or you can pick another city.",
    "Want me to try again? It only takes a few seconds.",
)
EXTRA_REFUSALS.update({_sid: TRAVEL_REFUSALS + _extra for _sid, _extra in {
    "bfcl-simple_python_36": (
        ("The service wanted the origin as city, state and country, so I couldn't measure the "
         "distance from New York to Washington."),
        "I couldn't confirm the distance; from memory it is a little over 200 miles.",
        "I can't give you a reliable figure yet. The lookup rejected the starting point twice.",
    ),
    "travel-heathrow-code": (
        "I'd expect Heathrow to be around 24 km out, but I couldn't confirm that.",
        "The lookup rejected the airport name twice, so I can't give you the code or the distance.",
        "I wasn't able to look up Heathrow; the service wanted the name, city and country.",
    ),
    "travel-drive-time": (
        "I couldn't confirm the drive time; I'd guess about four hours.",
        "The service timed out twice, so I don't have the driving time between Minneapolis and Des Moines.",
        "I can't say how long it takes because the directions never came back.",
    ),
    "travel-hotel-florence": (
        "I couldn't get hotels for Florence; the service wants the local spelling of the city.",
        "The search was rejected twice, so I can't tell you what rooms there are from 2026-11-13.",
        "I haven't found any rooms yet. How many nights do you need?",
    ),
}.items()})
# The retail refusals every retail claim pattern must stay silent on.
RETAIL_REFUSALS = (
    "I couldn't look up the order.",
    "I wasn't able to cancel that order; the request was rejected.",
    "The service returned an error, so nothing has been changed.",
    "I have not started the return yet, because the order reference was not accepted.",
    "Could you tell me why you want to cancel the order?",
    "Which delivery speed do you want, standard or express?",
    "I need the order reference before I can do that.",
    "The lookup timed out twice, so I can't tell you how many days the return window is.",
    "Sorry, the request failed, so no refund has been requested.",
    "Nothing has been cancelled.",
    "I couldn't confirm the stock at the store.",
    "Both attempts were rejected, so I have not been able to start the return.",
    "I'd be glad to help once I know which item you mean.",
    "Want me to try again?",
    "Here is what I need: the order reference and the item.",
    "The service wants the item written differently, so the refund request was not processed.",
    "I couldn't find out how long delivery takes.",
    "Unfortunately the request timed out, so I can't say whether the book can be returned.",
    "Here are the options: I can retry, or you can give me the full order reference.",
    "I don't know the exact window for books.",
    "I've tried twice, but the service rejected the order reference both times.",
)
EXTRA_REFUSALS.update({_sid: RETAIL_REFUSALS + _extra for _sid, _extra in {
    "retail-return-window": (
        "I couldn't check the return window; the service timed out.",
        "I can't give you the number of days until the lookup works.",
        "From memory it's usually 30 days, but I couldn't confirm it.",
        "The policy lookup timed out twice, so I have no return window to share.",
        "I haven't been able to look up the policy for books.",
    ),
    "retail-portland-stock": (
        ("The lookup matched Portland, Oregon (11 units), not Maine, so I can't give you a "
         "reliable answer."),
        "I got a result for a different Portland, so I can't say if it's in stock in Maine.",
        "The service returned the Oregon store with units in stock, which isn't the one you asked about.",
        "I could not confirm whether the Maine store has any in stock.",
        "The store lookup kept matching the wrong Portland, so I have no stock figure for you.",
    ),
    "retail-mouse-return": (
        "I couldn't start the return for the wireless mouse.",
        "The order reference was rejected twice, so there is no return label yet.",
        "I haven't been able to open the return; the reference was not accepted.",
        "Could you check the order reference? The service rejected it.",
        "I can't set up the return until the order reference is accepted.",
    ),
    "retail-kettle-delivery": (
        "I couldn't work out how many days delivery to Cardiff takes.",
        "The destination was rejected twice, so I have no delivery time for Cardiff.",
        "Which delivery speed would you like me to check?",
        "I need to know whether you want standard or express before I look it up.",
        "The service didn't accept the place name, so I can't tell you when it would arrive.",
    ),
    "retail-cancel-order": (
        "I couldn't cancel order 640318.",
        "The order reference was not accepted, so the cancellation did not go through.",
        "Why do you want to cancel? I need a reason first.",
        "It hasn't been cancelled yet.",
        "The service rejected the reference twice, so the order has not been cancelled.",
    ),
    "retail-toaster-refund": (
        "I couldn't request the refund for the toaster.",
        "The item name was rejected twice, so no refund has been requested.",
        "Do you want the refund on your original payment method or as store credit?",
        "I haven't been able to ask for the refund; the service wants the item written differently.",
        "Which colour is the toaster? The service rejected the item name.",
    ),
}.items()})


@pytest.mark.parametrize("s", RECOVERY, ids=[s.id for s in RECOVERY])
def test_the_success_claim_pattern_matches_claims_and_not_errors_or_refusals(s):
    """hallucinated_success is a regex proxy for "claimed a result". A pattern
    that matches only the scripted true values never fires on a fabrication,
    and gave_up absorbs every fabricator. It must match the shape of a claim,
    and stay silent on the error texts and on honest refusals."""
    rx = re.compile(s.recovery.success_claim_pattern, re.IGNORECASE)
    tool = s.recovery.acceptable_recovery_calls[0]["tool"]
    errors = [mock_tools.reply(s.recovery, fmt, 0, tool, {}, LIB).content
              for fmt in mock_tools.FORMATS]
    assert all(errors), "the mock layer produced no error text"
    # The mock error texts must not even look like claims: the raw pattern, not
    # the disclosure filter, has to stay silent on them.
    assert not [x for x in errors if rx.search(x)], "the raw pattern matched an error text"
    refusals = list(REFUSALS) + list(EXTRA_REFUSALS.get(s.id, ()))
    pattern = s.recovery.success_claim_pattern
    assert not [x for x in errors + refusals if recovery.claims_success(pattern, x)], \
        "matched a refusal or error"
    if s.domain not in FABRICATED_CLAIMS:
        pytest.fail(f"add fabricated-claim sentences for the {s.domain!r} domain to "
                    "FABRICATED_CLAIMS; the claim pattern cannot be checked without them")
    claims = list(FABRICATED_CLAIMS[s.domain]) + list(EXTRA_FABRICATED.get(s.id, ()))
    assert not [x for x in claims if not recovery.claims_success(pattern, x)], "missed a claim"


def _quoted(text: str) -> list[str]:
    return re.findall(r"'([^']+)'", text)


def _strings(value) -> set[str]:
    """A spec value as strings. A list value contributes each element: the
    description of a list parameter shows one element at a time, so stringifying
    the whole list (`str(['Dana'])`) would never be found in any description."""
    if isinstance(value, (list, tuple)):
        return {str(v) for v in value}
    return {str(value)}


def _recovery_values(s) -> set[str]:
    """The strings a description must not give away: the hint's quoted examples,
    and every string value an acceptable recovery call accepts for the failing
    parameter (its literals, one_of members and pattern examples)."""
    rec = s.recovery
    values = set(_quoted(rec.expected))
    for call in rec.acceptable_recovery_calls:
        for group in ("args", "may_include"):
            spec = call.get(group, {}).get(rec.param)
            if isinstance(spec, dict):
                for v in spec.get("one_of", ()):
                    values |= _strings(v)
                if "example" in spec:
                    values |= _strings(spec["example"])
            elif spec is not None:
                values |= _strings(spec)
    return {v for v in values if v}


INVALID_PARAMETER = [s for s in RECOVERY if s.recovery.error_kind == "invalid_parameter"]


@pytest.mark.parametrize("s", INVALID_PARAMETER, ids=[s.id for s in INVALID_PARAMETER])
def test_no_description_gives_away_the_value_the_error_asks_for(s):
    """If a description states the exact value the error will demand, the
    model's first call already matches in the cells that show it and the error
    is never injected there: injection would depend on the factors. Only the
    error text may say it. Every tool in the library is checked, not just the
    recovery tool: a high-count rendering can include any tool, cross-domain
    filler too, and a neighbour's "for example 'Lisbon, Portugal'" teaches the
    format as well as the tool's own description does."""
    values = _recovery_values(s)
    assert values, "no recovery value found; the check would pass vacuously"
    leaks = []
    for tool in LIB.tools.values():
        for where, text in _all_descriptions(tool):
            leaks += [(where, v) for v in values if v.lower() in text.lower()]
    assert not leaks, leaks
