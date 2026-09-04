# Repository instructions

These instructions apply to the entire repository.

## Project contract

- Production code lives only in `src/audiobook_generator/`; keep root files as
  packaging, documentation, configuration examples, or tooling.
- The supported CLI is `import-text`, `scrape`, `validate`, and `build`, plus
  `--version` and `python -m audiobook_generator`.
- Local authorized text is the primary input. Web scraping is optional,
  configuration-driven, HTTPS-only, allowlisted, robots-aware, and must never
  bypass login, cookies, paywalls, DRM, or access controls.
- Public book, site, voice, chapter-manifest, and book-manifest JSON uses
  `schema_version: 1`. Reject unknown/unsafe input instead of guessing.
- v0.1 audio input/output is WAV only. Preserve streaming WAV merge, validated
  content-addressed caches, temporary writes, and atomic replacement.
- Use the official OpenAI SDK. TTS defaults to `gpt-4o-mini-tts`; speaker
  inference defaults to `gpt-5.6-luna`, strict structured output, and
  `store=False`. Never weaken paid-call confirmation or hard cost limits.

## Development commands

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/audiobook_generator
pytest
python -m build
python -m twine check dist/*
python scripts/prepublish_check.py
```

Run focused tests while iterating, then the full suite before handoff. Pytest
must retain branch coverage of at least 80%. Do not run formatters in rewrite
mode across unrelated user changes.

## Tests and fixtures

- Tests are offline: no real websites, OpenAI calls, paid APIs, or account
  credentials. Use fake clients and local deterministic fixtures.
- Fixtures must be short, synthetic, original, and use reserved domains. Build
  WAV data at test time; do not commit generated media.
- Cover validation failures and security boundaries, especially path escape,
  symlinks, SSRF/redirects, response limits, cache corruption, and redaction.
- Keep error messages useful without including secrets, input text, absolute
  personal paths, or URL query strings.

## Data and release safety

- Never add API keys, cookies, tokens, private mappings, copyrighted books,
  scraped HTML, run output, caches, logs, or audio. Do not force-add ignored
  data.
- Do not name private local directories or works in tracked files. Keep
  machine-specific exclusions in `.git/info/exclude`.
- Never archive or publish the current working directory and never reuse its
  `.git` for the public repository. Build a separate allowlisted candidate,
  pass `python scripts/prepublish_check.py`, and create a fresh `main` history.
- Do not make live network or paid API calls for verification.

## Review expectations

- Treat changes to URL/path validation, cache keys, atomic writes, cost limits,
  manifests, and log redaction as security-sensitive.
- Keep behavior deterministic where possible, including chapter ordering,
  filenames, and stable voice assignment.
- Update tests and both `README.md` and `README.en.md` for user-visible CLI,
  schema, default, privacy, cost, or disclosure changes. Keep both contribution
  guides aligned.
- Generated audio must remain labeled `ai_generated: true`, and user-facing
  guidance must require clear AI-voice disclosure and prohibit impersonation.
