"""Address boundary detection: explicit and inferred modes (MCC-189)."""

import time

import pytest

from verbal_code.address_itn import AddressNormalizer, looks_like_address
from verbal_code.app import _create_address_normalizer, validate_config
from verbal_code.injector import TextProcessor

# Ordinary prose containing "at", "dot" and other symbol words. Inferred mode
# must leave every one of these exactly as it is: mangling prose is worse
# than missing an address.
FALSE_POSITIVE_PROSE = [
    "I'll meet you at the dot on the map",
    "look at that",
    "we land at eight",
    "compute the dot product",
    "the dot com bubble burst",
    "connect the dots at the end",
    "she smiled at me",
    "we met at noon",
    "the meeting is at three thirty",
    "at that point we gave up",
    "look at the dot matrix printer",
    "I'm at home",
    "he works at the bank dot",
    "stay at the hotel",
    "arrive at the airport at seven",
    "at least two of them",
    "put a dot over the i",
    "the period ended at five",
    "use a colon here",
    "slash the budget at once",
    "two plus two is four",
    "point at the screen",
    "we arrived at a decision",
    "the dash at the end of the line",
    "at the end of the day",
    "the dot net framework",
    "she's at work dot",
    "Ryan is at lunch.",
    "Look at that, dot com.",
    "the cat sat at the mat",
    "we have two dot com companies",
    "version 2 dot 1 is out",
    "meet at 5 dot com",
]


@pytest.fixture
def inferred():
    return AddressNormalizer(explicit=False, inferred=True)


@pytest.fixture
def explicit():
    return AddressNormalizer(explicit=True, inferred=False)


class TestFalsePositives:
    @pytest.mark.parametrize("prose", FALSE_POSITIVE_PROSE)
    def test_prose_is_unchanged(self, prose):
        assert AddressNormalizer().normalize(prose) == prose

    @pytest.mark.parametrize("prose", FALSE_POSITIVE_PROSE)
    def test_prose_survives_the_whole_pipeline(self, prose):
        expected = TextProcessor().process(prose)
        assert TextProcessor().process(AddressNormalizer().normalize(prose)) == expected


class TestInferredMode:
    def test_converts_the_second_at_and_stops_before_and(self, inferred):
        assert inferred.normalize(
            "email me at ryan at liatrio dot com and I'll reply"
        ) == "email me at ryan@liatrio.com and I'll reply"

    @pytest.mark.parametrize(
        ("spoken", "written"),
        [
            ("ryan at liatrio dot com", "ryan@liatrio.com"),
            ("jane dot doe at example dot com", "jane.doe@example.com"),
            ("support at example dot co dot uk", "support@example.co.uk"),
            ("www dot liatrio dot com", "www.liatrio.com"),
            ("www liatrio dot com", "www.liatrio.com"),
            (
                "https colon slash slash github dot com slash anthropics",
                "https://github.com/anthropics",
            ),
            ("github dot com slash anthropics", "github.com/anthropics"),
            ("my site is example dot dev", "my site is example.dev"),
            (
                "http colon slash slash localhost colon 8080 slash api",
                "http://localhost:8080/api",
            ),
            ("ryan plus spam at gmail dot com", "ryan+spam@gmail.com"),
            ("jane underscore doe at example dot io", "jane_doe@example.io"),
        ],
    )
    def test_spoken_address(self, inferred, spoken, written):
        assert inferred.normalize(spoken) == written

    @pytest.mark.parametrize(
        ("parakeet", "written"),
        [
            # Real Parakeet output from the MCC-188 spike.
            ("Ryan at Liatrill.com", "ryan@liatrill.com"),
            (
                "Email me at ryan at lyatrillo.com, and I'll reply.",
                "Email me at ryan@lyatrillo.com, and I'll reply.",
            ),
            ("Ryan.mclish at liatreal.com", "ryan.mclish@liatreal.com"),
            ("Support at example.co.uk", "support@example.co.uk"),
            ("Check github.com slash anthropics.", "Check github.com/anthropics."),
            (
                "Visit http colon slash slash localhost colon 8080 slash api",
                "Visit http://localhost:8080/api",
            ),
        ],
    )
    def test_engine_output(self, inferred, parakeet, written):
        assert inferred.normalize(parakeet) == written

    def test_function_word_before_at_is_not_a_local_part(self, inferred):
        assert inferred.normalize("look at google dot com") == "look at google.com"
        assert inferred.normalize("I work at liatrio dot com") == (
            "I work at liatrio.com"
        )

    def test_punctuation_ends_a_span(self, inferred):
        assert inferred.normalize("ryan, at liatrio dot com") == (
            "ryan, at liatrio.com"
        )

    def test_sentence_period_is_kept(self, inferred):
        assert inferred.normalize("write to ryan at liatrio dot com.") == (
            "write to ryan@liatrio.com."
        )

    def test_unknown_tld_is_not_inferred(self, inferred):
        assert inferred.normalize("ryan at liatrio dot zz") == "ryan at liatrio dot zz"

    def test_extra_tlds_extend_the_list(self):
        normalizer = AddressNormalizer(inferred=True, extra_tlds=[".zz"])
        assert normalizer.normalize("ryan at liatrio dot zz") == "ryan@liatrio.zz"

    def test_point_and_period_do_not_join_labels(self, inferred):
        assert inferred.normalize("ryan at liatrio point com") == (
            "ryan at liatrio point com"
        )

    def test_two_addresses_in_one_dictation(self, inferred):
        assert inferred.normalize(
            "cc ryan at liatrio dot com and jane at example dot org"
        ) == "cc ryan@liatrio.com and jane@example.org"


