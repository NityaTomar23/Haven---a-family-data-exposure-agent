"""JSON extraction from model output.

Every structured stage of the pipeline depends on this helper, and a model
that wraps its JSON in prose or a markdown fence must not be treated as a
failure.
"""

from __future__ import annotations

from haven.pipeline import _extract_json


def test_plain_json_object():
    assert _extract_json('{"relevant": true, "confidence": 0.9}') == {
        "relevant": True,
        "confidence": 0.9,
    }


def test_json_with_surrounding_whitespace():
    assert _extract_json('  \n {"a": 1}  \n ') == {"a": 1}


def test_json_in_a_labelled_markdown_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_in_an_unlabelled_markdown_fence():
    assert _extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_json_after_chatty_preamble():
    assert _extract_json('Sure! Here is the result:\n{"a": 1}') == {"a": 1}


def test_json_before_trailing_commentary():
    assert _extract_json('{"a": 1}\n\nLet me know if you need more.') == {"a": 1}


def test_nested_objects_survive():
    text = 'Result: {"method": "web_form", "steps": ["one", "two"], "meta": {"n": 2}}'
    assert _extract_json(text) == {
        "method": "web_form",
        "steps": ["one", "two"],
        "meta": {"n": 2},
    }


def test_braces_inside_a_string_do_not_break_extraction():
    assert _extract_json('note {"a": "contains } brace"} tail') == {
        "a": "contains } brace"
    }


def test_unparseable_output_returns_empty_dict():
    assert _extract_json("I could not analyse this page.") == {}


def test_empty_output_returns_empty_dict():
    assert _extract_json("") == {}


def test_truncated_json_returns_empty_dict():
    assert _extract_json('{"a": 1, "b":') == {}


def test_closing_brace_before_opening_brace_returns_empty_dict():
    assert _extract_json("} then {") == {}
