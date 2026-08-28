"""Pure-logic tests for the latency log viewer window (MCC-58).

Follows the pattern in test_dictionary_editor.py: GTK widget construction
isn't exercised (no display in CI), only the plain functions the window's
callbacks delegate to.
"""

from verbal_code.log_viewer import _extract_latency_lines, _read_latency_log


class TestExtractLatencyLines:
    def test_keeps_only_latency_lines(self):
        lines = [
            "2026-08-28 [INFO] verbal_code: Starting Verbal Code v1.0\n",
            "2026-08-28 [INFO] verbal_code: dictation_latency_ms=142\n",
            "2026-08-28 [INFO] verbal_code: System tray started\n",
            "2026-08-28 [INFO] verbal_code: dictation_latency_ms=98\n",
        ]

        result = _extract_latency_lines(lines)

        assert result == [lines[1], lines[3]]

    def test_no_latency_lines_returns_empty(self):
        lines = ["2026-08-28 [INFO] verbal_code: Starting Verbal Code v1.0\n"]

        assert _extract_latency_lines(lines) == []

    def test_empty_input_returns_empty(self):
        assert _extract_latency_lines([]) == []


class TestReadLatencyLog:
    def test_no_path_returns_empty(self):
        assert _read_latency_log(None) == []

    def test_missing_file_returns_empty(self, tmp_path):
        missing = tmp_path / "does-not-exist.log"

        assert _read_latency_log(str(missing)) == []

    def test_reads_and_strips_latency_lines(self, tmp_path):
        log = tmp_path / "verbal-code.log"
        log.write_text(
            "2026-08-28 [INFO] verbal_code: Starting Verbal Code v1.0\n"
            "2026-08-28 [INFO] verbal_code: dictation_latency_ms=142\n"
            "2026-08-28 [INFO] verbal_code: dictation_latency_ms=98\n"
        )

        result = _read_latency_log(str(log))

        assert result == [
            "2026-08-28 [INFO] verbal_code: dictation_latency_ms=142",
            "2026-08-28 [INFO] verbal_code: dictation_latency_ms=98",
        ]

    def test_truncates_to_max_lines(self, tmp_path):
        log = tmp_path / "verbal-code.log"
        log.write_text(
            "".join(f"dictation_latency_ms={i}\n" for i in range(10))
        )

        result = _read_latency_log(str(log), max_lines=3)

        assert result == [
            "dictation_latency_ms=7",
            "dictation_latency_ms=8",
            "dictation_latency_ms=9",
        ]
