# Slice 0: Project Scaffold & Config Loading

## Goal
Set up the project structure, config loading, CLI argument parsing, and logging. Running `python -m verbal_code` should parse config.yaml, set up logging, and print "Verbal Code v0.1.0 ready" then exit cleanly on Ctrl+C.

## Acceptance Criteria
- [ ] `verbal_code/` package with `__init__.py` (version = "0.1.0"), `__main__.py`, `app.py`
- [ ] `config.yaml` at project root with all sections (hotkey, stt, audio, injection, vad, tray, logging) — values can be placeholders
- [ ] `app.py` has `load_config(path)` that reads YAML, searches `~/.config/verbal-code/config.yaml` then `./config.yaml`
- [ ] `app.py` has `main()` entry point with argparse: `-c/--config`, `--list-devices`, `--version`
- [ ] Logging configured from `config.logging.level` and `config.logging.file`
- [ ] `pyproject.toml` with `[project.scripts] verbal-code = "verbal_code.app:main"`
- [ ] `requirements.txt` with `PyYAML>=6.0` and `numpy>=1.24`
- [ ] Running `python -m verbal_code` loads config, logs "Starting Verbal Code v0.1.0", blocks on a sleep loop, exits cleanly on SIGINT/SIGTERM

## Files to Create
```
verbal_code/
├── config.yaml
├── pyproject.toml
├── requirements.txt
└── verbal_code/
    ├── __init__.py
    ├── __main__.py
    └── app.py
```

## Technical Notes
- Use `PyYAML` for config parsing
- `signal.signal(SIGINT, ...)` and `signal.signal(SIGTERM, ...)` for clean shutdown
- Config should return sensible defaults if keys are missing (use `.get()` everywhere)
- Python 3.10+ (use `match` or union types if helpful)

## Test It
```bash
pip install PyYAML
python -m verbal_code --version        # prints "Verbal Code 0.1.0"
python -m verbal_code                  # prints ready message, blocks, Ctrl+C exits cleanly
python -m verbal_code -c config.yaml   # loads specific config
```
