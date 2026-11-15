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
from difflib import SequenceMatcher

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

# Phonetic alphabet -> letter, for spelling inside an address (MCC-191).
# Both spellings of the variants, since engines write "Alpha", not "Alfa".
NATO_ALPHABET: dict[str, str] = {
    "alfa": "a", "alpha": "a", "bravo": "b", "charlie": "c", "delta": "d",
    "echo": "e", "foxtrot": "f", "golf": "g", "hotel": "h", "india": "i",
    "juliett": "j", "juliet": "j", "kilo": "k", "lima": "l", "mike": "m",
    "november": "n", "oscar": "o", "papa": "p", "quebec": "q", "romeo": "r",
    "sierra": "s", "tango": "t", "uniform": "u", "victor": "v",
    "whiskey": "w", "whisky": "w", "x-ray": "x", "xray": "x", "yankee": "y",
    "zulu": "z",
}  # fmt: skip

# "capital r" -> R, for case-sensitive URL paths.
CAPITAL_WORDS: frozenset[str] = frozenset({"capital", "cap", "uppercase"})

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


_LETTER = re.compile(r"[a-z]")
# Parakeet writes spelled letters as "R-Y-N".
_HYPHEN_LETTERS = re.compile(r"[a-z](?:-[a-z])+")
_DIGITS = re.compile(r"\d+")

# Spelling items that show the user is spelling, as opposed to a lone NATO
# word ("victor"), which is far likelier to be a name and stays a word.
_SPELLING_KINDS = frozenset({"letter", "hyphen", "capital", "as_in"})


def _spell_item(tokens: Sequence[Token], i: int) -> tuple[str, int, str] | None:
    """One spelled item at ``i``: (written text, tokens consumed, kind)."""
    core = tokens[i].core
    nxt = tokens[i + 1].core if i + 1 < len(tokens) else ""
    if core in CAPITAL_WORDS:
        letter = nxt if _LETTER.fullmatch(nxt) else NATO_ALPHABET.get(nxt)
        if letter:
            return letter.upper(), 2, "capital"
    if _LETTER.fullmatch(core):
        window = [t.core for t in tokens[i + 1 : i + 4]]
        if window[:2] == ["as", "in"] and window[2:] and window[2].startswith(core):
            return core, 4, "as_in"  # "b as in bravo"
        return core, 1, "letter"
    if _HYPHEN_LETTERS.fullmatch(core):
        return core.replace("-", ""), 1, "hyphen"
    if core in NATO_ALPHABET:
        return NATO_ALPHABET[core], 1, "nato"
    if core in DIGIT_WORDS:
        return DIGIT_WORDS[core], 1, "digit"
    if _DIGITS.fullmatch(core):
        return core, 1, "digit"
    return None


def _spell_run(tokens: Sequence[Token], i: int) -> list[tuple[str, int, str]]:
    """Consecutive spelling items from ``i`` (possibly empty)."""
    items = []
    while i < len(tokens):
        item = _spell_item(tokens, i)
        if item is None:
            break
        items.append(item)
        i += item[1]
    return items


def _is_spelling(items: list[tuple[str, int, str]]) -> bool:
    kinds = [kind for _, _, kind in items]
    return bool(_SPELLING_KINDS.intersection(kinds)) or kinds.count("nato") >= 2


def assemble(tokens: Sequence[Token]) -> str:
    """Map a span's spoken words to written form and close up the whitespace.

    Symbol and digit words become their symbols. A spelled run ("r y a n",
    "romeo yankee alpha november", "b as in bravo", "capital r") becomes its
    letters (MCC-191). Every other word is kept and lowercased, together
    with any internal punctuation it already has (``liatrio.com``).
    Punctuation around a word is dropped, so the caller has to decide what
    to do with a sentence-final period. Only "capital" letters keep their
    case, and never in the host. No validation happens here; see
    :func:`is_valid_address`.
    """
    pieces: list[str] = []
    i = 0
    while i < len(tokens):
        symbol, consumed = _match_multiword_symbol(tokens, i)
        if consumed:
            pieces.append(symbol)
            i += consumed
            continue
        run = _spell_run(tokens, i)
        if run and _is_spelling(run):
            pieces.append("".join(text for text, _, _ in run))
            i += sum(consumed for _, consumed, _ in run)
            continue
        core = tokens[i].core
        pieces.append(SYMBOL_WORDS.get(core) or DIGIT_WORDS.get(core) or core)
        i += 1
    return _lowercase_host(_join_pieces(pieces))


def _lowercase_host(candidate: str) -> str:
    """Hosts are case-insensitive, so a spelled capital never reaches one."""
    if "@" in candidate:
        local, _, domain = candidate.rpartition("@")
        return f"{local}@{domain.lower()}"
    match = re.match(r"([A-Za-z]+://)?([^/?#]*)", candidate)
    assert match is not None  # both groups can match empty
    return match.group(0).lower() + candidate[match.end() :]


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