class TestExplicitMode:
    def test_converts_only_the_span(self, explicit):
        assert explicit.normalize(
            "send it to begin address jane at example dot io finish address "
            "at noon"
        ) == "send it to jane@example.io at noon"

    def test_ends_at_end_of_dictation(self, explicit):
        assert explicit.normalize("begin address ryan at liatrio dot com") == (
            "ryan@liatrio.com"
        )

    def test_misheard_terminator_still_ends_the_span(self, explicit):
        # Parakeet heard "end address" as "and address" in the MCC-188 spike.
        assert explicit.normalize(
            "Begin address ryan at cliotreal.com and address."
        ) == "ryan@cliotreal.com."

    def test_keeps_punctuation_after_the_terminator(self, explicit):
        assert explicit.normalize(
            "Begin address, ryan at liatrio dot com, finish address, thanks."
        ) == "ryan@liatrio.com, thanks."

    def test_period_and_point_count_inside_the_span(self, explicit):
        assert explicit.normalize(
            "begin address ryan period mcclish at liatrio point com end address"
        ) == "ryan.mcclish@liatrio.com"

    def test_accepts_a_short_unlisted_tld(self, explicit):
        assert explicit.normalize("begin address ryan at liatrio dot zz") == (
            "ryan@liatrio.zz"
        )

    def test_invalid_span_falls_through_as_spoken_text(self, explicit, caplog):
        with caplog.at_level("INFO", logger="verbal_code"):
            result = explicit.normalize(
                "begin address ryan at at liatrio finish address ok"
            )
        assert result == "ryan at at liatrio ok"
        assert "failed validation" in caplog.text

    def test_empty_span_just_drops_the_phrases(self, explicit):
        assert explicit.normalize("begin address finish address hello") == "hello"

    def test_prose_outside_the_span_is_not_inferred_when_disabled(self, explicit):
        assert explicit.normalize("ryan at liatrio dot com") == (
            "ryan at liatrio dot com"
        )

    def test_custom_phrases(self):
        normalizer = AddressNormalizer(
            begin_phrases=["email mode"], end_phrases=["email done"], inferred=False
        )
        assert normalizer.normalize(
            "email mode ryan at liatrio dot com email done ok"
        ) == "ryan@liatrio.com ok"

    def test_begin_phrase_is_not_fuzzy(self, explicit):
        text = "begins addresses ryan at liatrio dot com"
        assert explicit.normalize(text) == text


class TestModesCombined:
    def test_explicit_output_is_not_reprocessed(self):
        normalizer = AddressNormalizer()
        assert normalizer.normalize(
            "begin address ryan at liatrio dot com finish address or "
            "jane at example dot org"
        ) == "ryan@liatrio.com or jane@example.org"

    def test_both_modes_off_is_a_no_op(self):
        normalizer = AddressNormalizer(explicit=False, inferred=False)
        text = "begin address ryan at liatrio dot com"
        assert normalizer.normalize(text) == text


class TestCapitalisationGuard:
    def test_address_at_start_of_dictation_stays_lowercase(self):
        processed = TextProcessor().process(
            AddressNormalizer().normalize("Ryan at Liatrill.com")
        )
        assert processed == "ryan@liatrill.com "

    def test_address_after_a_sentence_stays_lowercase(self):
        assert TextProcessor().process("done. www.liatrio.com is up") == (
            "Done. www.liatrio.com is up "
        )

    def test_ordinary_sentence_start_is_still_capitalised(self):
        assert TextProcessor().process("done. next one") == "Done. Next one "

    @pytest.mark.parametrize(
        "word", ["ryan@liatrio.com", "https://x.io", "www.a.com", "liatrio.com,"]
    )
    def test_looks_like_address(self, word):
        assert looks_like_address(word)

    @pytest.mark.parametrize("word", ["e.g.", "i.e.", "hello", "Liatrio.com", "U.S."])
    def test_does_not_look_like_address(self, word):
        assert not looks_like_address(word)


class TestConfig:
    def test_disabled_builds_no_normalizer(self):
        assert _create_address_normalizer({"address": {"enabled": False}}) is None

    def test_defaults_enable_both_modes(self):
        normalizer = _create_address_normalizer({})
        assert normalizer.explicit and normalizer.inferred

    def test_inferred_can_be_disabled_alone(self):
        normalizer = _create_address_normalizer({"address": {"inferred": False}})
        assert normalizer.explicit and not normalizer.inferred

    @pytest.mark.parametrize(
        "address",
        [
            {"inferred": "yes"},
            {"begin_phrases": "begin address"},
            {"end_phrases": [""]},
            {"extra_tlds": ["c0m"]},
            "on",
        ],
    )
    def test_bad_values_fail_fast(self, address):
        config = {"hotkey": {}, "stt": {"engine": "parakeet"}, "audio": {}}
        config["address"] = address
        with pytest.raises(SystemExit):
            validate_config(config)

    def test_valid_section_passes(self):
        validate_config(
            {
                "hotkey": {},
                "stt": {"engine": "parakeet"},
                "audio": {},
                "address": {
                    "enabled": True,
                    "explicit": True,
                    "inferred": False,
                    "begin_phrases": ["begin address"],
                    "end_phrases": ["finish address"],
                    "extra_tlds": ["zz", ".rs"],
                },
            }
        )


class TestLatency:
    def test_normalizing_a_long_dictation_is_fast(self):
        # MCC-30's release-to-text budget is hundreds of ms; this pass must
        # cost well under a millisecond per typical dictation.
        text = " ".join(FALSE_POSITIVE_PROSE) + " email ryan at liatrio dot com"
        normalizer = AddressNormalizer()
        start = time.perf_counter()
        for _ in range(100):
            normalizer.normalize(text)
        per_call_ms = (time.perf_counter() - start) * 10
        assert per_call_ms < 20
