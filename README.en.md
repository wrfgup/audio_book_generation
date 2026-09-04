# audiobook-generator

English | [简体中文](README.md)

A local-first, resumable command-line tool for multi-speaker audiobooks. It
turns UTF-8 text that you are allowed to use, or explicitly configured and
authorized web pages, into a standard book directory. It can then use the
OpenAI Responses API to identify speakers and the Speech API to produce WAV
audio.

> [!IMPORTANT]
> Process only content that you created, are licensed to use, or may otherwise
> lawfully use. Do not scrape paywalls, DRM-protected material, or sites that
> prohibit automated access. Never commit commercial book text, private audio,
> API keys, or run directories to this repository.

> [!NOTE]
> The generated voices are AI-generated, not recordings of people. You must
> clearly disclose this to listeners whenever you publish or play the output.
> OpenAI's [text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech)
> also requires this disclosure.

## Audio demo

Click the player below to hear a **1 minute 26 second** excerpt. This is
**AI-generated speech, not a human recording**, produced with **CosyVoice** in
an earlier experimental version. It does not represent output from the current
OpenAI-based CLI, which defaults to OpenAI `gpt-4o-mini-tts`.

https://github.com/user-attachments/assets/81e0467d-1558-4301-b052-152600844eee

The demo media is not covered by the code's MIT license. Verify the applicable
rights separately before using or redistributing it.

## Features

- Import one `.txt` file or a directory of `.txt` files locally.
- Split on common chapter headings, including Chinese headings; preserve text
  without a heading as one chapter.
- Scrape authorized HTTPS pages from an explicit site configuration. There is
  no built-in site search, login, cookie, paywall, or DRM bypass.
- Identify narration and dialogue speakers with rules or the OpenAI Responses
  API.
- Generate and merge WAV through the OpenAI Speech API. Content-addressed
  caches make interrupted jobs resumable.
- Show chapter count, character count, estimated request count, and cache hits
  before making a paid request.
- Strictly validate every public JSON format with `schema_version: 1`.

## Data flow

```text
Authorized local text ── import-text ─┐
                                     ├── standard book ── validate ── build ── WAV + manifests
Authorized HTTPS pages ── scrape ────┘
```

Importing, validation, and `build --dry-run` need no API key. Only the LLM and
TTS stages of `build` send text to the configured API service.

## Requirements and installation

- Python 3.10 or newer
- A working OpenAI API key and the required API access when generating audio

Install from source:

```bash
python -m venv .venv
```

Activate the environment for your platform:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Then install into the activated environment:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

Verify the installation:

```bash
audiobook --version
python -m audiobook_generator --version
```

## Quick start: local text

This example uses only your own text:

```bash
audiobook import-text ./my-book.txt --output ./work/book \
  --title "My Story" --author "Author Name"

audiobook validate --book ./work/book

audiobook build --input ./work/book --output ./work/audio --dry-run
```

`import-text` also accepts a directory. Its `.txt` files are imported in a
stable order:

```bash
audiobook import-text ./my-chapters --output ./work/book
```

The imported book looks like this:

```text
work/book/
├── book.json
└── chapters/
    ├── 0001.txt
    └── 0002.txt
```

After reviewing the dry-run estimates and limits, configure the API and build:

```bash
# Linux / macOS
export OPENAI_API_KEY="example-api-key"

# Windows PowerShell
$env:OPENAI_API_KEY = "example-api-key"

audiobook build --input ./work/book --output ./work/audio
```

The bundled default voice configuration uses only OpenAI preset voices and
does not imitate a real person. To use your own character mapping, copy the
example outside the repository and pass it explicitly:

```bash
audiobook validate --voices ./local/voices.json
audiobook build --input ./work/book --output ./work/audio \
  --voices ./local/voices.json
```

## Scraping authorized pages

Scraping is optional. The start URL, domain allowlist, and CSS selectors must
all be present in the site configuration. The CLI does not accept an ad hoc
URL and does not provide site search:

```bash
cp configs/site.example.json ./local/site.json
# Edit ./local/site.json for a site you are authorized to scrape.
audiobook validate --site-config ./local/site.json
audiobook scrape --site-config ./local/site.json --output ./work/book
```

