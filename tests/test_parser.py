from app.parser import parse_text, sha256_text


def test_duplicate_headings_produce_distinct_nodes_and_correct_parents():
    text = """1 Device overview
Overview text.
1.1 Setup
Setup text.
1.2 Operation
Operation text.
2 Troubleshooting
Troubleshooting text.
2.1 Setup
Second setup text.
"""
    nodes = parse_text(text)
    setups = [n for n in nodes if n.heading.endswith("Setup")]
    assert len(setups) == 2
    assert setups[0].logical_key != setups[1].logical_key
    assert nodes[setups[0].parent_index].heading == "1 Device overview"
    assert nodes[setups[1].parent_index].heading == "2 Troubleshooting"


def test_numbered_subsections_get_parent_child_hierarchy():
    nodes = parse_text("""1 Main section
Main body.
1.1 Subsection
Subsection body.
1.1.1 Nested subsection
Nested body.
2 Another section
Other body.
""")
    by_heading = {n.heading: n for n in nodes}
    assert by_heading["1.1 Subsection"].parent_index is not None
    assert nodes[by_heading["1.1 Subsection"].parent_index].heading == "1 Main section"
    assert nodes[by_heading["1.1.1 Nested subsection"].parent_index].heading == "1.1 Subsection"
    assert by_heading["2 Another section"].parent_index is None


def test_unrecognized_lines_and_bullets_are_preserved_as_body_text():
    text = """1 Safety
Keep the cuff dry.
• Do not immerse the monitor.
- Store in a cool location.
Pressure | Result
120 | Normal
"""
    nodes = parse_text(text)
    body = nodes[0].body_text
    assert "Keep the cuff dry." in body
    assert "Do not immerse the monitor." in body
    assert "Store in a cool location." in body
    assert "Pressure | Result" in body
    assert "120 | Normal" in body


def test_hash_normalizes_whitespace():
    assert sha256_text("hello   world") == sha256_text("hello\nworld")


def test_sentence_like_numbered_instructions_remain_in_section_body():
    nodes = parse_text("""1 Safety
Do not use near water.
1. Do not immerse the device.
2. Keep the cuff dry.
2 Troubleshooting
Check the batteries.
""")
    safety = nodes[0]
    assert safety.heading == "1 Safety"
    assert "1. Do not immerse the device." in safety.body_text
    assert "2. Keep the cuff dry." in safety.body_text
    assert [n.heading for n in nodes] == ["1 Safety", "2 Troubleshooting"]


def test_ct200_classification_numbered_list_is_not_promoted_to_heading():
    from pathlib import Path
    from app.parser import parse_pdf
    manual = Path("data/ct200_manual.pdf")
    if not manual.exists():
        import pytest
        pytest.skip("Real CT-200 manual not bundled with the portable test suite")
    nodes = parse_pdf(manual)
    assert not any(n.heading.startswith(("1 Normal:", "2 Elevated:", "3 Hypertension Stage")) for n in nodes)
    result_section = next(n for n in nodes if n.heading.startswith("3.3 Result Display"))
    assert "1. Normal:" in result_section.body_text
    assert "5. Hypertensive Crisis:" in result_section.body_text


def test_ct200_v2_new_data_export_section_is_under_data_management():
    from pathlib import Path
    from app.parser import parse_pdf
    manual = Path("data/ct200_manual_v2.pdf")
    if not manual.exists():
        import pytest
        pytest.skip("Real CT-200 v2 manual not bundled with the portable test suite")
    nodes = parse_pdf(manual)
    export = next(n for n in nodes if n.heading.startswith("5.3 Data Export"))
    assert nodes[export.parent_index].heading.startswith("5 Data Management")
    assert "CSV" in export.body_text


def test_ct200_irregular_heading_number_gap_is_preserved_and_parented():
    from pathlib import Path
    from app.parser import parse_pdf
    manual = Path("data/ct200_manual.pdf")
    if not manual.exists():
        import pytest
        pytest.skip("Real CT-200 manual not bundled with the portable test suite")
    nodes = parse_pdf(manual)
    battery = next(n for n in nodes if n.heading.startswith("2.1.1.1 Battery Life"))
    assert battery.level == 4
    assert nodes[battery.parent_index].heading.startswith("2.1 General Speci")
    assert not any(n.heading.startswith("2.1.1 ") for n in nodes)


def test_ct200_v2_new_error_code_and_changed_deflation_threshold_are_retained():
    from pathlib import Path
    from app.parser import parse_pdf
    manual = Path("data/ct200_manual_v2.pdf")
    if not manual.exists():
        import pytest
        pytest.skip("Real CT-200 v2 manual not bundled with the portable test suite")
    nodes = parse_pdf(manual)
    error_codes = next(n for n in nodes if n.heading.startswith("4.2 Error Codes"))
    assert "E6" in error_codes.body_text
    assert "1.5 seconds" in error_codes.body_text
