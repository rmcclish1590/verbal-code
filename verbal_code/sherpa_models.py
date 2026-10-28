"""Model download and file resolution for the sherpa-onnx streaming engine.

sherpa-onnx loads models from local files, so the first use of a model
downloads its release archive from the k2-fsa GitHub releases and unpacks it
under ``~/.cache/verbal-code/sherpa-onnx/<model_name>/``.  Only models listed
in :data:`SHERPA_MODELS` are ever downloaded, and each archive must match its
pinned SHA-256 before anything is extracted, so a compromised or swapped
release asset can't be installed silently.
"""

import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
import urllib.request

logger = logging.getLogger("verbal_code")

DEFAULT_SHERPA_CACHE_DIR = os.path.expanduser("~/.cache/verbal-code/sherpa-onnx")

_RELEASE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{name}.tar.bz2"
)
_DOWNLOAD_BLOCK_SIZE = 1 << 20

#: Downloadable models -> SHA-256 of the release archive (from the GitHub
#: release asset digests).  A model directory already present in the cache is
#: used as-is, whatever its name, so custom models still work offline.
SHERPA_MODELS: dict[str, str] = {
    # Kroko Zipformer transducer (~57 MB download): fast and light.
    "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06": (
        "c8676e5ff9ac2a85296e53ee0fd4d5fb1db6770e7a7647166eeafe349ade6834"
    ),
    # NVIDIA Nemotron streaming (~464 MB, INT8): punctuated, capitalised.
    "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25": (
        "78e2b79fcf7271553a74402a76b771b09ea40117a39566a79f52235b23db6358"
    ),
}

_TRANSDUCER_PARTS = ("encoder", "decoder", "joiner")


def resolve_transducer_files(model_dir: str) -> tuple[str, str, str, str]:
    """Return (encoder, decoder, joiner, tokens) paths inside ``model_dir``.

    Prefers INT8 weights (``encoder.int8.onnx``) over float ones
    (``encoder.onnx``) when an archive ships both, and accepts the
    ``encoder-epoch-99-avg-1.onnx`` style names older releases use.
    """
    files = sorted(os.listdir(model_dir))
    paths: list[str] = []
    missing: list[str] = []
    for part in _TRANSDUCER_PARTS:
        candidates = [
            f for f in files if f.startswith(part) and f.endswith(".onnx")
        ]
        int8 = [f for f in candidates if f.endswith(".int8.onnx")]
        chosen = (int8 or candidates)[:1]
        if chosen:
            paths.append(os.path.join(model_dir, chosen[0]))
        else:
            missing.append(f"{part}*.onnx")
    if "tokens.txt" not in files:
        missing.append("tokens.txt")
    if missing:
        raise FileNotFoundError(
            f"sherpa-onnx model in {model_dir} is missing {', '.join(missing)}"
        )
    encoder, decoder, joiner = paths
    return encoder, decoder, joiner, os.path.join(model_dir, "tokens.txt")


def ensure_sherpa_model_downloaded(
    model_name: str, cache_dir: str = DEFAULT_SHERPA_CACHE_DIR
) -> str:
    """Return the local directory for ``model_name``, downloading it if needed.

    Raises ValueError for a model that is neither cached nor in
    :data:`SHERPA_MODELS`, and RuntimeError when a download fails its
    checksum.
    """
    model_dir = os.path.join(cache_dir, model_name)
    if os.path.isdir(model_dir):
        return model_dir

    expected_sha256 = SHERPA_MODELS.get(model_name)
    if expected_sha256 is None:
        raise ValueError(
            f"Unknown sherpa-onnx model {model_name!r}: not one of "
            f"{', '.join(sorted(SHERPA_MODELS))}, and no local copy at {model_dir}"
        )

    os.makedirs(cache_dir, exist_ok=True)
    fd, archive_path = tempfile.mkstemp(dir=cache_dir, suffix=".tar.bz2.part")
    extract_dir = tempfile.mkdtemp(dir=cache_dir, prefix=".extract-")
    try:
        url = _RELEASE_URL.format(name=model_name)
        logger.info("Downloading sherpa-onnx model '%s'...", model_name)
        with os.fdopen(fd, "wb") as out:
            digest = _download(url, out)
        if digest != expected_sha256:
            raise RuntimeError(
                f"Checksum mismatch for sherpa-onnx model {model_name!r}: "
                f"expected {expected_sha256}, got {digest}"
            )
        _extract(archive_path, extract_dir, model_name)
        # Rename into place last so an interrupted download or extraction
        # never leaves a half-populated model directory that looks cached.
        os.replace(os.path.join(extract_dir, model_name), model_dir)
        logger.info("sherpa-onnx model '%s' installed in %s", model_name, model_dir)
    finally:
        if os.path.exists(archive_path):
            os.remove(archive_path)
        shutil.rmtree(extract_dir, ignore_errors=True)
    return model_dir


def _download(url: str, out: "object") -> str:
    """Stream ``url`` into the binary file ``out``; return its SHA-256 hex."""
    sha256 = hashlib.sha256()
    with urllib.request.urlopen(url) as response:  # noqa: S310 — fixed https URL
        while block := response.read(_DOWNLOAD_BLOCK_SIZE):
            sha256.update(block)
            out.write(block)  # type: ignore[attr-defined]
    return sha256.hexdigest()


def _extract(archive_path: str, dest: str, model_name: str) -> None:
    """Extract the archive's ``<model_name>/`` tree into ``dest``.

    The ``data`` filter rejects absolute paths, ``..`` traversal, links that
    escape ``dest``, and device files, so a malformed archive can't write
    outside the cache.
    """
    with tarfile.open(archive_path, "r:bz2") as tar:
        members = [
            m
            for m in tar.getmembers()
            if m.name == model_name or m.name.startswith(model_name + "/")
        ]
        if not members:
            raise RuntimeError(
                f"Archive for sherpa-onnx model {model_name!r} has no "
                f"{model_name}/ directory"
            )
        tar.extractall(dest, members=members, filter="data")
