"""Atomic, comment-preserving updates to the user's config file.

The shipped config.yaml is documented through its comments, so rewrites must
round-trip them (ruamel.yaml) rather than dump a bare data structure.  Writes
go to a temp file in the same directory and are moved into place with
``os.replace`` so a crash mid-write can never leave a truncated config, and a
process-wide lock serializes the writers (tray model switch and hotkey editor
run on different threads).
"""

import contextlib
import logging
import os
import tempfile
import threading
from collections.abc import Callable

from ruamel.yaml import YAML

logger = logging.getLogger("verbal_code")

_write_lock = threading.Lock()

_DEFAULT_MODE = 0o644


def _make_yaml() -> YAML:
    yaml = YAML()  # round-trip mode: preserves comments, ordering, quoting
    yaml.default_flow_style = False
    return yaml


def update_config(path: str, mutate: Callable[[dict], None]) -> None:
    """Read the YAML config at ``path``, apply ``mutate``, and write it back.

    The write is atomic and preserves comments; a missing file (or an empty
    one) starts from an empty mapping.  Raises ``OSError`` or a ruamel
    parsing error on failure — callers decide how to surface it.
    """
    with _write_lock:
        yaml = _make_yaml()
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)

        if os.path.isfile(path):
            with open(path) as f:
                cfg = yaml.load(f) or {}
            mode = os.stat(path).st_mode & 0o777
        else:
            cfg = {}
            mode = _DEFAULT_MODE

        mutate(cfg)

        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".config-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(cfg, f)
            os.chmod(tmp_path, mode)
            os.replace(tmp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
