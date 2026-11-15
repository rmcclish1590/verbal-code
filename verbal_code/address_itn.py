"""Inverse text normalization for email addresses and URLs (MCC-188).

ASR engines emit the *spoken* form of an address ("ryan at liatrio dot com");
this module turns it back into the *written* form (``ryan@liatrio.com``). In
ITN terms, these are the "electronic" semiotic class.

This module holds the grammar (MCC-190): the spoken-word → symbol tables,
span assembly (map the words, close up the whitespace, lowercase) and the
validators that decide whether the assembled text really is an address.
Deciding *which* part of a transcript is an address is a separate problem.

The engine already does part of the job. Parakeet writes "dot com" as
``.com`` and digits as ``8080``, but it leaves "at", "slash", "colon" and
"underscore" as words. So every rule here also accepts input that is
already normalized: ``liatrill.com``, ``k2-fsa.dev``, ``Ryan.mclish``.

Pure Python with no dependencies. A WFST grammar (Pynini) is the scale-up
path if the rule set outgrows readable code.
"""

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

logger = logging.getLogger("verbal_code")

# --- Data tables -----------------------------------------------------------
# Edit these to change the grammar; the logic below only reads them.

# Single spoken word -> written symbol.
SYMBOL_WORDS: dict[str, str] = {
    "at": "@",
    "dot": ".",
    "period": ".",
    "point": ".",
    "dash": "-",
    "hyphen": "-",
    "minus": "-",
    "underscore": "_",
    "slash": "/",
    "plus": "+",
    "colon": ":",
}

# Multi-word spoken symbols, matched before the single words above.
MULTIWORD_SYMBOLS: dict[tuple[str, ...], str] = {
    ("forward", "slash"): "/",
    ("at", "sign"): "@",
}

DIGIT_WORDS: dict[str, str] = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

# TLDs recognised without an explicit "begin address". This list deliberately
# leaves out TLDs that are also common English words ("in", "is", "it", "me",
# "us", "to", "at", "be", "so", "no", "my", "go"), because "... dot in"
# or "... dot it" turns up in ordinary speech. Users add their own with
# ``address.extra_tlds``.
KNOWN_TLDS: frozenset[str] = frozenset(
    {
        "com", "net", "org", "edu", "gov", "mil", "int",
        "io", "dev", "sh", "ai", "app", "co", "uk", "ca", "de", "fr", "nl",
        "jp", "au", "nz", "eu", "ch", "se", "ie", "es", "pl", "br", "cn",
        "ru", "ly", "gg", "fm", "tv", "cc", "info", "biz", "tech", "xyz",
        "cloud", "online", "site",
    }
)  # fmt: skip

# Inside an explicit span, an unlisted TLD is accepted when it is plausibly
# short. This catches typos in the list without accepting a run-on such as
# "comandaddress".
_MAX_UNLISTED_TLD_LEN = 6

# Punctuation the ASR engine attaches to a word ("com.", "Ryan,", "(www").
_LEADING_PUNCT = "\"'([{<"
_TRAILING_PUNCT = ".,;:!?\"')]}>"


@dataclass(frozen=True)
class Token:
    """One whitespace-delimited word with its position in the source text.

    ``core`` is the lowercase word with surrounding punctuation stripped.
    ``lead`` and ``trail`` hold that punctuation, so a caller can tell a
    sentence break ("com.") from an address-internal dot ("liatrio.com").
    """

    text: str
    start: int
    end: int
    core: str
    lead: str
    trail: str

    @property
    def core_end(self) -> int:
        """Offset just past the core, before any trailing punctuation."""
        return self.end - len(self.trail)


def tokenize(text: str) -> list[Token]:
    tokens = []
    for match in re.finditer(r"\S+", text):
        word = match.group()
        stripped = word.lstrip(_LEADING_PUNCT)
        lead = word[: len(word) - len(stripped)]
        core = stripped.rstrip(_TRAILING_PUNCT)
        trail = stripped[len(core) :]
        tokens.append(
            Token(word, match.start(), match.end(), core.lower(), lead, trail)
        )
    return tokens


# --- Assembly --------------------------------------------------------------


