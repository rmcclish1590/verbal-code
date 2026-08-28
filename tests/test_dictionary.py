"""Persisted custom-term store (MCC-54): CRUD, case rules, and persistence."""

import json
import os

import pytest

from verbal_code.dictionary import DictionaryEntry, DictionaryStore


class TestEmptyStore:
    def test_missing_file_starts_empty(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))

        assert store.entries == []

    def test_missing_file_is_not_created_until_a_write(self, tmp_path):
        path = tmp_path / "dictionary.json"
        DictionaryStore(str(path))

        assert not path.exists()


class TestAdd:
    def test_add_persists_a_case_preserving_entry(self, tmp_path):
        path = tmp_path / "dictionary.json"
        store = DictionaryStore(str(path))

        entry = store.add("EnGen", variants=["engine", "en gen"])

        assert entry.term == "EnGen"
        assert entry.source == "manual"
        assert entry.enabled is True
        assert entry.created_at == entry.updated_at

        reloaded = DictionaryStore(str(path))
        assert [e.term for e in reloaded.entries] == ["EnGen"]
        assert reloaded.entries[0].variants == ["engine", "en gen"]

    def test_add_rejects_a_case_insensitive_duplicate(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("MCP")

        with pytest.raises(ValueError):
            store.add("mcp")

    def test_add_defaults_to_no_variants(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))

        entry = store.add("Anthropic")

        assert entry.variants == []


class TestUpdate:
    def test_update_replaces_variants_and_bumps_timestamp(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        original = store.add("EnGen", variants=["engine"])

        updated = store.update("engen", variants=["engine", "en-gen"])

        assert updated.variants == ["engine", "en-gen"]
        assert updated.updated_at >= original.created_at
        assert updated.term == "EnGen"  # canonical casing untouched

    def test_update_can_disable_an_entry(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("EnGen")

        updated = store.update("EnGen", enabled=False)

        assert updated.enabled is False

    def test_update_missing_term_raises(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))

        with pytest.raises(KeyError):
            store.update("nope")


class TestDelete:
    def test_delete_removes_the_entry(self, tmp_path):
        path = tmp_path / "dictionary.json"
        store = DictionaryStore(str(path))
        store.add("EnGen")

        store.delete("engen")

        assert store.entries == []
        assert DictionaryStore(str(path)).entries == []

    def test_delete_missing_term_raises(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))

        with pytest.raises(KeyError):
            store.delete("nope")


class TestLookup:
    def test_lookup_matches_the_term_case_insensitively(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("EnGen")

        assert store.lookup("engen").term == "EnGen"
        assert store.lookup("ENGEN").term == "EnGen"

    def test_lookup_matches_a_variant(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("EnGen", variants=["engine", "en gen"])

        assert store.lookup("en gen").term == "EnGen"
        assert store.lookup("Engine").term == "EnGen"

    def test_lookup_supports_multi_word_phrases(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("Verbal Code", variants=["verbal cod"])

        assert store.lookup("verbal code").term == "Verbal Code"
        assert store.lookup("Verbal Cod").term == "Verbal Code"

    def test_lookup_returns_none_when_no_match(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("EnGen")

        assert store.lookup("unrelated") is None


class TestPersistenceHygiene:
    def test_write_leaves_no_temp_files(self, tmp_path):
        path = tmp_path / "dictionary.json"
        store = DictionaryStore(str(path))

        store.add("EnGen")

        assert os.listdir(tmp_path) == ["dictionary.json"]

    def test_file_is_valid_json_with_entries_key(self, tmp_path):
        path = tmp_path / "dictionary.json"
        store = DictionaryStore(str(path))
        store.add("EnGen", source="auto-learned", enabled=False)

        with open(path) as f:
            raw = json.load(f)

        assert raw["entries"][0]["term"] == "EnGen"
        assert raw["entries"][0]["source"] == "auto-learned"
        assert raw["entries"][0]["enabled"] is False

    def test_entries_are_sorted_case_insensitively_by_term(self, tmp_path):
        store = DictionaryStore(str(tmp_path / "dictionary.json"))
        store.add("zeta")
        store.add("Alpha")

        assert [e.term for e in store.entries] == ["Alpha", "zeta"]


class TestDictionaryEntryMatches:
    def test_matches_term_and_variants_case_insensitively(self):
        entry = DictionaryEntry(term="EnGen", variants=["engine"])

        assert entry.matches("engen")
        assert entry.matches("Engine")
        assert not entry.matches("unrelated")
