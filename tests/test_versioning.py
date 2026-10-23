from app.versioning import compare_text, match_nodes
from app.parser import parse_text


def test_text_change_is_flagged_and_diff_summary_returned():
    result = compare_text("Pressure must be below 200.", "Pressure must be below 180.")
    assert result["changed"] is True
    assert result["similarity"] < 1
    assert "Text changed" in result["summary"]


def test_unchanged_text_is_not_flagged():
    result = compare_text("Use the monitor as described.", "Use the monitor as described.")
    assert result["changed"] is False
    assert result["similarity"] == 1.0


def test_unique_heading_can_be_matched_between_versions():
    old = parse_text("""1 Operation
Start the device.
2 Cleaning
Wipe the surface.
""")
    new = parse_text("""1 Operation
Start the device.
2 Cleaning
Wipe the surface carefully.
""")
    matches = match_nodes(old, new)
    assert old[0].logical_key in matches
    assert old[1].logical_key in matches
