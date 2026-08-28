"""Persisted store for user-defined custom terms (MCC-54).

Transcription models consistently mangle proper nouns, acronyms, and domain
jargon; the dictionary is a user-owned list of corrections the rest of the
pipeline can apply. This module is the data layer only — matching terms
against transcribed text and any UI live elsewhere.

Stored separately from config.yaml (``dictionary.json``, alongside it) since
it is expected to grow independently of the handful of config options.
Writes are atomic (temp file + ``os.replace``) for the same crash-safety
reason as ``config_store``.
"""

import contextlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

_write_lock = threading.Lock()

_DEFAULT_MODE = 0o644


def default_dictionary_path() -> str:
    return os.path.expanduser("~/.config/verbal-code/dictionary.json")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class DictionaryEntry:
    """One correction. Matching is case-insensitive; ``term`` and
    ``variants`` may be single words or multi-word phrases — matching is a
    whole-string comparison, not per-token, so phrases work the same way
    words do."""

    term: str
    variants: list[str] = field(default_factory=list)
    source: str = "manual"
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        if lowered == self.term.lower():
            return True
        return any(lowered == variant.lower() for variant in self.variants)


class DictionaryStore:
    """Add/update/delete/lookup against a JSON-backed dictionary file.

    Entries are cached in memory, keyed by the term's lowercase form for
    case-insensitive uniqueness; every mutation persists immediately. A
    missing file starts from an empty dictionary — no behavior change until
    the user adds a term.
    """

    def __init__(self, path: str | None = None):
        self._path = os.path.expanduser(path or default_dictionary_path())
        self._entries: dict[str, DictionaryEntry] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            self._entries = {}
            return
        with open(self._path) as f:
            raw = json.load(f) or {}
        self._entries = {
            entry["term"].lower(): DictionaryEntry(**entry)
            for entry in raw.get("entries", [])
        }

    def _save(self) -> None:
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {"entries": [asdict(e) for e in self.entries]}

        mode = _DEFAULT_MODE
        if os.path.isfile(self._path):
            mode = os.stat(self._path).st_mode & 0o777

        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".dictionary-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.chmod(tmp_path, mode)
            os.replace(tmp_path, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    @property
    def entries(self) -> list[DictionaryEntry]:
        return sorted(self._entries.values(), key=lambda e: e.term.lower())

    def add(
        self,
        term: str,
        variants: list[str] | None = None,
        source: str = "manual",
        enabled: bool = True,
    ) -> DictionaryEntry:
        key = term.lower()
        with _write_lock:
            if key in self._entries:
                raise ValueError(f"dictionary already has a term for {term!r}")
            now = _now()
            entry = DictionaryEntry(
                term=term,
                variants=list(variants or []),
                source=source,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            self._entries[key] = entry
            self._save()
            return entry

    def update(
        self,
        term: str,
        *,
        variants: list[str] | None = None,
        enabled: bool | None = None,
    ) -> DictionaryEntry:
        key = term.lower()
        with _write_lock:
            entry = self._entries.get(key)
            if entry is None:
                raise KeyError(f"no dictionary entry for {term!r}")
            if variants is not None:
                entry.variants = list(variants)
            if enabled is not None:
                entry.enabled = enabled
            entry.updated_at = _now()
            self._save()
            return entry

    def delete(self, term: str) -> None:
        key = term.lower()
        with _write_lock:
            if key not in self._entries:
                raise KeyError(f"no dictionary entry for {term!r}")
            del self._entries[key]
            self._save()

    def lookup(self, text: str) -> DictionaryEntry | None:
        lowered = text.lower()
        exact = self._entries.get(lowered)
        if exact is not None:
            return exact
        for entry in self._entries.values():
            if any(lowered == variant.lower() for variant in entry.variants):
                return entry
        return None
