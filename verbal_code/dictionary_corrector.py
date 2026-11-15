"""Applies dictionary corrections to transcribed text before injection (MCC-55).

An exact case-insensitive match to a term or one of its known variants is
always corrected to the canonical spelling. Anything close enough — measured
by `difflib`'s sequence-matching ratio, no extra dependency — but not exact
also gets corrected, so the STT engine's exact way of mangling a word doesn't
have to be captured as a `variants` entry in advance. Everything else —
spacing, punctuation — passes through untouched; sentence-level
capitalization is `TextProcessor`'s job and runs after this.

Fuzzy matching compares a phrase only with candidates that have the same
number of words. A two-word phrase such as "at liatrio" is close enough to
the one-word term "liatrio" to pass the threshold, and it would swallow
the "at". A phrase that is exactly a term with its spaces removed
("en gen" for "EnGen") still matches, as long as no symbol word is in it.

Address terms (MCC-192). This pass runs before address ITN, so it repairs a
domain the engine split up ("lee at treo" -> "liatrio") before the
spurious "at" can become a second "@". Next to an address (an "at" or
"dot" beside the phrase, or ".com" stuck to it), entries flagged
``address`` are tried first. They may also match a phrase of up to
``_ADDRESS_MAX_WORDS`` words with the spaces removed, and they are written
lowercase and unspaced.
"""

import re
from difflib import SequenceMatcher

from verbal_code.dictionary import DictionaryEntry, DictionaryStore

_TOKEN_RE = re.compile(r"(?P<word>\w+(?:'\w+)*)|(?P<sep>\W+)")

# Fuzzy matching below this length produces too many false-positive hits
# ("a", "an", "or" are a short edit away from all sorts of real words).
_MIN_FUZZY_LEN = 3

DEFAULT_FUZZY_THRESHOLD = 0.82

# Longest split-up domain an address entry is matched against ("lee a trio").
_ADDRESS_MAX_WORDS = 4

# Words beside a phrase that mark it as part of an address. Phrases that
# contain one of these are never joined up, so "lia trio dot" can't
# swallow the "dot".
_ADDRESS_NEIGHBOURS = frozenset({"at", "dot"})


def _joined(candidate: str) -> str:
    return "".join(candidate.split()).lower()


def _tokenize(text: str) -> list[tuple[bool, str]]:
    tokens: list[tuple[bool, str]] = []
    for m in _TOKEN_RE.finditer(text):
        word = m.group("word")
        if word is not None:
            tokens.append((True, word))
        else:
            tokens.append((False, m.group("sep")))
    return tokens


class DictionaryCorrector:
    """Runs transcribed text through a `DictionaryStore` and returns the
    corrected text. See MCC-54 for the store this reads from."""

    def __init__(
        self,
        store: DictionaryStore,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    ) -> None:
        self._store = store
        self._threshold = fuzzy_threshold

    def correct(self, text: str) -> str:
        entries = [e for e in self._store.entries if e.enabled]
        if not entries or not text:
            return text

        max_phrase_words = max(
            len(candidate.split())
            for entry in entries
            for candidate in (entry.term, *entry.variants)
        )
        if any(entry.address for entry in entries):
            max_phrase_words = max(max_phrase_words, _ADDRESS_MAX_WORDS)

        tokens = _tokenize(text)
        word_idx = [i for i, (is_word, _) in enumerate(tokens) if is_word]

        i = 0
        while i < len(word_idx):
            max_n = min(max_phrase_words, len(word_idx) - i)
            for n in range(max_n, 0, -1):
                if n > 1 and not self._is_contiguous_phrase(tokens, word_idx, i, n):
                    continue
                start = word_idx[i]
                end = word_idx[i + n - 1]
                words = [tokens[j][1] for j in word_idx[i : i + n]]
                in_address = self._in_address_context(tokens, start, end)
                entry = self._best_match(words, entries, in_address)
                if entry is not None:
                    tokens[start : end + 1] = [
                        (True, self._written(entry, in_address))
                    ]
                    word_idx = [
                        k for k, (is_word, _) in enumerate(tokens) if is_word
                    ]
                    i += 1
                    break
            else:
                i += 1

        return "".join(t for _, t in tokens)

    @staticmethod
    def _written(entry: DictionaryEntry, in_address: bool) -> str:
        if in_address and entry.address:
            return "".join(entry.term.split()).lower()
        return entry.term

    def _best_match(
        self, words: list[str], entries: list[DictionaryEntry], in_address: bool
    ) -> DictionaryEntry | None:
        phrase = " ".join(words)
        for entry in entries:
            if entry.matches(phrase):
                return entry

        joinable = len(words) > 1 and not any(
            w.lower() in _ADDRESS_NEIGHBOURS for w in words
        )
        joined = "".join(words).lower()
        if joinable:
            for entry in entries:
                if any(joined == _joined(c) for c in (entry.term, *entry.variants)):
                    return entry

        if len(phrase) < _MIN_FUZZY_LEN:
            return None

        address_entries = [e for e in entries if e.address]
        if in_address:
            # Address terms win next to an address; elsewhere every entry is
            # weighed the same.
            match = self._fuzzy(phrase.lower(), len(words), address_entries)
            if match is not None:
                return match
            if joinable:
                match = self._fuzzy_joined(joined, address_entries)
                if match is not None:
                    return match
        return self._fuzzy(phrase.lower(), len(words), entries)

    def _fuzzy(
        self, lowered: str, word_count: int, entries: list[DictionaryEntry]
    ) -> DictionaryEntry | None:
        best_entry = None
        best_ratio = self._threshold
        for entry in entries:
            for candidate in (entry.term, *entry.variants):
                if len(candidate.split()) != word_count:
                    continue
                ratio = SequenceMatcher(None, lowered, candidate.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_entry = entry
        return best_entry

    def _fuzzy_joined(
        self, joined: str, entries: list[DictionaryEntry]
    ) -> DictionaryEntry | None:
        best_entry = None
        best_ratio = self._threshold
        for entry in entries:
            for candidate in (entry.term, *entry.variants):
                ratio = SequenceMatcher(None, joined, _joined(candidate)).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_entry = entry
        return best_entry

    @staticmethod
    def _in_address_context(
        tokens: list[tuple[bool, str]], start: int, end: int
    ) -> bool:
        """True when the phrase at tokens[start..end] sits in an address:
        an "at" before it, an "at" or "dot" after it, or a "." or "@"
        joining it to the next or previous word ("treo.com")."""
        before = tokens[start - 1][1] if start >= 1 else ""
        after = tokens[end + 1][1] if end + 1 < len(tokens) else ""
        if (before in (".", "@") and start >= 2) or (
            after in (".", "@") and end + 2 < len(tokens)
        ):
            return True
        prev_word = tokens[start - 2][1].lower() if start >= 2 else ""
        next_word = tokens[end + 2][1].lower() if end + 2 < len(tokens) else ""
        return prev_word == "at" or next_word in _ADDRESS_NEIGHBOURS

    @staticmethod
    def _is_contiguous_phrase(
        tokens: list[tuple[bool, str]], word_idx: list[int], i: int, n: int
    ) -> bool:
        """True when the n words starting at word_idx[i] are separated only
        by whitespace — a comma, period, or newline between them means
        they're not one phrase and shouldn't be merged into a match."""
        for k in range(i, i + n - 1):
            sep_index = word_idx[k] + 1
            if not tokens[sep_index][1].isspace():
                return False
        return True
