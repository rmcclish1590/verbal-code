"""Pure-logic tests for the dictionary management window (MCC-57).

Follows the pattern in test_hotkey_editor.py: GTK widget construction isn't
exercised (no display in CI), only the plain functions the window's
callbacks delegate to.
"""

from verbal_code.dictionary import DictionaryEntry
from verbal_code.dictionary_editor import (
    _filter_entries,
    _format_variants,
    _parse_variants,
    _source_label,
)


def _entry(term, variants=None, source="manual", enabled=True):
    return DictionaryEntry(
        term=term, variants=variants or [], source=source, enabled=enabled
    )


class TestFilterEntries:
    def test_empty_query_returns_all_entries(self):
        entries = [_entry("EnGen"), _entry("MCP")]

        assert _filter_entries(entries, "") == entries

    def test_matches_term_case_insensitively(self):
        entries = [_entry("EnGen"), _entry("MCP")]

        assert _filter_entries(entries, "engen") == [entries[0]]

    def test_matches_a_variant(self):
        entries = [_entry("EnGen", variants=["engine gen"]), _entry("MCP")]

        assert _filter_entries(entries, "engine") == [entries[0]]

    def test_no_match_returns_empty_list(self):
        entries = [_entry("EnGen")]

        assert _filter_entries(entries, "nope") == []


class TestVariantsFormatting:
    def test_format_joins_with_comma_space(self):
        assert _format_variants(["engine", "en gen"]) == "engine, en gen"

    def test_format_empty_list_is_empty_string(self):
        assert _format_variants([]) == ""

    def test_parse_splits_and_strips(self):
        assert _parse_variants(" engine , en gen ,") == ["engine", "en gen"]

    def test_parse_empty_string_is_empty_list(self):
        assert _parse_variants("") == []

    def test_round_trip(self):
        variants = ["engine", "en gen"]
        assert _parse_variants(_format_variants(variants)) == variants


class TestSourceLabel:
    def test_manual_source_is_shown_plain(self):
        assert _source_label(_entry("EnGen", source="manual")) == "manual"

    def test_auto_learned_source_gets_a_marker(self):
        label = _source_label(_entry("EnGen", source="auto-learned"))
        assert "auto-learned" in label
        assert "✨" in label
