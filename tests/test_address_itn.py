"""Spoken-to-written address grammar (MCC-190)."""

import pytest

from verbal_code import address_itn
from verbal_code.address_itn import (
    assemble,
    convert_span,
    is_valid_address,
    is_valid_email,
    is_valid_url,
    tokenize,
)


class TestAcceptanceCriteria:
    @pytest.mark.parametrize(
        ("spoken", "written"),
        [
            ("ryan at liatrio dot com", "ryan@liatrio.com"),
            ("ryan dot mcclish at liatrio dot com", "ryan.mcclish@liatrio.com"),
            ("www dot liatrio dot com", "www.liatrio.com"),
            (
                "h t t p s colon slash slash github dot com slash k two dash f s a",
                "https://github.com/k2-fsa",
            ),
            ("support at example dot co dot uk", "support@example.co.uk"),
        ],
    )
    def test_spoken_address_converts(self, spoken, written):
        assert convert_span(spoken) == written


class TestSymbolTable:
    @pytest.mark.parametrize(
        ("word", "symbol"),
        [
            ("at", "@"),
            ("dot", "."),
            ("period", "."),
            ("point", "."),
            ("dash", "-"),
            ("hyphen", "-"),
            ("minus", "-"),
            ("underscore", "_"),
            ("slash", "/"),
            ("plus", "+"),
            ("colon", ":"),
        ],
    )
    def test_every_mapped_word_assembles_to_its_symbol(self, word, symbol):
        assert assemble(tokenize(f"a {word} b")) == f"a{symbol}b"

    def test_forward_slash_is_one_symbol(self):
        assert convert_span("example dot com forward slash docs") == (
            "example.com/docs"
        )

    def test_mapping_is_data(self, monkeypatch):
        # A new entry needs no logic change.
        monkeypatch.setitem(address_itn.SYMBOL_WORDS, "tilde", "~")
        assert convert_span("example dot com slash tilde ryan") == (
            "example.com/~ryan"
        )


class TestAssembly:
    def test_lowercases_asr_capitalisation(self):
        assert convert_span("Ryan at Liatrio dot COM") == "ryan@liatrio.com"

    def test_accepts_tokens_the_engine_already_normalised(self):
        # Parakeet writes "dot com" as ".com" but leaves "at" as a word.
        assert convert_span("Ryan.mclish at Liatrio.com") == "ryan.mclish@liatrio.com"

    def test_www_without_a_spoken_dot(self):
        assert convert_span("www liatrio dot com") == "www.liatrio.com"

    def test_word_protocol(self):
        assert convert_span("https colon slash slash github dot com") == (
            "https://github.com"
        )

    def test_spoken_digits_collapse(self):
        assert convert_span(
            "http colon slash slash localhost colon eight zero eight zero slash api"
        ) == "http://localhost:8080/api"

    def test_engine_digits_pass_through(self):
        assert convert_span("http colon slash slash localhost colon 8080") == (
            "http://localhost:8080"
        )

    def test_surrounding_punctuation_is_dropped(self):
        assert convert_span("ryan, at liatrio dot com.") == "ryan@liatrio.com"

    def test_underscore_and_plus_in_local_part(self):
        assert convert_span("jane underscore doe plus spam at example dot io") == (
            "jane_doe+spam@example.io"
        )


class TestValidationFallsThrough:
    @pytest.mark.parametrize(
        "spoken",
        [
            "ryan at at liatrio dot com",  # two @
            "ryan at liatrio at example dot com",  # two @
            "at liatrio dot com",  # empty local part
            "dot ryan at liatrio dot com",  # leading dot
            "ryan dot at liatrio dot com",  # dot before @
            "ryan at liatrio dot com dot",  # trailing dot
            "ryan at liatrio",  # no TLD
            "just some words",
            "ryan at liatrio dot comandaddress",  # run-on TLD
            "localhost colon eight zero",  # localhost needs a protocol
        ],
    )
    def test_invalid_span_returns_none(self, spoken):
        assert convert_span(spoken) is None


class TestValidators:
    def test_email_rejects_double_dot(self):
        assert not is_valid_email("ryan..m@liatrio.com")

    def test_url_with_port_and_path(self):
        assert is_valid_url("https://example.com:8443/a/b-c_d.html")

    def test_bare_domain_is_a_url(self):
        assert is_valid_url("liatrio.com")

    def test_ip_needs_a_scheme(self):
        assert is_valid_url("http://127.0.0.1:8000")
        assert not is_valid_url("127.0.0.1")

    def test_tld_restriction(self):
        assert is_valid_address("ryan@liatrio.com", tlds={"com"})
        assert not is_valid_address("ryan@liatrio.zz", tlds={"com"})

    def test_explicit_mode_accepts_short_unlisted_tld(self):
        assert is_valid_address("ryan@liatrio.zz")


class TestFailureLogging:
    def test_failed_span_is_logged_without_its_content(self, caplog):
        with caplog.at_level("INFO", logger="verbal_code"):
            assert convert_span("secret at words") is None
        assert "failed validation" in caplog.text
        assert "secret" not in caplog.text