def looks_like_address(word: str) -> bool:
    """True when ``word`` (one whitespace-free token) is a written address.

    The sentence capitaliser uses this so that ``ryan@liatrio.com`` at the
    start of a dictation isn't typed as ``Ryan@liatrio.com``.
    """
    core = word.strip(_LEADING_PUNCT + _TRAILING_PUNCT)
    if not core or core != core.lower():
        return False
    return "://" in core or is_valid_address(core)


# --- Boundary detection (MCC-189) -------------------------------------------
#
# Two modes decide which part of a transcript is an address:
#
# * Explicit: "begin address ... finish address" (or the end of the
#   dictation). Everything in between is converted; nothing outside it is.
# * Inferred: spans are recognised in ordinary dictation. This is deliberately
#   narrow, because mangling prose is worse than missing an address. A span
#   must end in a known TLD (or start with a protocol), "dot" is the only dot
#   word that can join labels ("point" and "period" are too common in prose),
#   punctuation ends a span, and common function words never become a local
#   part or domain label ("look at google dot com" is not look@google.com).

# Words that never form a local part, domain label or path segment on their
# own in inferred mode.
_STOPWORDS: frozenset[str] = frozenset(
    {
        # pronouns and determiners
        "i", "me", "my", "mine", "you", "your", "yours", "he", "him", "his",
        "she", "her", "hers", "it", "its", "we", "us", "our", "ours", "they",
        "them", "their", "this", "that", "these", "those", "who", "whom",
        "whose", "which", "what", "a", "an", "the", "some", "any", "all",
        "each", "every", "no", "one",
        # prepositions and conjunctions
        "at", "in", "on", "of", "to", "for", "from", "with", "by", "about",
        "into", "onto", "over", "under", "near", "around", "after", "before",
        "than", "via", "per", "and", "or", "but", "so", "if", "then",
        "because", "while", "when", "where", "until", "as",
        # auxiliaries and common adverbs
        "is", "am", "are", "was", "were", "be", "been", "being", "do", "does",
        "did", "have", "has", "had", "will", "would", "can", "could",
        "should", "may", "might", "must", "shall", "not", "yes", "here",
        "there", "now", "just", "also", "very", "still", "only", "even",
        "good", "bad", "great", "least", "most", "best", "once", "first",
        "last", "home",
    }
)  # fmt: skip

# Verbs that commonly come right before "at" ("look at", "arrive at").
_AT_VERBS = (
    "look", "stare", "glance", "point", "aim", "arrive", "meet", "work",
    "live", "stay", "wait", "land", "start", "stop", "end", "begin",
    "finish", "laugh", "smile", "wave", "shout", "yell", "throw", "shop",
    "eat", "study", "play", "park", "sit", "stand", "call", "email",
    "text", "reach", "find", "see", "visit",
)  # fmt: skip
_AT_VERB_IRREGULAR = (
    "met", "sat", "stood", "ate", "began", "begun", "found", "saw", "seen",
    "threw", "thrown",
)  # fmt: skip
_STOPWORDS |= frozenset(
    form
    for verb in _AT_VERBS
    for form in (verb, verb + "s", verb + "ed", verb + "d", verb + "ing")
) | frozenset(_AT_VERB_IRREGULAR)

# Which spoken symbols may join units inside each part of an inferred span.
_LOCAL_JOINERS = frozenset({"dot", "underscore", "dash", "hyphen", "plus"})
_HOST_JOINERS = frozenset({"dot", "dash", "hyphen"})
_PATH_JOINERS = frozenset({"dot", "dash", "hyphen", "underscore"})
_PROTOCOL_WORDS = frozenset({"http", "https", "ftp"})

# One already-written chunk of an address: a word, "liatrio.com", "k2-fsa".
_WORD_UNIT = re.compile(r"[a-z0-9](?:[a-z0-9._%+-]*[a-z0-9])?")

DEFAULT_BEGIN_PHRASES = ("begin address",)
DEFAULT_END_PHRASES = ("finish address", "end address")

# Within an open explicit span, an end phrase matches at this difflib ratio
# or better. Parakeet hears "end address" as "and address".
_END_PHRASE_RATIO = 0.8


