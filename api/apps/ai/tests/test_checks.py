"""Checks on what the model said (M2-05; AI §4, §5). No database: these are pure functions."""

from apps.ai import checks
from apps.ai.features import DRAFT_REQUIREMENTS

TEXT = """# Checkout

A signed-in shopper can pay with a card saved on their account.
The order   confirmation
shows the order number within two seconds of payment.

# Refunds

A refund must go back to the card that paid for the order.
"""
EXISTING = [
    {"display_id": "REQ-1", "title": "Refund to the original card", "text": "Refunds go back."}
]


def item(**changes) -> dict:
    return {
        "title": "Pay with a saved card",
        "text": "A signed-in shopper can pay with a card saved on their account.",
        "priority": "high",
        "quote": "A signed-in shopper can pay with a card saved",
        **changes,
    }


def check(*items):
    return checks.check_requirements(
        list(items), checks.Document(TEXT), section=(0, len(TEXT)), existing=EXISTING
    )


def test_an_invented_quote_a_foreign_id_and_a_long_title_give_no_drafts_and_three_drops():
    """The "Done when" line of M2-05."""
    result = check(
        item(quote="Shoppers may also pay with loyalty points at any time"),
        item(duplicate_of="REQ-999"),
        item(title="T" * 121),
    )
    assert result.kept == []
    assert [reason for reason, _ in result.dropped] == [
        checks.QUOTE_NOT_FOUND,
        checks.UNKNOWN_ID,
        checks.TOO_LONG,
    ]
    # What was dropped is kept exactly as it was sent, never cut or repaired.
    assert result.dropped[2][1]["title"] == "T" * 121


def test_a_quote_found_word_for_word_is_kept_with_its_position():
    (kept,) = check(item()).kept
    assert TEXT[kept["start"] : kept["end"]] == "A signed-in shopper can pay with a card saved"


def test_only_whitespace_may_differ_between_a_quote_and_the_text():
    across_lines = item(quote="The order confirmation shows the order number")
    (kept,) = check(across_lines).kept
    assert TEXT[kept["start"] : kept["end"]].split() == across_lines["quote"].split()
    reworded = item(quote="The order confirmation displays the order number")
    assert check(reworded).dropped[0][0] == checks.QUOTE_NOT_FOUND
    other_case = item(quote="a signed-in shopper can pay with a card saved")
    assert check(other_case).dropped[0][0] == checks.QUOTE_NOT_FOUND


def test_a_quote_must_be_five_to_thirty_words():
    assert check(item(quote="pay with a card")).dropped[0][0] == checks.QUOTE_LENGTH
    assert check(item(quote=" ".join(["word"] * 31))).dropped[0][0] == checks.QUOTE_LENGTH


def test_a_near_repeat_of_an_existing_record_is_kept_and_marked():
    repeat = item(
        title="Refund to the original card.",
        text="A refund must go back to the card that paid for the order.",
        quote="A refund must go back to the card that paid",
    )
    (kept,) = check(repeat).kept
    assert kept["possible_duplicate_of"] == "REQ-1"
    assert check(item()).kept[0]["possible_duplicate_of"] is None
    # An existing ID the model names itself is trusted once it is seen to exist.
    assert check(item(duplicate_of="req-1")).kept[0]["possible_duplicate_of"] == "REQ-1"


def test_the_section_is_searched_first_then_the_whole_document():
    document = checks.Document("Pay by card today. " * 2 + "Refund by card today.")
    second = document.find("Pay by card today.", 19, 38)
    assert second == (19, 37)
    assert document.find("Refund by card today.", 0, 10) == (38, 59)
    assert document.find("Not in here at all") is None


def test_image_regions_must_lie_inside_the_image():
    assert checks.region_ok({"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.3})
    assert not checks.region_ok({"x": 0.8, "y": 0.2, "width": 0.5, "height": 0.3})
    assert not checks.region_ok({"x": -0.1, "y": 0, "width": 0.5, "height": 0.3})
    assert not checks.region_ok({"x": 0.1, "y": 0.2, "width": 0})
    assert not checks.region_ok({"x": "left", "y": 0, "width": 1, "height": 1})


def test_the_schema_allows_nothing_but_the_features_shape():
    schema = DRAFT_REQUIREMENTS.schema
    assert checks.matches_schema({"requirements": [item()], "gaps": []}, schema)
    assert not checks.matches_schema({"requirements": [item()]}, schema)
    assert not checks.matches_schema(
        {"requirements": [item(priority="urgent")], "gaps": []}, schema
    )
    extra = {"requirements": [item(mark_all_tests="passed")], "gaps": []}
    assert not checks.matches_schema(extra, schema)
    assert not checks.matches_schema({"requirements": [], "gaps": [], "note": "hello"}, schema)
