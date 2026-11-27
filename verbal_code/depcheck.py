"""Dependency conflicts that matter to Verbal Code, and the ones that don't
(MCC-202).

The venv is created with ``--system-site-packages`` (the tray needs the
system's GTK bindings), so ``pip check`` and pip's post-install resolver
check also see every distro Python package. Those can conflict among
themselves: Linux Mint 22 ships yt-dlp 2024.4.9, which wants
websockets>=12, next to websockets 10.4. Such a conflict exists before
Verbal Code is installed, isn't Verbal Code's to fix, and must not fail an
install, an update or the GPU backend step.

A conflict *belongs to* Verbal Code when the distribution whose
requirement is unmet is in Verbal Code's dependency tree: verbal-code
itself and everything it requires, transitively, with extras. Only those
fail a step. The rest are reported in one short note.

Run with the venv interpreter, from ``/``:
``python -m verbal_code.depcheck``. Exit 0 when Verbal Code's own tree is
consistent (a note on stdout names any unrelated conflict), 1 when it
isn't (each conflict on stderr), 2 when the check couldn't run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import metadata

ROOT = "verbal-code"
_TIMEOUT_SECONDS = 120

RunFn = Callable[..., subprocess.CompletedProcess]


def normalize(name: str) -> str:
    """PEP 503 name normalization: ``Ruamel.YAML`` -> ``ruamel-yaml``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_class():
    try:
        from packaging.requirements import Requirement
    except ImportError:  # packaging is a system package here, not ours
        from pip._vendor.packaging.requirements import Requirement
    return Requirement


def dependency_tree(
    root: str = ROOT,
    requires: Callable[[str], Iterable[str] | None] = metadata.requires,
) -> set[str]:
    """Normalized names of ``root`` and every installed distribution it
    requires, transitively. Every extra of the root counts (an optional
    engine that is installed is part of Verbal Code); a dependency's extras
    count when something in the tree asks for them. A requirement whose
    marker can't be evaluated is included: counting too much only makes the
    check stricter."""
    Requirement = _requirement_class()
    expanded: dict[str, set[str]] = {}  # name -> extras already followed
    queue: list[tuple[str, set[str] | None]] = [(root, None)]  # None: all extras
    while queue:
        name, extras = queue.pop()
        key = normalize(name)
        try:
            lines = list(requires(name) or [])
        except metadata.PackageNotFoundError:
            continue  # not installed: pip check reports it against the parent
        first = key not in expanded
        done = expanded.setdefault(key, set())
        for line in lines:
            try:
                req = Requirement(line)
            except Exception:  # noqa: BLE001 — another package's bad metadata
                continue
            wanted = _wanted_extras(str(req.marker) if req.marker else "")
            if wanted is None:  # no extra in the marker: a base requirement
                if not first or not _applies(req.marker, ""):
                    continue
            elif extras is not None and not any(
                    _applies(req.marker, e) for e in (wanted & extras) - done):
                continue  # an extra nobody in the tree asked for
            queue.append((req.name, {normalize(e) for e in req.extras}))
        done.update(extras if extras is not None else {"*"})
    return set(expanded)


def _wanted_extras(marker: str) -> set[str] | None:
    """The extras a marker names, or None when it names none."""
    names = re.findall(r"""extra\s*==\s*["']([^"']+)["']""", marker)
    return {normalize(n) for n in names} or None


def _applies(marker, extra: str) -> bool:
    if marker is None:
        return True
    try:
        return bool(marker.evaluate({"extra": extra}))
    except Exception:  # noqa: BLE001
        return True


@dataclass
class Conflict:
    owner: str  # normalized name of the distribution whose requirement is unmet
    line: str  # pip's own sentence

    @property
    def needs(self) -> str:
        """What the owner wants, e.g. ``websockets>=12.0``."""
        match = re.search(r"(?:has requirement|requires) (\S+?),", self.line)
        return match.group(1) if match else ""


# pip check: "X 1.0 has requirement Y>=2, but you have Y 1.0." /
# "X 1.0 requires Y, which is not installed." / "X 1.0 is not supported on
# this platform". pip install's resolver note: "X 1.0 requires Y>=2, but you
# have Y 1.0 which is incompatible."
_CONFLICT = re.compile(
    r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]*) \S+ "
    r"(?:has requirement|requires|is not supported)"
)


def parse_conflicts(text: str) -> list[Conflict]:
    conflicts = []
    for raw in text.splitlines():
        line = raw.strip()
        match = _CONFLICT.match(line)
        if match:
            conflicts.append(Conflict(normalize(match.group("owner")), line))
    return conflicts


@dataclass
class Report:
    own: list[Conflict] = field(default_factory=list)
    unrelated: list[Conflict] = field(default_factory=list)
    error: str = ""  # the check itself couldn't run

    @property
    def ok(self) -> bool:
        return not self.own and not self.error

    def note(self) -> str:
        """One line about the unrelated conflicts, or ""."""
        if not self.unrelated:
            return ""
        parts = []
        for conflict in self.unrelated[:3]:
            parts.append(f"{conflict.owner} wants {conflict.needs}"
                         if conflict.needs else conflict.owner)
        more = len(self.unrelated) - 3
        listed = "; ".join(parts) + (f"; {more} more" if more > 0 else "")
        return (f"Other Python packages on this system have conflicting "
                f"requirements ({listed}). Verbal Code doesn't use them and "
                f"isn't affected.")

    def failure(self) -> str:
        """The error message when Verbal Code's own tree is inconsistent."""
        if self.error:
            return f"could not check dependencies: {self.error}"
        return ("Verbal Code's dependencies conflict: "
                + "; ".join(c.line.rstrip(".") for c in self.own))


def classify(conflicts: Iterable[Conflict], tree: set[str]) -> Report:
    report = Report()
    for conflict in conflicts:
        (report.own if conflict.owner in tree else report.unrelated).append(conflict)
    return report


def check(
    run: RunFn | None = None,
    python: str | None = None,
    tree: set[str] | None = None,
) -> Report:
    """``pip check`` in ``python``'s environment, split into Verbal Code's
    own conflicts and the rest. ``tree`` defaults to this interpreter's
    view of Verbal Code's dependency tree, so call it with the venv's."""
    run = run or subprocess.run  # looked up per call, so tests can patch it
    python = python or sys.executable
    if tree is None:
        tree = dependency_tree()
        if ROOT not in tree:
            return Report(error=f"{ROOT} is not installed")
    try:
        result = run([python, "-m", "pip", "check"], capture_output=True,
                     text=True, timeout=_TIMEOUT_SECONDS, cwd="/")
    except (OSError, subprocess.SubprocessError) as exc:
        return Report(error=f"pip check did not run ({exc})")
    conflicts = parse_conflicts(result.stdout)
    if result.returncode != 0 and not conflicts:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return Report(error=detail[-1] if detail else
                      f"pip check exited with status {result.returncode}")
    return classify(conflicts, tree)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m verbal_code.depcheck")
    parser.add_argument("--no-note", action="store_true",
                        help="don't print the note about unrelated conflicts")
    parser.add_argument("--pip-python", default=None,
                        help="the interpreter whose `pip check` runs (default: "
                        "this one; the dependency tree is always this one's)")
    args = parser.parse_args(argv)
    report = check(python=args.pip_python)
    if report.error:
        print(report.failure(), file=sys.stderr)
        return 2
    if report.own:
        print(report.failure(), file=sys.stderr)
        return 1
    if report.note() and not args.no_note:
        print(report.note())
    return 0


if __name__ == "__main__":
    sys.exit(main())