def _match_multiword_symbol(tokens: Sequence[Token], i: int) -> tuple[str, int]:
    """Return (symbol, token count) for a multi-word symbol at ``i``, else ("", 0)."""
    for words, symbol in MULTIWORD_SYMBOLS.items():
        window = tokens[i : i + len(words)]
        if tuple(t.core for t in window) == words:
            return symbol, len(words)
    return "", 0


def assemble(tokens: Sequence[Token]) -> str:
    """Map a span's spoken words to written form and close up the whitespace.

    Symbol and digit words become their symbols. Every other word is kept
    and lowercased, together with any internal punctuation it already has
    (``liatrio.com``). Punctuation around a word is dropped, so the caller
    has to decide what to do with a sentence-final period. No validation
    happens here; see :func:`is_valid_address`.
    """
    pieces: list[str] = []
    i = 0
    while i < len(tokens):
        symbol, consumed = _match_multiword_symbol(tokens, i)
        if consumed:
            pieces.append(symbol)
            i += consumed
            continue
        core = tokens[i].core
        pieces.append(SYMBOL_WORDS.get(core) or DIGIT_WORDS.get(core) or core)
        i += 1
    return _join_pieces(pieces)


def _join_pieces(pieces: list[str]) -> str:
    """Join with no spaces, inserting the dot a spoken "www" usually omits."""
    out = ""
    for k, piece in enumerate(pieces):
        out += piece
        nxt = pieces[k + 1] if k + 1 < len(pieces) else ""
        if piece == "www" and nxt and not nxt.startswith("."):
            out += "."
    return out


# --- Validation ------------------------------------------------------------

_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_HOST_NAME = re.compile(rf"(?:{_LABEL}\.)+(?P<tld>[a-z]{{2,}})")
_IPV4 = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
_LOCAL_PART = re.compile(r"[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*")
_URL = re.compile(
    r"(?:(?P<scheme>https?|ftp)://)?"
    r"(?P<host>[^/:?#]+)"
    r"(?::(?P<port>\d{1,5}))?"
    r"(?P<path>[/?#][A-Za-z0-9._~%!$&'()*+,;=:@/?#-]*)?"
)


def _tld_ok(tld: str, tlds: Iterable[str] | None) -> bool:
    """``tlds=None`` means explicit mode: any known TLD, or a short unlisted one."""
    if tlds is None:
        return tld in KNOWN_TLDS or len(tld) <= _MAX_UNLISTED_TLD_LEN
    return tld in tlds


def _host_ok(host: str, tlds: Iterable[str] | None, has_scheme: bool) -> bool:
    match = _HOST_NAME.fullmatch(host)
    if match is not None:
        return _tld_ok(match.group("tld"), tlds)
    # localhost and bare IPs only count as URLs with a protocol in front of
    # them ("http colon slash slash localhost"); on their own they are text.
    return has_scheme and (host == "localhost" or _IPV4.fullmatch(host) is not None)


def is_valid_email(candidate: str, tlds: Iterable[str] | None = None) -> bool:
    local, sep, domain = candidate.partition("@")
    if not sep or "@" in domain:
        return False
    return _LOCAL_PART.fullmatch(local) is not None and _host_ok(
        domain, tlds, has_scheme=False
    )


def is_valid_url(candidate: str, tlds: Iterable[str] | None = None) -> bool:
    match = _URL.fullmatch(candidate)
    if match is None:
        return False
    return _host_ok(match.group("host"), tlds, has_scheme=bool(match.group("scheme")))


def is_valid_address(candidate: str, tlds: Iterable[str] | None = None) -> bool:
    """True when ``candidate`` is a syntactically valid email address or URL.

    ``tlds`` restricts which top-level domains count. ``None`` (explicit
    mode) also accepts any unlisted TLD of up to six letters.
    """
    if "@" in candidate:
        return is_valid_email(candidate, tlds)
    return is_valid_url(candidate, tlds)


def convert_span(text: str, tlds: Iterable[str] | None = None) -> str | None:
    """Convert a spoken address span to written form.

    Returns None when the result isn't a valid address, so the caller can
    leave the span as spoken text instead of typing something malformed.
    The failure is logged by length only, because span text is dictation.
    """
    candidate = assemble(tokenize(text))
    if is_valid_address(candidate, tlds):
        return candidate
    logger.info(
        "Address span failed validation; leaving it as spoken text (%d chars)",
        len(text),
    )
    return None