class _InferredParser:
    """Recognises address spans in one token list. Each ``_match_*`` method
    returns the exclusive end index of a span starting at ``i``, or None."""

    def __init__(self, tokens: Sequence[Token], tlds: frozenset[str]):
        self.tokens = tokens
        self.tlds = tlds

    # A span can't run past punctuation ("com, and") and can't absorb a word
    # with leading punctuation, except as its first token.
    def _can_extend(self, p: int) -> bool:
        return 0 < p < len(self.tokens) and self._no_break_before(p)

    def _is(self, p: int, *words: str) -> bool:
        return self._can_extend(p) and self.tokens[p].core in words

    def _is_digit(self, p: int) -> bool:
        core = self.tokens[p].core
        return core in DIGIT_WORDS or _DIGITS.fullmatch(core) is not None

    def _no_break_before(self, q: int) -> bool:
        """No punctuation between tokens ``q - 1`` and ``q``, except the
        period an engine puts after a spelled letter ("R. Y. A. N.")."""
        prev, tok = self.tokens[q - 1], self.tokens[q]
        if tok.lead:
            return False
        lettered = prev.trail == "." and _LETTER.fullmatch(prev.core) is not None
        return not prev.trail or lettered

    def _spelled_unit(self, p: int) -> int | None:
        """End of a spelled run at ``p`` ("r y a n", "k two f s a"), if any."""
        tokens = self.tokens
        items: list[tuple[str, int, str]] = []
        q = p
        while q < len(tokens):
            if q > p and not self._no_break_before(q):
                break
            item = _spell_item(tokens, q)
            if item is None or any(
                tokens[k].trail or tokens[k + 1].lead for k in range(q, q + item[1] - 1)
            ):
                break
            items.append(item)
            q += item[1]
        if not items or not _is_spelling(items):
            return None
        if len(items) == 1 and tokens[p].core in ("a", "i"):
            return None  # the words "a" and "I", not spelling
        return q

    def _unit(self, p: int, first: bool = False) -> int | None:
        """End of the unit at ``p``: a spelled run, a run of digits, or one
        plain word."""
        if not first and not self._can_extend(p):
            return None
        if p >= len(self.tokens):
            return None
        spelled = self._spelled_unit(p)
        if spelled is not None:
            return spelled
        if self._is_digit(p):
            end = p + 1
            while self._can_extend(end) and self._is_digit(end):
                end += 1
            return end
        core = self.tokens[p].core
        if (
            core in SYMBOL_WORDS
            or core in _STOPWORDS
            or _WORD_UNIT.fullmatch(core) is None
        ):
            return None
        return p + 1

    def _chain(self, p: int, joiners: frozenset[str], first: bool) -> list[int]:
        """Units joined by ``joiners``. Returns the end after each unit."""
        end = self._unit(p, first=first)
        ends: list[int] = []
        while end is not None:
            ends.append(end)
            if not self._is(end, *joiners):
                break
            end = self._unit(end + 1)
        return ends

    def _host(self, p: int, first: bool, has_scheme: bool) -> int | None:
        """Longest chain from ``p`` that assembles to a valid host."""
        tlds = None if has_scheme else self.tlds
        for end in reversed(self._chain(p, _HOST_JOINERS, first)):
            host = assemble(self.tokens[p:end])
            # Without a protocol, an all-digit label is far likelier to be a
            # number in a sentence ("two dot com companies") than a domain.
            if not has_scheme and any(label.isdigit() for label in host.split(".")):
                continue
            if _host_ok(host, tlds, has_scheme):
                return end
        return None

    def _path(self, p: int) -> int:
        """Optional ":port" and "/segment" parts after a host."""
        if self._is(p, "colon") and self._can_extend(p + 1) and self._is_digit(p + 1):
            p = self._unit(p + 1) or p
        while self._is(p, "slash"):
            p += 1
            ends = self._chain(p, _PATH_JOINERS, first=False)
            if ends:
                p = ends[-1]
        return p

    def _word_at(self, i: int) -> tuple[str, int]:
        """The written word at ``i`` and its end, joining a spelled run
        ("h t t p s" -> "https", "w w w" -> "www")."""
        spelled = self._spelled_unit(i)
        if spelled is not None:
            return assemble(self.tokens[i:spelled]), spelled
        return self.tokens[i].core, i + 1

    def _match_protocol(self, i: int) -> int | None:
        word, p = self._word_at(i)
        if word not in _PROTOCOL_WORDS:
            return None
        for word in ("colon", "slash", "slash"):
            if not self._is(p, word):
                return None
            p += 1
        end = self._host(p, first=False, has_scheme=True)
        return self._path(end) if end is not None else None

    def _match_www(self, i: int) -> int | None:
        word, p = self._word_at(i)
        if word != "www":
            return None
        if self._is(p, "dot"):
            p += 1
        end = self._host(p, first=False, has_scheme=False)
        return self._path(end) if end is not None else None

    def _match_email(self, i: int) -> int | None:
        ends = self._chain(i, _LOCAL_JOINERS, first=True)
        if not ends or not self._is(ends[-1], "at"):
            return None
        return self._host(ends[-1] + 1, first=False, has_scheme=False)

    def _match_bare(self, i: int) -> int | None:
        end = self._host(i, first=True, has_scheme=False)
        return self._path(end) if end is not None else None

    def spans(self) -> list[tuple[int, int]]:
        found = []
        i = 0
        matchers = (
            self._match_protocol,
            self._match_www,
            self._match_email,
            self._match_bare,
        )
        while i < len(self.tokens):
            for match in matchers:
                end = match(i)
                if end is not None:
                    found.append((i, end))
                    i = end
                    break
            else:
                i += 1
        return found