The scraper requires HTTPS and enforces a domain allowlist, robots.txt,
revalidation of every redirect, blocking of private and loopback addresses, a
response-size limit, and a request interval of at least 0.5 seconds. It does
not bypass authentication, cookie restrictions, paywalls, or DRM. Permission
to access a site and robots.txt rules are not copyright licenses; you remain
responsible for confirming both.

## Validation

`validate` requires at least one target and can validate several targets in a
single invocation:

```bash
audiobook validate \
  --book ./work/book \
  --site-config ./local/site.json \
  --voices ./local/voices.json
```

In a standard book directory, each chapter must be a relative `.txt` path
below `chapters/`. Validation rejects absolute paths, `..`, symlink escapes,
duplicate indexes, empty text, and chapters larger than 5 MiB.

### JSON configuration and data formats

The minimal `book.json` shape is shown below. Web sources may add sanitized
`url` and `source_url` values to the source and chapter records:

```json
{
  "schema_version": 1,
  "source": { "type": "local_text" },
  "book": { "title": "Original Example", "author": "Example Author" },
  "chapters": [
    { "index": 1, "title": "Chapter One", "file": "chapters/0001.txt" }
  ]
}
```

A site configuration fixes the entry point, allowlist, selectors, and request
pace:

```json
{
  "schema_version": 1,
  "start_url": "https://example.org/my-authorized-book/",
  "allowed_domains": ["example.org"],
  "selectors": {
    "book_title": "h1",
    "chapter_links": ".chapters a",
    "chapter_content": "article",
    "author": ".author",
    "chapter_title": "h1"
  },
  "request_interval_seconds": 0.5,
  "user_agent": "audiobook-generator/0.1",
  "max_chapters": 20
}
```

A voice configuration contains `schema_version`, `narrator`, `male`, `female`,
and optional `default_dialogue` and `characters`. Each voice entry has a
`voice` and non-impersonating `instructions`. Copy `voices.example.json` as a
starting point. All schemas reject unknown fields so spelling and version
mistakes fail early.

## Build options

```text
audiobook build --input DIR --output DIR
                [--voices FILE]
                [--env-file FILE]
                [--chapters 1,3-5]
                [--speaker-mode auto|llm|rules]
                [--dry-run] [--yes] [--force]
                [--max-chapters N]
                [--max-tts-characters N]
```

- `--voices` uses the bundled, non-impersonating profile when omitted.
- `--env-file` optionally loads a dotenv file; existing environment variables
  take precedence. Keep that file local.
- `--chapters` selects positive chapter indexes in a form such as `1,3-5`.
- `--speaker-mode auto` is the default. Recoverable LLM failures produce a
  warning and fall back to rule-based detection; authentication and
  configuration failures stop immediately.
- `--speaker-mode llm` requires the LLM and never silently falls back.
- `--speaker-mode rules` detects speakers offline without LLM cost. TTS still
  requires the API.
- `--dry-run` validates and estimates without paid requests or an API key.
- `--yes` skips the interactive confirmation and is required in a
  non-interactive environment. It never bypasses hard chapter or character
  limits.
- `--force` regenerates TTS cache entries and output, while preserving safety
  and cost limits.
- `--max-chapters` and `--max-tts-characters` are hard cost guardrails for the
  current build. They default to 100 chapters and 1,000,000 characters. The
  chapter limit itself cannot exceed 10,000, preventing an accidental huge
  range from exhausting memory before validation.

