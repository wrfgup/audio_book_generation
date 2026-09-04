"""Command-line interface for audiobook-generator."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .config import OpenAIConfig, load_voice_config
from .errors import AudiobookError, BuildError, InputError
from .io_utils import DataError, SchemaError
from .pipeline import (
    ABSOLUTE_MAX_CHAPTERS,
    DEFAULT_MAX_CHAPTERS,
    DEFAULT_MAX_TTS_CHARACTERS,
    AudiobookBuilder,
    BuildOptions,
    BuildPlan,
    parse_chapter_selection,
)
from .sources import (
    GenericHTMLSource,
    SourceError,
    SourceNetworkError,
    SourceSecurityError,
    import_text,
    load_book_directory,
    load_site_config,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audiobook",
        description="Build disclosed AI-generated audiobooks from text you are authorized to use.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    importer = commands.add_parser("import-text", help="Import a UTF-8 .txt file or directory.")
    importer.add_argument(
        "input", metavar="INPUT", help="Text file or directory containing .txt files."
    )
    importer.add_argument("--output", required=True, help="Standard book directory to create.")
    importer.add_argument("--title", help="Book title (defaults to the input name).")
    importer.add_argument("--author", help="Optional author name.")
    importer.add_argument(
        "--encoding", default="utf-8-sig", help="Input encoding (default: utf-8-sig)."
    )

    scraper = commands.add_parser("scrape", help="Import an explicitly authorized HTTPS website.")
    scraper.add_argument("--site-config", required=True, help="Versioned site configuration JSON.")
    scraper.add_argument("--output", required=True, help="Standard book directory to create.")

    validator = commands.add_parser(
        "validate", help="Validate local inputs without network or API calls."
    )
    validator.add_argument("--book", help="Standard book directory.")
    validator.add_argument("--site-config", help="Site configuration JSON.")
    validator.add_argument("--voices", help="Voices configuration JSON.")

    builder = commands.add_parser(
        "build", help="Generate WAV chapters from a standard book directory."
    )
    builder.add_argument(
        "--input", required=True, help="Directory containing book.json and chapters/."
    )
    builder.add_argument("--output", required=True, help="Build output directory.")
    builder.add_argument(
        "--voices", help="Voices JSON; defaults to the bundled non-imitating profile."
    )
    builder.add_argument(
        "--env-file", help="Optional dotenv file. Environment variables take precedence."
    )
    builder.add_argument("--chapters", help="Chapter indexes such as 1,3-5.")
    builder.add_argument(
        "--speaker-mode",
        choices=("auto", "llm", "rules"),
        default="auto",
        help="Speaker detection mode (default: auto).",
    )
    builder.add_argument(
        "--dry-run", action="store_true", help="Validate and print a request estimate only."
    )
    builder.add_argument(
        "--yes", action="store_true", help="Approve the displayed paid-call estimate."
    )
    builder.add_argument(
        "--force", action="store_true", help="Regenerate TTS cache entries and outputs."
    )
    builder.add_argument(
        "--max-chapters",
        type=int,
        default=DEFAULT_MAX_CHAPTERS,
        help=(
            f"Hard selected-chapter limit (default: {DEFAULT_MAX_CHAPTERS}; "
            f"maximum: {ABSOLUTE_MAX_CHAPTERS})."
        ),
    )
    builder.add_argument(
        "--max-tts-characters",
        type=int,
        default=DEFAULT_MAX_TTS_CHARACTERS,
        help=f"Hard input character limit (default: {DEFAULT_MAX_TTS_CHARACTERS}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "import-text":
            metadata = import_text(
                args.input,
                args.output,
                title=args.title,
                author=args.author,
                encoding=args.encoding,
            )
            print(f"Imported book metadata: {metadata}")
            return 0

        if args.command == "scrape":
            config = load_site_config(args.site_config)
            metadata = GenericHTMLSource(config).scrape_to_dir(args.output)
            print(f"Imported authorized web content: {metadata}")
            return 0

        if args.command == "validate":
            return _validate_inputs(args, parser)

        if args.command == "build":
            return _run_build(args)

        parser.error("unknown command")
    except (InputError, DataError, SchemaError, SourceSecurityError) as exc:
        _print_error(str(exc) or "Invalid input or configuration.")
        return 2
    except ValueError:
        _print_error("Invalid input or configuration.")
        return 2
    except (BuildError, SourceNetworkError, SourceError) as exc:
        _print_error(str(exc) or "Build failed.")
        return 1
    except OSError:
        _print_error("A local file operation failed.")
        return 1
    except AudiobookError as exc:
        _print_error(str(exc) or "Audiobook operation failed.")
        return 1


def _validate_inputs(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not any((args.book, args.site_config, args.voices)):
        parser.error("validate requires --book, --site-config, and/or --voices")
    if args.book:
        book, chapters = load_book_directory(args.book)
        print(f"Book is valid: {book.book.title} ({len(chapters)} chapter(s))")
    if args.site_config:
        load_site_config(args.site_config)
        print("Site configuration is valid (offline validation only).")
    if args.voices:
        load_voice_config(args.voices)
        print("Voices configuration is valid.")
    return 0


def _run_build(args: argparse.Namespace) -> int:
    config = OpenAIConfig.from_env(args.env_file)
    options = BuildOptions(
        chapter_indexes=parse_chapter_selection(args.chapters),
        speaker_mode=args.speaker_mode,
        dry_run=args.dry_run,
        force=args.force,
        max_chapters=args.max_chapters,
        max_tts_characters=args.max_tts_characters,
    )
    builder = AudiobookBuilder(config, args.voices)
    plan = builder.plan_from_book_dir(args.input, args.output, options)
    _print_plan(plan)
    if args.dry_run:
        print("Dry run complete; no API request was made.")
        return 0

    if (plan.paid_llm_requests or plan.paid_tts_requests) and not args.yes:
        if not sys.stdin.isatty():
            raise InputError("Non-interactive paid builds require --yes.")
        answer = input("Proceed with the estimated paid API calls? [y/N] ").strip().casefold()
        if answer not in {"y", "yes"}:
            print("Build cancelled; no API request was made.")
            return 0

    report = builder.build_from_book_dir(
        args.input,
        args.output,
        options,
        approved_plan=plan,
    )
    if report.book_manifest_path is None:
        raise BuildError("Build finished without a book manifest.")
    print(f"Built {len(report.chapters)} chapter(s): {report.book_manifest_path}")
    return 0


def _print_plan(plan: BuildPlan) -> None:
    print("Build estimate:")
    print(f"  chapters: {plan.chapter_count}")
    print(f"  characters: {plan.character_count}")
    print(
        "  LLM requests: "
        f"{plan.estimated_llm_requests} ({plan.llm_cache_hits} cache hit(s), "
        f"{plan.paid_llm_requests} estimated paid)"
    )
    print(
        "  TTS requests: "
        f"{plan.estimated_tts_requests} ({plan.tts_cache_hits} cache hit(s), "
        f"{plan.paid_tts_requests} estimated paid)"
    )


def _print_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