def _phrase_words(phrases: Iterable[str]) -> list[tuple[str, ...]]:
    return [tuple(p.lower().split()) for p in phrases if p.split()]


class AddressNormalizer:
    """Converts the email addresses and URLs in a transcript to written form.

    Runs after the dictionary pass (so a domain the model split up is
    repaired first) and before ``TextProcessor`` (so "colon" and "period"
    inside an address become symbols rather than punctuation).
    """

    def __init__(
        self,
        explicit: bool = True,
        inferred: bool = True,
        begin_phrases: Iterable[str] = DEFAULT_BEGIN_PHRASES,
        end_phrases: Iterable[str] = DEFAULT_END_PHRASES,
        extra_tlds: Iterable[str] = (),
    ) -> None:
        self.explicit = explicit
        self.inferred = inferred
        self._begin = _phrase_words(begin_phrases)
        self._end = _phrase_words(end_phrases)
        self._tlds = KNOWN_TLDS | {t.lower().lstrip(".") for t in extra_tlds}

    def normalize(self, text: str) -> str:
        if not text or not (self.explicit or self.inferred):
            return text
        pieces = self._explicit_pass(text) if self.explicit else [(text, False)]
        if self.inferred:
            pieces = [
                (piece if done else self._inferred_pass(piece), done)
                for piece, done in pieces
            ]
        return "".join(piece for piece, _ in pieces)

    # -- explicit mode --

    def _match_phrase(
        self, tokens: Sequence[Token], i: int, phrases: list[tuple[str, ...]],
        fuzzy: bool,
    ) -> int:
        """Token count of the phrase starting at ``i``, or 0."""
        for words in phrases:
            window = tuple(t.core for t in tokens[i : i + len(words)])
            if len(window) != len(words):
                continue
            if window == words:
                return len(words)
            if fuzzy:
                ratio = SequenceMatcher(None, " ".join(window), " ".join(words)).ratio()
                if ratio >= _END_PHRASE_RATIO:
                    return len(words)
        return 0

    def _explicit_pass(self, text: str) -> list[tuple[str, bool]]:
        """Split ``text`` into (piece, converted) pairs. Converted pieces are
        explicit-mode output that inferred mode must not touch again."""
        tokens = tokenize(text)
        pieces: list[tuple[str, bool]] = []
        cursor = 0
        i = 0
        while i < len(tokens):
            begin_len = self._match_phrase(tokens, i, self._begin, fuzzy=False)
            if not begin_len:
                i += 1
                continue
            start = i + begin_len
            stop = start
            end_len = 0
            while stop < len(tokens):
                end_len = self._match_phrase(tokens, stop, self._end, fuzzy=True)
                if end_len:
                    break
                stop += 1
            span = tokens[start:stop]
            # The replacement runs from the trigger to the terminator (or the
            # last spoken token), keeping the punctuation that follows it.
            last = tokens[stop + end_len - 1] if end_len else tokens[stop - 1]
            region_end = last.core_end
            pieces.append((text[cursor : tokens[i].start + len(tokens[i].lead)], False))
            if span:
                spoken = text[span[0].start : span[-1].core_end]
                converted = convert_span(spoken)
                pieces.append((converted if converted is not None else spoken, True))
            elif not last.trail and region_end < len(text) and text[region_end] == " ":
                region_end += 1  # don't leave a double space behind
            cursor = region_end
            i = stop + end_len
            logger.debug("Explicit address span: %d tokens", len(span))
        pieces.append((text[cursor:], False))
        return pieces

    # -- inferred mode --

    def _inferred_pass(self, text: str) -> str:
        tokens = tokenize(text)
        out = []
        cursor = 0
        for i, end in _InferredParser(tokens, self._tlds).spans():
            first, last = tokens[i], tokens[end - 1]
            candidate = assemble(tokens[i:end])
            region_start = first.start + len(first.lead)
            original = text[region_start : last.core_end]
            if candidate == original or not is_valid_address(candidate, None):
                continue
            out.append(text[cursor:region_start])
            out.append(candidate)
            cursor = last.core_end
        out.append(text[cursor:])
        return "".join(out)
