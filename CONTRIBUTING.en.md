# Contributing

English | [简体中文](CONTRIBUTING.md)

Thank you for improving audiobook-generator. By participating, you agree to
follow the [Code of Conduct](CODE_OF_CONDUCT.md). Do not open a public issue
for a security concern; report it privately under the
[security policy](SECURITY.md).

## Before contributing

- Submit only code, text, and assets that you have the right to publish.
- Never submit commercial book text, scraped pages, private character maps,
  real audio, run output, personal paths, IP addresses, cookies, tokens, or API
  keys.
- Examples and fixtures must be short, synthetic, original, and must not
  imitate a real person.
- Features that bypass login, paywalls, DRM, robots.txt, or access controls are
  not accepted.
- Do not add built-in search or scraping adapters for third-party content
  sites. Generic web support must remain explicit, allowlisted, and safe by
  default.

If the direction is uncertain, open a short issue describing the problem,
expected behavior, and alternatives first. Do not paste sensitive data or
copyrighted text into that issue.

## Development setup

```bash
python -m venv .venv
# After activating it as shown in the README:
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The project supports Python 3.10+. `src/audiobook_generator/` is the only
production source tree; do not add a second implementation as an executable
script at the repository root. Read [AGENTS.md](AGENTS.md) for architecture
and security constraints before making changes.

## Suggested workflow

1. Create a short-lived branch from a current, clean `main`.
2. Keep one pull request focused on one clear problem.
3. Add or update offline tests, then implement the smallest effective change.
4. Update both language versions of the docs and examples when public CLI,
   JSON schemas, or defaults change.
5. Run all quality and pre-publication checks before submitting.

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/audiobook_generator
pytest
python -m build
python -m twine check dist/*
python scripts/prepublish_check.py
pip-audit
python -X utf8 -m detect_secrets scan --no-verify
```

Local secret scanning defaults to Git-tracked files, forces UTF-8, and disables
online verification. Do not use `--all-files` in a workspace containing private
data. Review every result in the output JSON; exit code 0 does not mean there
are no findings. CI also uses `--all-files` in a clean checkout to cover package
metadata and fails on unaudited results.

The pytest configuration measures branch coverage and requires at least 80%
overall. New behavior should cover success, input failure, and security
boundaries rather than relying on the aggregate number alone.

## Test rules

- Tests must be completely offline. Use fake clients, local synthetic HTML,
  and short WAV files generated at runtime.
- Never contact a real website, OpenAI, or any paid API from a test.
- Use reserved domains such as `example.org` and synthetic text, not real
  service endpoints or excerpts from published works.
- Network tests should cover HTTPS, the domain allowlist, robots.txt, redirect
  revalidation, private-address blocking, rate limits, and response limits.
- Path tests should cover absolute paths, `..`, symlink escapes, empty files,
  and oversized chapters.
- Audio tests should cover streaming merge of compatible WAV files, format
  mismatch, corrupt caches, and interrupted-run recovery.
- API tests should assert only sanitized errors. Logs and exceptions must not
  contain keys or input text.

## Code and interface conventions

- Type Python code and pass Ruff formatting and static checks.
- Validate every external input before use. Errors should be actionable but
  must never echo secrets or source text.
- Public JSON formats use `schema_version: 1`; unknown fields and unsafe paths
  should be rejected explicitly.
- The v0.1 audio boundary is WAV only. Do not silently add unvalidated formats.
- Use the official OpenAI SDK. Responses calls retain structured output and
  `store=False`; TTS output is validated before atomic replacement.
- A new dependency needs a concrete reason and review of security, license,
  maintenance, and supported Python versions.

## Documentation and user experience

When a user-facing command, error, configuration field, or safety rule changes,
update both `README.md` and `README.en.md`. Keep both contribution guides in
sync when this workflow changes. Examples must be copyable and must not point
at a contributor's personal directory.

User-facing audio workflows must retain the AI-voice disclosure. Do not
describe a preset voice as a person or add defaults that imitate a named
person.

## Pull request checklist

A PR description should cover the problem, solution, user-visible behavior,
risks, test results, and whether the CLI or a schema changes. Before submitting:

- [ ] The change is focused and contains no unrelated formatting or generated files.
- [ ] New behavior has offline tests and all checks pass.
- [ ] No secret, private path, real endpoint, commercial text, or media is present.
- [ ] CLI, schema, and default changes are reflected in both languages and examples.
- [ ] Safety boundaries, cost confirmation, privacy, and AI-voice disclosure remain intact.
- [ ] `python scripts/prepublish_check.py` passes.

Maintainers may ask for a large PR to be split. Merge and release decisions
remain with the maintainers; accepted code is not guaranteed an immediate
release.

## License

Accepted contributions are distributed under the project's
[MIT License](LICENSE). By submitting a contribution, you represent that you
have the right to provide it under that license.
