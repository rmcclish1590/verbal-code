"""Applying dictionary corrections to transcribed text (MCC-55)."""

from verbal_code.dictionary import DictionaryStore
from verbal_code.dictionary_corrector import DictionaryCorrector


def _store(tmp_path):
    return DictionaryStore(str(tmp_path / "dictionary.json"))


class TestNoOp:
    def test_empty_dictionary_leaves_text_untouched(self, tmp_path):
        corrector = DictionaryCorrector(_store(tmp_path))

        assert corrector.correct("hello world") == "hello world"

    def test_empty_text_is_returned_as_is(self, tmp_path):
        store = _store(tmp_path)
        store.add("EnGen")
        corrector = DictionaryCorrector(store)

        assert corrector.correct("") == ""

    def test_disabled_entries_are_skipped(self, tmp_path):
        store = _store(tmp_path)
        store.add("EnGen", enabled=False)
        corrector = DictionaryCorrector(store)

        assert corrector.correct("I use engen daily") == "I use engen daily"


class TestExactVariantMatch:
    def test_known_variant_is_replaced_with_canonical_term(self, tmp_path):
        store = _store(tmp_path)
        store.add("EnGen", variants=["engine gen", "en gen"])
        corrector = DictionaryCorrector(store)

        assert corrector.correct("open en gen now") == "open EnGen now"

    def test_case_insensitive_term_match_gets_canonical_casing(self, tmp_path):
        store = _store(tmp_path)
        store.add("MCP")
        corrector = DictionaryCorrector(store)

        assert corrector.correct("the mcp server") == "the MCP server"

    def test_multi_word_phrase_is_replaced(self, tmp_path):
        store = _store(tmp_path)
        store.add("Verbal Code", variants=["verbal cod"])
        corrector = DictionaryCorrector(store)

        assert (
            corrector.correct("I built verbal cod last week")
            == "I built Verbal Code last week"
        )


class TestFuzzyMatch:
    def test_close_misspelling_is_corrected(self, tmp_path):
        store = _store(tmp_path)
        store.add("Anthropic")
        corrector = DictionaryCorrector(store)

        assert corrector.correct("we work at anthropik") == "we work at Anthropic"

    def test_unrelated_word_is_not_corrected(self, tmp_path):
        store = _store(tmp_path)
        store.add("Anthropic")
        corrector = DictionaryCorrector(store)

        assert corrector.correct("the weather is nice") == "the weather is nice"

    def test_short_words_are_not_fuzzy_matched(self, tmp_path):
        store = _store(tmp_path)
        store.add("MCP")
        corrector = DictionaryCorrector(store)

        # "map" is a plausible whisper mishearing distance-wise but is a
        # real, common word — the length floor keeps it from being clobbered.
        assert corrector.correct("look at the map") == "look at the map"


class TestPunctuationAndSpacingPreserved:
    def test_surrounding_punctuation_and_spacing_survive(self, tmp_path):
        store = _store(tmp_path)
        store.add("EnGen")
        corrector = DictionaryCorrector(store)

        assert (
            corrector.correct("Hello, engen!  How are you?")
            == "Hello, EnGen!  How are you?"
        )

    def test_phrase_is_not_matched_across_a_sentence_boundary(self, tmp_path):
        store = _store(tmp_path)
        store.add("Verbal Code")
        corrector = DictionaryCorrector(store)

        text = "I said verbal. Code review is next."
        assert corrector.correct(text) == text


class TestThreshold:
    def test_custom_threshold_is_respected(self, tmp_path):
        store = _store(tmp_path)
        store.add("Anthropic")
        strict = DictionaryCorrector(store, fuzzy_threshold=0.99)

        assert strict.correct("we work at anthropik") == "we work at anthropik"


class TestPhraseFuzzyMatching:
    def test_fuzzy_phrase_does_not_swallow_a_neighbouring_word(self, tmp_path):
        # A 3-word variant raises the n-gram length. "at liatrio" is close
        # enough to "liatrio" to pass the threshold, but the "at" must survive.
        store = _store(tmp_path)
        store.add("Liatrio", variants=["lee at treo"])
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at liatrio dot com") == (
            "ryan at Liatrio dot com"
        )


class TestAddressTerms:
    """MCC-192: entries flagged ``address`` next to an address."""

    def test_split_domain_variant_collapses_to_one_token(self, tmp_path):
        store = _store(tmp_path)
        store.add("Liatrio", variants=["lee at treo"], address=True)
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at lee at treo dot com") == (
            "ryan at liatrio dot com"
        )

    def test_unspaced_match_next_to_an_address(self, tmp_path):
        store = _store(tmp_path)
        store.add("liatrio", address=True)
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at lia trio dot com") == (
            "ryan at liatrio dot com"
        )

    def test_unspaced_fuzzy_match_only_next_to_an_address(self, tmp_path):
        store = _store(tmp_path)
        store.add("liatrio", address=True)
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at lia treo dot com") == (
            "ryan at liatrio dot com"
        )
        assert corrector.correct("the lia treo is great") == "the lia treo is great"

    def test_domain_stuck_to_its_tld_counts_as_an_address(self, tmp_path):
        store = _store(tmp_path)
        store.add("liatrio", address=True)
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at lia treo.com") == "ryan at liatrio.com"

    def test_emitted_lowercase_and_unspaced_in_an_address(self, tmp_path):
        store = _store(tmp_path)
        store.add("Lia Trio", address=True)
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at lia trio dot com") == (
            "ryan at liatrio dot com"
        )
        assert corrector.correct("I like lia trio a lot") == "I like Lia Trio a lot"

    def test_join_never_swallows_a_symbol_word(self, tmp_path):
        store = _store(tmp_path)
        store.add("liatrio", address=True)
        corrector = DictionaryCorrector(store)

        # "lia trio dot" -> "liatriodot" is fuzzy-close to "liatrio".
        assert corrector.correct("ryan at lia trio dot com") == (
            "ryan at liatrio dot com"
        )

    def test_address_terms_are_preferred_next_to_an_address(self, tmp_path):
        store = _store(tmp_path)
        store.add("liatrio", address=True)
        store.add("Liatrion")  # closer to "liatrin" than "liatrio" is
        corrector = DictionaryCorrector(store)

        assert corrector.correct("ryan at liatrin dot com") == (
            "ryan at liatrio dot com"
        )
        assert corrector.correct("I said liatrin") == "I said Liatrion"