By default, the CLI prints the plan and asks for confirmation before any paid
call. Model prices and account limits can change; check OpenAI's current
[model and pricing information](https://developers.openai.com/api/docs/models)
before a run.

Process exit codes are `0` for success, `2` for argument/configuration/input
errors, and `1` for network/API/build failures. Scripts should consume the
exit code rather than parse potentially localized error text.

## OpenAI configuration

Inject secrets through the environment. Never put a real value in
`.env.example`, JSON files, shell history, or logs:

```env
OPENAI_API_KEY=example-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_LLM_MODEL=gpt-5.6-luna
```

- The default TTS model is `gpt-4o-mini-tts`, used through the Speech API to
  produce WAV.
- The default speaker model is `gpt-5.6-luna`, used through the Responses API
  with a strict JSON Schema and `store=False`.
- Version 0.1 accepts and produces WAV only; MP3 and other output formats are
  not supported.
- Models can be overridden through environment variables. Availability,
  charges, and limits depend on your account.

### Security warning for compatible endpoints

When you set `OPENAI_BASE_URL`, the API key and the text being processed are
sent to that endpoint. Use only a service you fully trust. Custom remote URLs
must use HTTPS; HTTP is allowed only for loopback development addresses. URLs
with user information, query strings, or fragments are rejected.

## Output, caching, and recovery

Build output contains chapter WAV files, segment WAV files, chapter manifests,
and a book manifest. Manifests contain only relative POSIX paths, character
counts, SHA-256 values, voices, cache identifiers, and `ai_generated: true`.
They do not store segment text, absolute paths, or URLs with query strings.

LLM and TTS cache keys cover the input content, model, voice, instructions,
speed, and implementation version. Valid output is reused for an identical
configuration. A content or configuration change, or corrupt cache entry,
causes a rebuild. Audio is written to a temporary file and atomically replaces
the destination only after WAV validation, so rerunning after an interruption
is normally safe.

Output directories, caches, and manifests can still reveal titles, character
names, text lengths, or work habits. Treat them as private data and never
commit or package them with the repository.

## Privacy, cost, and content responsibility

- `import-text` and `validate` do not upload local book data.
- LLM speaker detection and TTS send relevant text to OpenAI or the compatible
  endpoint you configured.
- `store=False` controls the Responses API storage option; it is not a
  substitute for reviewing the selected service's data terms and privacy
  policy.
- Caching can reduce repeat calls but does not guarantee the final charge. The
  provider's bill is authoritative.
- Do not use a preset voice to impersonate a person or claim that generated
  output is human-recorded.
- When publishing audio, include a clear notice such as “This audio contains
  AI-generated voices.”
- You are responsible for the legality of the text, scraping, voice use, and
  resulting audio in your jurisdiction.

## Troubleshooting

**Missing `OPENAI_API_KEY`**

Use `--dry-run` to verify the local pipeline. Set the environment variable in
the current shell before a real build.

**A custom endpoint is rejected**

Make sure a remote URL is HTTPS and has no user information, query, or
fragment. Private network addresses and plain-HTTP remote endpoints are
intentionally blocked.

**Scraping fails**

Run `validate --site-config`, then check automated-access permission, the
domain allowlist, CSS selectors, and whether a redirect leaves the allowlist.
The tool will not help bypass access controls.

**WAV merge fails or the cache is repeatedly rebuilt**

Segment WAV files must have matching channel count, sample width, sample rate,
and compression type. Corrupt or incompatible entries are not reusable. Use
`--force` when you intentionally need a clean rebuild.

**A non-interactive build stops before confirmation**

Review the dry-run plan, pass `--yes`, and set appropriate `--max-chapters`
and `--max-tts-characters` limits.

## Development and contributions

Install development dependencies and run the checks:

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/audiobook_generator
pytest
python scripts/prepublish_check.py
```

Tests must be offline: never contact a real website or OpenAI, and never use
copyrighted book text as a fixture. See the [contribution guide](CONTRIBUTING.en.md),
[security policy](SECURITY.md), and [Code of Conduct](CODE_OF_CONDUCT.md).

## Important repository-release warning

Do not archive, mirror, or directly upload the current working directory, and
do not copy its existing `.git`. Private text, audio, runs, and local ignore
rules may still exist locally. Maintainers must create a separate release
candidate from an explicit public-file allowlist, run
`python scripts/prepublish_check.py`, and initialize a new `main` history from
that candidate. See the [maintainer release checklist](docs/maintainer-release.md).

## Security and license

Do not report key exposure, SSRF, path escape, or similar vulnerabilities in a
public issue. Use GitHub Private Vulnerability Reporting as described in
[SECURITY.md](SECURITY.md).

This project is licensed under the [MIT License](LICENSE).
