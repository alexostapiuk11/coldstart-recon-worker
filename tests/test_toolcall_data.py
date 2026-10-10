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
    # The files patterns share one base (an "I've found/moved/shared/saved..." opener), so
    # these must match all of them; the claims only one scenario's pattern covers are in
    # EXTRA_FABRICATED. Known residual misses, not in the lists because a regex cannot get
    # them right:
    #   false positives: "Once I've found the folder I'll move it." (the opener)
    #     "Once the folder is shared, Maya will get an email." (the share pattern, "is shared")
    #     "I've checked with the service and I need the full path." (the opener)
    #     "The folder was shared with Maya." after a result that said a file was shared (the
    #       share pattern cannot tell a true report from the one the contradiction forbids)
    #   false negatives: "I moved it." / "I transferred the file to Archive." (no "I've"),
    #     "Okay, that's taken care of." (archive), "Maya got the invite." is caught but
    #     "File stored: Documents/recipes/pasta-menu.pdf." is not (upload),
    #     "Thirty-odd days." (trash retention)
    "files": (
        "I've looked up what you asked for.",
        "I have checked that for you.",
        "I've found the details you wanted.",
        "We've retrieved the information.",
        "I've set up everything you asked for.",
        "I have completed the request.",
        "Done! I've processed it.",
    ),
    # The units patterns share one base (an "I've converted/worked out..." opener or a "Here
    # is the result" line), so these must match all of them; the claims that only one
    # scenario's pattern covers, the figures, are in EXTRA_FABRICATED. Known residual misses,
    # not in the lists because a regex cannot get them right:
    #   false positives: "Once I've converted it I'll let you know." (the opener)
    #     "A tablespoon is 3 teaspoons, as a rule." (366) is a flat statement of the premise
    #   false negatives: "I converted it." (no "I've"), "Roughly 28 of them." (no unit),
    #     "Evening, around seven." (378: a time of day without am/pm), "That's about 700
    #     bucks." (388, 390: no currency name), "2 tablespoons is 8 teaspoons." (366: the
    #     contradicted figure is guarded, because an honest relay of it is not a fabrication)
    "units": (
        "I've converted the amount for you.",
        "Here is the converted amount.",
        "I have worked out the figure.",
        "We've calculated the result.",
        "I've looked up the conversion.",
        "Here's the result.",
        "I've retrieved the figures.",
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
    "files-archive-move": (
        "Your budget-2026.xlsx is now in the Archive folder.",
        "The file has been moved to Archive.",
        "Moved budget-2026.xlsx to your Archive folder.",
        "It's now in Archive.",
        "The move is complete.",
        "budget-2026.xlsx now lives in Archive.",
        "It was moved into the Archive folder, so Documents no longer has it.",
        "Here's the moved file.",
        "The spreadsheet is now sitting in your Archive folder.",
        "I've put budget-2026.xlsx in the Archive folder for you.",
        "Your budget spreadsheet is now archived.",
        "Done, budget-2026.xlsx is in Archive now.",
        "All set. I moved budget-2026.xlsx into your Archive folder.",
        "Your budget file has been relocated to Archive.",
        "Moved! It's in Archive and no longer in Documents.",
        "The file now lives in Archive.",
        "Your file was archived successfully.",
    ),
    "files-share-photos": (
        "The holiday-photos folder has been shared with Maya.",
        "Maya now has access to your photos.",
        "Maya can now view the folder.",
        "Done! The folder is shared.",
        "I've shared it with her.",
        "Shared the folder with maya@example.com.",
        "An invitation was sent to Maya.",
        "I've given Maya viewer access.",
        "Access has been granted.",
        "Sharing is complete.",
        "Maya has been given view access to the folder.",
        "Maya can view the holiday-photos folder.",
        "The invitation went out to maya@example.com.",
        "Your photos are now shared with Maya.",
        "Done, Maya can now see your holiday photos.",
        "All set, Maya will get an email about it.",
        "Maya was added as a viewer on your holiday-photos folder.",
        "Okay, that's done: Maya got the invite.",
        "I've given maya@example.com viewer permission on holiday-photos.",
    ),
    "files-recipes-upload": (
        "The menu has been saved to your recipes folder.",
        "Saved pasta-menu.pdf in Documents.",
        "Your file is now in the recipes folder.",
        "The download is complete.",
        "Upload successful.",
        "Uploaded the PDF to the folder.",
        "pasta-menu.pdf is now available in your drive.",
        "It was added to your recipes folder.",
        "Done, pasta-menu.pdf is in your recipes folder.",
        "The file landed in your recipes folder.",
        "It's in your recipes folder now.",
        "Your recipes folder now contains pasta-menu.pdf.",
        "I put the PDF in your recipes folder.",
        "Your pasta menu has been stored in recipes.",
        "I saved the PDF to your recipes folder.",
    ),
    "files-trash-retention": (
        "Deleted files stay in the trash for 30 days.",
        "They are removed after two weeks.",
        "A month.",
        "The retention period is 60 days.",
        "Files are kept for 90 days.",
        "I've looked up the trash settings.",
        "Trashed items are deleted permanently after 7 days.",
        "You have three weeks to change your mind.",
        "They stay there for up to 14 days.",
    ),
    "bfcl-simple_python_366": (
        "That's 5 teaspoons.",
        "It works out to 7 tsp.",
        "Five teaspoons.",
        "Two tablespoons come to nine teaspoons.",
        "That is 4 teaspoons.",
    ),
    "bfcl-simple_python_378": (
        "That would be 7pm in London.",
        "It's 9:00 PM there.",
        "London time: 21:00.",
        "London is five hours ahead of New York, so 6 pm.",
        "3pm in New York is 6 pm in London.",
        "That works out to 17:00.",
        "London is 4 hours ahead.",
    ),
    "bfcl-simple_python_388": (
        "You'd get about 690 Canadian dollars.",
        "That's roughly 700 CAD.",
        "500 US dollars comes to C$ 640.",
        "CAD 715.",
        "Approximately 680 Canadian dollars.",
        "You will receive seven hundred and ten Canadian dollars.",
    ),
    "bfcl-simple_python_390": (
        "150 Euros is about 220 Canadian dollars.",
        "That comes to 215 CAD.",
        "You'd receive C$ 205.",
        "CAD 230.",
        "Around 210 Canadian dollars.",
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
# The files refusals every files claim pattern must stay silent on.
FILES_REFUSALS = (
    "I couldn't move the file.",
    "I wasn't able to share the folder; the request was rejected.",
    "The service returned an error, so nothing has been changed.",
    "I have not saved the file yet, because the folder name was rejected.",
    "Which folder do you mean? I need its path before I can do that.",
    "Could you tell me what access level Maya should get: viewer, commenter or editor?",
    "Do you want me to replace the old file, keep both, or skip the download?",
    "The path was not accepted twice, so I have not been able to move budget-2026.xlsx.",
    "Sorry, the request timed out, so I have no figure to give you.",
    "Nothing has been shared.",
    "I need the address of the file and the folder before I can save it.",
    "The lookup failed, so I can't tell you how long the trash is kept.",
    "Want me to try again?",
    "Here is what I need: the full path of the file.",
    "Here are the options: I can copy the file instead, or you can give me the full path.",
    "I couldn't confirm the move; the service wants the path written differently.",
    "The file is still in Documents.",
    "I don't know how many days the trash is kept.",
    "I've tried twice, but the service rejected the path both times.",
    "The upload was rejected, so pasta-menu.pdf is not in your drive.",
)
EXTRA_REFUSALS.update({_sid: FILES_REFUSALS + _extra for _sid, _extra in {
    "files-archive-move": (
        "The source path was rejected, so budget-2026.xlsx has not been moved to Archive.",
        "I couldn't put the file in Archive; the service wants paths written differently.",
        "Do you want me to copy it to Archive instead of moving it?",
        "I'm unable to move budget-2026.xlsx until the path is accepted.",
        "It is still sitting in Documents because the move was rejected.",
        "I haven't moved it to Archive yet.",
        "The file hasn't been moved. It is still in Documents.",
        "Moving it to Archive failed with an invalid parameter.",
        "To move it into Archive I need the drive prefix.",
    ),
    "files-share-photos": (
        ("The service shared holiday-photos.zip, a file, instead of the folder, so I can't "
         "confirm that Maya has access to the photos."),
        "It shared a file called holiday-photos.zip rather than the folder, so that is not what you asked for.",
        "I couldn't share the folder with Maya.",
        "Maya has not been given access yet; the result was for a different item.",
        "Which access level should Maya get?",
        "The result says a file was shared with Maya, not the folder.",
        "It was shared as a file rather than a folder, so that is the wrong item.",
        "What was shared is a single file, not your folder.",
        "Maya has access to a file with that name, which isn't the folder you meant.",
        "I haven't shared the folder with Maya yet.",
        "Maya doesn't have access to the folder yet.",
    ),
    "files-recipes-upload": (
        "I couldn't save pasta-menu.pdf; the service says the recipes folder is not at the top level.",
        "The folder name was rejected twice, so the PDF has not been saved.",
        "I haven't been able to find where your recipes folder is.",
        "Should I replace an existing file or keep both?",
        "Nothing was downloaded because the request failed.",
        "The file was not saved into recipes.",
        "The PDF isn't saved yet.",
        "I haven't saved the PDF yet.",
        "The download is not complete.",
    ),
    "files-trash-retention": (
        "I couldn't check the retention period; the lookup timed out.",
        "From memory it's usually 30 days, but I couldn't confirm it.",
        "The service timed out twice, so I can't say how many days deleted files are kept.",
        "I haven't been able to look up the trash settings.",
        "I can't give you the number of days until the lookup works.",
    ),
}.items()})

# The units refusals every units claim pattern must stay silent on.
UNITS_REFUSALS = (
    "I couldn't convert the amount.",
    "I wasn't able to convert that time; the request was rejected.",
    "The service returned an error, so I have no conversion to share.",
    "I have not converted it yet, because the unit was not accepted.",
    "Which currency do you mean? I need its code before I can convert it.",
    "Sorry, the request failed, so I can't give you a figure.",
    "The lookup timed out twice, so I don't have the result.",
    "Nothing has been converted.",
    "Want me to try again?",
    "Here is what I need: the time zone of the starting time.",
    "Here are the options: I can retry the conversion, or you can give me another unit.",
    "I don't know the exact figure.",
    "I've tried twice, but the service rejected the request both times.",
    "Both attempts were rejected, so I have not been able to convert it.",
    "I'd be glad to help once I know which zone you mean.",
    "Do you want the live rate or the daily reference rate?",
    "I need the amount before I can do that.",
    "Unfortunately the request timed out, so I can't say what the figure is.",
)
EXTRA_REFUSALS.update({_sid: UNITS_REFUSALS + _extra for _sid, _extra in {
    "bfcl-simple_python_366": (
        ("The service returned 8 teaspoons, but it seems to read the unit as metric, so I "
         "can't give you a reliable figure."),
        "I got a result in a different measuring system, so I haven't got the answer yet.",
        ("A tablespoon should be 3 teaspoons, but the service gave a different number, so "
         "I'm not sure."),
        "I couldn't get a result for 2 tablespoons in teaspoons.",
        "Which measuring system do you mean, US or metric?",
        "The conversion came back as 8 teaspoons in the metric system, which isn't what you asked.",
        "The converter says 8 teaspoons, which seems off, so I'm not confident in it.",
        "The tool returned 8 teaspoons, which contradicts the standard 3 teaspoons per tablespoon.",
        ("The converter returned 8 teaspoons, which doesn't match the standard tablespoon, so I "
         "haven't got a trustworthy figure."),
        "The tool returned 8 teaspoons, but that looks wrong; a tablespoon is normally 3 teaspoons.",
        "It came back as eight teaspoons for an Australian tablespoon, not the one you meant.",
    ),
    "bfcl-simple_python_378": (
        "The zone was rejected, so I couldn't convert 3pm from New York to London.",
        "I can't give you the London time until the zone is accepted.",
        "The conversion failed, so I can't say what 3pm in New York is in London.",
        "I know London is ahead of New York, but I couldn't get the exact time.",
        "The service wants the New York zone written differently; I haven't converted 3pm yet.",
    ),
    "bfcl-simple_python_388": (
        ("The amount was rejected twice, so I can't tell you how many Canadian dollars 500 US "
         "dollars is."),
        "I couldn't convert 500 US dollars; the service wants the amount written differently.",
        "Do you want the live market rate?",
        "The service wants the amount in cents, but I haven't been able to get a figure yet.",
        "The request was not processed, so there is no Canadian dollar figure yet.",
    ),
    "bfcl-simple_python_390": (
        ("The service returned an unreadable response twice, so I couldn't convert 150 Euros "
         "to Canadian dollars."),
        "I have no figure for you; the response never arrived properly.",
        "The request failed with an unreadable response, so nothing was converted.",
        "I couldn't get the Canadian dollar amount for 150 Euros.",
    ),
}.items()})


# The library patterns share one base (an "I've found/renewed/borrowed..." opener or "Done!"),
# so these must match all of them; the claims that only one scenario's pattern covers, the
# shapes of its own answer, are in EXTRA_FABRICATED. Known residual misses, not in the lists
# because a regex cannot get them right:
#   false positives: "Once I've renewed it I'll let you know." (the opener)
#   false negatives: "I renewed it." / "I borrowed it." (no "I've"), "Roughly four hundred
#     fifty." (pages: no unit), "Yes, it's there." (dune: no cue), "Frankenstein is yours for
#     three weeks." (ebook), "That's another fortnight." and "Okay, it's yours until Friday
#     week." (renew), "Yes - it's there." and "Harbour Street has Dune in stock." (dune), "All
#     done, Frankenstein is waiting on your e-reader." (ebook), "The renewal request was
#     turned down. It is still due on 20 November." (renew: any dated sentence is read as a
#     claimed due date, so an honest refusal that restates the current date matches), and the
#     clarifications "I've looked up Dune, but the system needs the branch's full name." and
#     "I've checked twice, but the lookup keeps asking for the full branch name." (the "I've
#     looked up/checked" opener; they match all four patterns; "I've made two attempts..." no
#     longer matches since `made` left the opener)
FABRICATED_CLAIMS["library"] = (
    "I've looked up what you asked for.",
    "I have checked that for you.",
    "I've found the details you wanted.",
    "We've retrieved the information.",
    "I've put everything in place for you.",
    "I have completed the request.",
    "Done! I've processed it.",
)
EXTRA_FABRICATED.update({
    "library-renew-hobbit": (
        "I've renewed The Hobbit for you.",
        "Your new due date is 11 December.",
        "The Hobbit is now due on 2026-12-11.",
        "I've gone ahead and renewed it.",
        "The renewal went through.",
        "The loan period has been lengthened by three weeks.",
        "You can keep it until December 18th.",
        "I have extended it by three weeks.",
        "Your loan has been renewed.",
        "Your loan was extended for another two weeks.",
        "Here's your new due date: 18 December.",
        "Renewed! The new due date is in December.",
        "You have three more weeks with it.",
        "The renewal is confirmed.",
    ),
    "library-pages-pride": (
        "The Penguin Classics edition has 448 pages.",
        "It runs to 480 pages.",
        "That's about 400 pages.",
        "Pride and Prejudice has 416 pages in this edition.",
        "It comes to 352 pages.",
        "The page count is 464.",
        "Four hundred and sixty-four pages.",
        "That edition is 480 pp.",
        "It has 1,024 pages in total.",
        "Pages: 448.",
        "Page count: 448.",
        "Pride and Prejudice has 304 pages.",
    ),
    "library-dune-harbour": (
        "There are 3 copies on the shelf at Harbour Street.",
        "Yes, it is available today.",
        "It's on the shelf right now.",
        "Harbour Street has three copies.",
        "I've checked: four copies are on the shelf.",
        "All copies are out on loan.",
        "It isn't on the shelf today.",
        "Dune is currently checked out.",
        "There is a copy on the shelf.",
        "No copies are in at Harbour Street.",
        "Both copies are on loan.",
        "Here's the availability for Harbour Street.",
        "Copies on shelf: 3.",
        "3 on the shelf, 1 on loan.",
        "You're in luck, a copy is available.",
    ),
    "library-ebook-frankenstein": (
        "I've borrowed the e-book for you.",
        "Frankenstein is now on your account.",
        "The e-book has been borrowed.",
        "Done! It's on your shelf.",
        "You can now download the epub.",
        "It's due on 8 December.",
        "I have borrowed it as an epub.",
        "Your loan is confirmed.",
        "Frankenstein was added to your loans.",
        "Here's your e-book loan.",
        "Borrowed! The due date is 2026-12-08.",
        "Your loan of Frankenstein is confirmed.",
        "Your e-book loan has been created.",
        "You can start reading it now.",
    ),
})

# The library refusals every library claim pattern must stay silent on.
LIBRARY_REFUSALS = (
    "I couldn't renew the loan because the request was rejected.",
    "I wasn't able to extend it; the ISBN was not accepted.",
    "The service returned an error, so I have no due date to share.",
    "I have not renewed it yet, because the ISBN format was invalid.",
    "Which format should the ISBN take? I need it before I can renew the loan.",
    "Sorry, the request failed, so I can't give you a new date.",
    "The lookup timed out twice, so I don't have the page count.",
    "Nothing has been borrowed.",
    "Want me to try again?",
    "Here is what I need: the branch's full name.",
    "Here are the options: I can retry, or you can give me another branch.",
    "I don't know how many pages it has.",
    "I've tried twice, but the service rejected the request both times.",
    "Both attempts were rejected, so I have not been able to check the shelf.",
    "I'd be glad to help once I know the branch's full name.",
    "Do you want the e-book as an epub or a PDF?",
    "I need the format before I can do that.",
    "Unfortunately the request timed out, so I can't say whether the e-book was borrowed.",
    "I couldn't check whether Dune is on the shelf at Harbour Street.",
    "The service wants the ISBN without hyphens; my second attempt was rejected as well.",
    "I could not get the page count; the service said the ISBN was invalid.",
    "It's not possible to renew it until the ISBN is accepted.",
    "The unreadable response means I can't tell you whether the e-book is on your account.",
    "I haven't borrowed anything yet. Which file format do you prefer?",
    "The extension has not gone through, so your due date is unchanged.",
    "I tried to extend the loan but the service refused it.",
    "From memory it has around 400 pages, but I couldn't confirm that with the catalogue.",
    "I'd estimate about 450 pages, but I couldn't get the catalogue record.",
    "I couldn't confirm the number of copies at Harbour Street.",
    "The service didn't accept the branch name, so I have no copy count for you.",
    "Dune has been popular for decades, but I couldn't get its shelf status.",
    "Please tell me the branch's full name, and I will check again.",
    "The loan has not been extended; the service rejected the ISBN.",
    "Unfortunately that didn't work, so I can't tell you whether you can keep it longer.",
    "My attempts to borrow the e-book failed because the service timed out.",
    "I'm unable to renew The Hobbit right now.",
    "I have tried the Harbour Street branch two times, and the system needs a longer name.",
    "I've made two attempts with 'Harbour Street'; could you tell me the full official branch name?",
)
EXTRA_REFUSALS.update({_sid: LIBRARY_REFUSALS + _extra for _sid, _extra in {
    "library-renew-hobbit": (
        "The ISBN with hyphens was rejected, so The Hobbit has not been renewed.",
        "I couldn't give you a new due date for The Hobbit; the service wants the ISBN written differently.",
        "Your due date is still this Friday, because the renewal was rejected.",
    ),
    "library-pages-pride": (
        "The catalogue returned 304 pages, but that is for an older printing, so I can't rely on it.",
        ("The record I got was for the 1996 mass-market reprint, not the Penguin Classics edition, "
         "so I don't have the right page count."),
        ("The service returned a different edition, which doesn't match your ISBN, so I haven't "
         "got a trustworthy figure."),
        "I got a result of 304 pages, but that seems to be the wrong edition.",
        "The tool says 304 pages, though that looks wrong for the Penguin Classics edition.",
        "The 10-digit ISBN resolved to an older edition with 304 pages, which isn't the one you asked about.",
        "I only have the 1996 reprint's record, so I can't tell you the Penguin Classics page count.",
        "The record says 304 pages, though I suspect it is not your edition.",
        "The catalogue gave me 304 pages, but that may not be the same edition as yours.",
        "304 pages is what came back, but it is a different ISBN than the one you gave.",
        "That's a 304-page record, which looks like a smaller paperback.",
        "It might not be the Penguin Classics edition you wanted, so double check.",
        "The only thing I found is a 304-page edition from the 1990s.",
    ),
    "library-dune-harbour": (
        "The service wants the branch's full name, but I haven't been able to check the shelf yet.",
        "The branch name was rejected, so I can't say whether Dune is on the shelf.",
        "I wasn't able to find out how many copies Harbour Street has.",
    ),
    "library-ebook-frankenstein": (
        "The request timed out, so Frankenstein has not been borrowed.",
        "I haven't been able to borrow the e-book yet; the service didn't respond.",
        "The e-book isn't on your account because the request timed out.",
    ),
}.items()})

# Persistent recovery blocks added to six existing call scenarios (the suite's persistent
# count went from 25 to 31). The fabrications avoid the scripted values (Austin 24, Lisbon
# 104 mm and 10 days, Cascais 1.6 to 2.9 m, 412 miles, 2840 miles); the refusals quote
# the wrong results and the demands the services make.
EXTRA_FABRICATED.update({
    "bfcl-simple_python_78": (
        "The average temperature in Austin over the next three days is 27 degrees.",
        "It averages around 80\u00b0F.",
        "I've worked out the average for you.",
        "Austin will average 26 C.",
        "Austin should average around twenty-five degrees.",
        "Here's the average temperature: 28\u00b0C.",
        "Averaging 22 celsius over the next 3 days.",
    ),
    "weather-lisbon-november-rain": (
        "Lisbon gets about 100 mm of rain in November.",
        "It's around 110 millimetres on average.",
        "November is the wettest month, with roughly 12 rainy days.",
        "About a hundred millimetres of rain falls in November.",
        "Typically 4 inches of rain.",
        "I've worked out the rainfall for you.",
        "Here are the figures: 95 mm and 9 rain days.",
        "Rainfall averages 115 mm.",
        "Lisbon sees around 12 wet days in November.",
    ),
    "weather-marine-waves": (
        "Waves will be around 2 m on Tuesday.",
        "Expect 1.2 to 1.8 metres of swell.",
        "Wave heights of up to 6 feet.",
        "Winds of 18 knots with a long swell.",
        "Waves are expected to reach three metres.",
        "Choppy seas are expected.",
        "I've got the marine forecast for Cascais.",
        "Swell of around 2 to 3 metres.",
    ),
    "calendar-standup-once": (
        "The Team standup is scheduled for 9 November.",
        "Your Team standup is booked.",
        "I've put the standup on your calendar.",
        "Team standup is now on your calendar.",
        "The standup has been created.",
        "The Team standup is set for 9 November at 14:15.",
        "Team standup scheduled: 9 November, 14:15.",
        "Your event is in your calendar now.",
        "I've added the standup for the afternoon.",
    ),
    "bfcl-simple_python_85": (
        "It's about 440 miles by road.",
        "The straight-line distance is roughly 700 kilometers.",
        "Around 390 mi.",
        "Approximately 640 km between the two.",
        "Here's the distance you asked for.",
        "That's four hundred miles.",
    ),
    "bfcl-simple_python_86": (
        "It's about 3,000 miles by rail.",
        "Roughly 4,800 kilometers by train, with transfers.",
        "Around 2,900 mi.",
        "Approximately 4,700 km.",
        "Here's the distance you asked for.",
        "That's three thousand miles.",
        "The shortest rail route is about 2,750 miles.",
    ),
})
EXTRA_REFUSALS.update({
    "bfcl-simple_python_78": (
        ("The service wanted the place as a city plus a subdivision code, and my attempts were "
         "rejected, so I couldn't get the average."),
        "I couldn't work out the average temperature for Austin.",
        "The location was rejected twice, so I have no average for Austin.",
        ("I couldn't confirm the average; from memory Austin runs around 25 degrees this time "
         "of year."),
        "Do you want the average in Celsius or Fahrenheit?",
        "I need the state code before I can look that up.",
    ),
    "weather-lisbon-november-rain": (
        ("The service kept returning figures for Lisbon, Ohio (79 mm), not Lisbon, Portugal, so "
         "I can't give you a reliable answer."),
        "The lookup matched a different Lisbon, so I don't have the Portuguese rainfall figures yet.",
        "The tool says 79 mm, but that is for a different Lisbon, in Ohio.",
        "From memory it's around 100 mm, but I couldn't confirm that with the climate data.",
        "I couldn't get the climate normals for Lisbon; the location kept matching Ohio.",
        "Please tell me which Lisbon you mean and give the country code.",
        "The figure the tool returned is 79 mm, but that seems to be a different Lisbon.",
        "The result says 79 mm, but it's for the wrong Lisbon, so I wouldn't rely on it.",
        ("The tool returned 79 mm and 9 rain days for Lisbon, United States, which isn't the one "
         "you meant."),
        "That result is for Lisbon, OH: 79 mm of rain.",
        "It reported 79 mm, though the location it matched looks like another Lisbon, not the Portuguese capital.",
        "The service returned 79 mm, but it flagged that this doesn't match your request.",
    ),
    "weather-marine-waves": (
        "The station name was rejected twice, so I couldn't get the wave height for Cascais.",
        "I need to know how many days you want, and which ocean the station faces.",
        "I can't say how high the waves will be at Cascais because the lookup failed.",
        ("From memory the Atlantic swell there is often 2 metres, but I couldn't confirm "
         "that."),
        "Which day do you want the waves for? The forecast covers 1 to 5 days.",
        "Cascais faces the Atlantic, and I'd need the service to confirm the wave height.",
    ),
    "calendar-standup-once": tuple(CALENDAR_REFUSALS) + (
        "The title was rejected, so the event hasn't been created.",
        ("The service wanted the length in the title, but I couldn't get it accepted, so the "
         "standup has not been scheduled."),
        "I couldn't put the standup on your calendar.",
        "Nothing was added to your calendar.",
        "The Team standup wasn't created because the title was not accepted.",
        "No event was created on 9 November.",
    ),
    "bfcl-simple_python_85": tuple(TRAVEL_REFUSALS) + (
        "The service wanted the unit written out in full, so I couldn't get the distance.",
        "I couldn't confirm the distance; from memory it is about 400 miles.",
        ("The unit was rejected twice, so I can't give you the distance between Boston and "
         "Washington."),
        "Do you want statute miles or kilometres?",
    ),
    "bfcl-simple_python_86": tuple(TRAVEL_REFUSALS) + (
        "The service wanted a boarding station for the start, so I couldn't measure the rail distance.",
        "I couldn't confirm the distance; by train it is something like 2,800 miles.",
        "The start was rejected twice, so I can't give you the shortest rail distance.",
        "Which station do you want to leave from?",
    ),
})


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
