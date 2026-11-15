"""Letter-by-letter and phonetic-alphabet spelling in addresses (MCC-191)."""

import pytest

from verbal_code import address_itn
from verbal_code.address_itn import AddressNormalizer, convert_span


@pytest.fixture
def normalizer():
    return AddressNormalizer()


class TestAcceptanceCriteria:
    @pytest.mark.parametrize(
        ("spoken", "written"),
        [
            ("r y a n at liatrio dot com", "ryan@liatrio.com"),
            ("romeo yankee alfa november at liatrio dot com", "ryan@liatrio.com"),
            ("ryan at l i a t r i o dot com", "ryan@liatrio.com"),
        ],
    )
    def test_inferred(self, normalizer, spoken, written):
        assert normalizer.normalize(spoken) == written

    def test_letter_run_with_digits(self):
        assert convert_span("k two f s a dot dev") == "k2fsa.dev"

    def test_spelling_is_inactive_outside_a_span(self, normalizer):
        assert normalizer.normalize("I think a b c is easy") == (
            "I think a b c is easy"
        )

    def test_phonetic_table_is_data(self, monkeypatch):
        monkeypatch.setitem(address_itn.NATO_ALPHABET, "rho", "r")
        assert convert_span("rho yankee alpha november at liatrio dot com") == (
            "ryan@liatrio.com"
        )


class TestEngineForms:
    def test_parakeet_hyphenated_letters(self, normalizer):
        # Parakeet's output for "r y a n at liatrio dot com" in the spike.
        assert normalizer.normalize("R-Y-N at Liatrill.com") == "ryn@liatrill.com"

    def test_letters_with_periods(self, normalizer):
        assert normalizer.normalize("R. Y. A. N. at liatrio dot com.") == (
            "ryan@liatrio.com."
        )

    def test_parakeet_alpha_spelling(self, normalizer):
        assert normalizer.normalize("Romeo Yankee Alpha November at Liatrio.com") == (
            "ryan@liatrio.com"
        )

    def test_spelled_protocol_and_path(self, normalizer):
        assert normalizer.normalize(
            "h t t p s colon slash slash github dot com slash k two dash f s a"
        ) == "https://github.com/k2-fsa"

    def test_spelled_www(self, normalizer):
        assert normalizer.normalize("w w w dot example dot com") == "www.example.com"


class TestSpellingForms:
    def test_as_in(self, normalizer):
        assert normalizer.normalize("b as in bravo o b at example dot io") == (
            "bob@example.io"
        )

    def test_as_in_needs_a_matching_word(self):
        # "b as in delta" isn't disambiguation, so the words stay words.
        assert convert_span("b as in delta at example dot io") == (
            "basindelta@example.io"
        )

    def test_capital_letter_in_a_path(self):
        assert convert_span("github dot com slash capital r e a d m e") == (
            "github.com/Readme"
        )

    def test_capital_phonetic_word(self):
        assert convert_span("example dot com slash cap romeo two") == (
            "example.com/R2"
        )

    def test_capital_never_reaches_the_host(self):
        assert convert_span("ryan at capital l i a t r i o dot com") == (
            "ryan@liatrio.com"
        )

    def test_capital_in_local_part_is_kept(self):
        assert convert_span("capital r y a n at liatrio dot com") == (
            "Ryan@liatrio.com"
        )

    def test_capital_without_a_letter_is_a_word(self):
        assert convert_span("capital one at example dot com") == (
            "capital1@example.com"
        )

    def test_lone_phonetic_word_is_a_name(self, normalizer):
        # "victor" alone is far likelier to be Victor than the letter v.
        assert normalizer.normalize("victor at example dot com") == (
            "victor@example.com"
        )

    def test_two_phonetic_words_spell(self, normalizer):
        assert normalizer.normalize("victor charlie at example dot com") == (
            "vc@example.com"
        )

    def test_spelling_stops_at_a_multi_letter_word(self, normalizer):
        assert normalizer.normalize("send it to r y a n at gmail dot com please") == (
            "send it to ryan@gmail.com please"
        )

    def test_explicit_mode_spells_too(self, normalizer):
        assert normalizer.normalize(
            "begin address m c c l i s h at liatrio dot com finish address"
        ) == "mcclish@liatrio.com"
