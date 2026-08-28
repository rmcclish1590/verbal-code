"""Applies dictionary corrections to transcribed text before injection (MCC-55).

An exact case-insensitive match to a term or one of its known variants is
always corrected to the canonical spelling. Anything close enough — measured
by `difflib`'s sequence-matching ratio, no extra dependency — but not exact
also gets corrected, so the STT engine's exact way of mangling a word doesn't
have to be captured as a `variants` entry in advance. Everything else —
spacing, punctuation — passes through untouched; sentence-level
capitalization is `TextProcessor`'s job and runs after this.
"""

import re
from difflib import SequenceMatcher

from verbal_code.dictionary import DictionaryEntry, DictionaryStore

_TOKEN_RE = re.compile(r"(?P<word>\w+(?:'\w+)*)|(?P<sep>\W+)")

# Fuzzy matching below this length produces too many false-positive hits
# ("a", "an", "or" are a short edit away from all sorts of real words).
_MIN_FUZZY_LEN = 3

DEFAULT_FUZZY_THRESHOLD = 0.82


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
                phrase = " ".join(tokens[j][1] for j in word_idx[i : i + n])
                entry = self._best_match(phrase, entries)
                if entry is not None:
                    tokens[start : end + 1] = [(True, entry.term)]
                    word_idx = [
                        k for k, (is_word, _) in enumerate(tokens) if is_word
                    ]
                    i += 1
                    break
            else:
                i += 1

        return "".join(t for _, t in tokens)

    def _best_match(
        self, phrase: str, entries: list[DictionaryEntry]
    ) -> DictionaryEntry | None:
        for entry in entries:
            if entry.matches(phrase):
                return entry

        if len(phrase) < _MIN_FUZZY_LEN:
            return None

        lowered = phrase.lower()
        best_entry = None
        best_ratio = self._threshold
        for entry in entries:
            for candidate in (entry.term, *entry.variants):
                ratio = SequenceMatcher(None, lowered, candidate.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_entry = entry
        return best_entry

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
