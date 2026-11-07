"""Command-line entry point for soase-validator.

The commands translate arguments and printed output only. Every decision is
made by the Engine facade.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from soase_validator import __version__
from soase_validator.engine.chain import ChainProblem
from soase_validator.engine.facade import Engine
from soase_validator.engine.manifests import format_plan
from soase_validator.engine.model import Diagnostic, Severity
from soase_validator.engine.versions import (
    DEFAULT_REBELLION,
    GameVersion,
    parse_game_version,
)
from soase_validator.reports import (
    build_report,
    diagnostic_to_dict,
    format_json,
    format_text,
    summary_line,
    write_report,
)

_DEFAULT_VERSION = DEFAULT_REBELLION.value


def _print_error(message: str) -> None:
    """Print an error line to stderr.

    Args:
        message: The text after the ``error:`` prefix.
    """
    print(f"error: {message}", file=sys.stderr)


def _print_problem(problem: ChainProblem) -> None:
    """Print a Reference Root warning to stderr.

    Args:
        problem: The problem reported by the Engine.
    """
    print(f"warning: {problem.code}: {problem.message}", file=sys.stderr)


def _parse_version(text: str) -> GameVersion:
    """Parse a Game Version argument.

    Args:
        text: The name given on the command line.

    Returns:
        The matching Game Version.

    Raises:
        ValueError: If the name is not recognised.
    """
    version = parse_game_version(text)
    if version is None:
        raise ValueError(f"unknown game version '{text}'")
    return version


def _interactive(args: argparse.Namespace) -> bool:
    """Decide whether ``init`` may prompt.

    Args:
        args: The parsed arguments.

    Returns:
        True when prompting is allowed and both stdin and stdout are terminals.
    """
    return not args.no_prompt and sys.stdin.isatty() and sys.stdout.isatty()


def _ask(question: str) -> str:
    """Read one answer from the terminal.

    Args:
        question: The prompt text.

    Returns:
        The trimmed answer; empty when the user skips the question.
    """
    return input(f"{question}: ").strip()


def _split_list(answer: str) -> list[str]:
    """Split a comma-separated answer.

    Args:
        answer: The raw answer.

    Returns:
        The non-empty trimmed entries.
    """
    return [part.strip() for part in answer.split(",") if part.strip()]


def _run_init(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``init``: write ``soase.json`` in a directory.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        The process exit code.
    """
    directory = Path(args.path)
    game_version: str | None = args.game_version
    reference_root: str | None = args.reference_root
    mod_roots: list[str] = list(args.mod_root)
    layers: list[str] = list(args.layer)
    if _interactive(args):
        if game_version is None:
            game_version = _ask(f"Game Version [{_DEFAULT_VERSION}]") or None
        if reference_root is None:
            reference_root = _ask("Reference Root (Enter to skip)") or None
        if not mod_roots:
            mod_roots = _split_list(_ask("Mod Roots, comma-separated (Enter to skip)"))
        if not layers:
            layers = _split_list(_ask("Parent Layers, comma-separated (Enter to skip)"))
    try:
        version = None if game_version is None else _parse_version(game_version)
        result = engine.configure_project(
            directory,
            game_version=version,
            reference_root=reference_root,
            layers=layers or None,
            mod_roots=mod_roots or None,
            language=args.language,
            overwrite=args.overwrite,
        )
    except (ValueError, OSError) as error:
        _print_error(str(error))
        return 1
    print(f"{'Created' if result.created else 'Updated'} {result.file}")
    for label, keys in (
        ("set", result.set_keys),
        ("skipped (different value present; use --overwrite)", result.skipped_keys),
        ("unchanged", result.unchanged_keys),
    ):
        if keys:
            print(f"  {label}: {', '.join(keys)}")
    if reference_root is not None:
        problem = engine.reference_root_problem(result.file, reference_root)
        if problem is not None:
            _print_problem(problem)
    elif result.default_reference_root is not None:
        print(f"Reference Root: using the user-level default {result.default_reference_root}")
    else:
        print(
            "No Reference Root configured. Add one later with: "
            "soase-validator config set-reference-root <path> [--game-version <version>] [--user]"
        )
    return 0


def _run_set_reference_root(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``config set-reference-root``.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        The process exit code.
    """
    try:
        version = _parse_version(args.game_version)
        file = engine.set_reference_root(Path(args.path), version, args.root, user=args.user)
    except (ValueError, OSError) as error:
        _print_error(str(error))
        return 1
    problem = engine.reference_root_problem(file, args.root)
    if problem is not None:
        _print_problem(problem)
    print(f"Saved the {version.value} Reference Root in {file}")
    return 0


def _run_config_show(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``config show``: print the effective configuration.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        The process exit code.
    """
    location = Path(args.path)
    report = engine.effective_config(location)
    print("Settings:")
    for entry in report.entries:
        origin = entry.source.kind.value
        if entry.source.path is not None:
            origin = f"{origin}: {entry.source.path}"
        print(f"  {entry.name} = {entry.value}  ({origin})")
    print("Reference Roots:")
    if report.reference_roots_found:
        for name, found in report.reference_roots_found.items():
            print(f"  {name}: {'found' if found else 'not found'}")
    else:
        print("  none configured")
    print("Configuration files:")
    for file in report.project_files:
        print(f"  project: {file}")
    if report.user_file is not None:
        print(f"  user: {report.user_file}")
    if report.settings.problems:
        print("Problems:")
        for problem in report.settings.problems:
            print(f"  {problem.setting}: {problem.message}")
    print("Chain (lowest first):")
    for layer in engine.chain_layers(location):
        print(f"  {layer.name} [{layer.kind}, {layer.status}] {layer.path}")
    return 0


def _format_diagnostic(diagnostic: Diagnostic) -> str:
    """Render a Diagnostic as one line with one-based positions.

    Args:
        diagnostic: The Diagnostic.

    Returns:
        ``file:line:col: severity code: message``.
    """
    start = diagnostic.range.start
    return (
        f"{diagnostic.file}:{start.line + 1}:{start.col + 1}: "
        f"{diagnostic.severity.value} {diagnostic.code}: {diagnostic.message}"
    )


def _collect_diagnostics(
    paths: Sequence[Path], engine: Engine
) -> list[tuple[Path, list[Diagnostic]]]:
    """Validate files and directories through the Engine.

    Args:
        paths: Existing files and directories.
        engine: The Engine.

    Returns:
        The Diagnostics per file in argument order, including files with
        none; files of a directory follow the Engine's order.
    """
    found: list[tuple[Path, list[Diagnostic]]] = []
    for path in paths:
        if path.is_dir():
            found.extend(engine.validate_directory(path).items())
        else:
            found.append((path, engine.validate_file(path)))
    return found


def _write_validation_report(
    results: Sequence[tuple[Path, list[Diagnostic]]], args: argparse.Namespace
) -> int | None:
    """Write the report of ``validate --output`` and print its summary line.

    A file that appears under several PATHs is reported once.

    Args:
        results: The per-file Diagnostics.
        args: The parsed arguments.

    Returns:
        None on success, otherwise the exit code of the failure.
    """
    report = build_report(dict(results))
    target = Path(args.output)
    text = format_json(report) if args.format == "json" else format_text(report)
    try:
        write_report(target, text)
    except OSError as error:
        _print_error(f"cannot write report: {error}")
        return 2
    print(f"{summary_line(report)}; report: {target}")
    return None


def _run_validate(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``validate``: print the Diagnostics of files and directories.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        1 when any Diagnostic is an error, 2 when a path does not exist, the
        Game Version is unknown or the report cannot be written, otherwise 0.
    """
    paths = [Path(item) for item in (args.paths or [args.path])]
    missing = [path for path in paths if not path.exists()]
    if missing:
        for path in missing:
            _print_error(f"path does not exist: {path}")
        return 2
    if args.game_version is not None:
        try:
            version = _parse_version(args.game_version)
        except ValueError as error:
            _print_error(str(error))
            return 2
        engine.set_editor_settings({"gameVersion": version.value})
    results = _collect_diagnostics(paths, engine)
    diagnostics = [item for _, found in results for item in found]
    errors = sum(1 for item in diagnostics if item.severity is Severity.ERROR)
    if args.output is not None:
        failure = _write_validation_report(results, args)
        if failure is not None:
            return failure
    elif args.format == "json":
        print(json.dumps({"diagnostics": [diagnostic_to_dict(item) for item in diagnostics]}))
    else:
        for diagnostic in diagnostics:
            start = diagnostic.range.start
            print(
                f"{diagnostic.file}:{start.line + 1}:{start.col + 1}: "
                f"{diagnostic.severity.value} {diagnostic.code} {diagnostic.message}"
            )
    if args.format == "text" and args.output is None:
        print(f"{len(diagnostics)} diagnostics, {errors} errors", file=sys.stderr)
    return 1 if errors else 0


def _run_manifest_check(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``manifest check``: print manifest Diagnostics.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        1 when any Diagnostic is an error, otherwise 0.
    """
    diagnostics = engine.manifest_check(Path(args.path))
    for diagnostic in diagnostics:
        print(_format_diagnostic(diagnostic))
    errors = sum(1 for item in diagnostics if item.severity is Severity.ERROR)
    print(f"{len(diagnostics)} manifest diagnostics, {errors} errors")
    return 1 if errors else 0


def _run_manifest_sync(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``manifest sync``: print the planned changes and optionally write.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        0 on success, including a dry run with pending changes; 1 when
        planning or writing fails.
    """
    try:
        plan = engine.manifest_plan(Path(args.path), remove_stale=args.remove_stale)
        text = format_plan(plan)
        if text:
            print(text, end="")
        removals = [edit for edit in plan.edits if edit.removed]
        if removals:
            print("Entries to remove:" if not args.write else "Entries removed:")
            for edit in removals:
                for name in edit.removed:
                    print(f"  {edit.manifest_path.name}: {name}")
        if not plan.edits and not plan.advisories:
            print("Manifests are in sync.")
            return 0
        if not args.write:
            if plan.edits:
                print("Dry run: nothing written. Use --write to apply.")
            return 0
        for record in engine.manifest_apply(plan):
            print(f"Wrote {record.manifest_path} (backup: {record.backup_path})")
    except (ValueError, OSError) as error:
        _print_error(str(error))
        return 1
    return 0


def _run_versions(args: argparse.Namespace, engine: Engine) -> int:
    """Run ``versions``: list Game Versions with their audit status.

    Args:
        args: The parsed arguments.
        engine: The Engine.

    Returns:
        The process exit code.
    """
    listing = engine.version_listing()
    print("Game Versions:")
    for item in listing.versions:
        print(f"  {item.version.value}: {item.name} ({item.label})")
    print("Unverified gate tokens:")
    if listing.unverified_tokens:
        for token in listing.unverified_tokens:
            print(f"  {token}")
    else:
        print("  none")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every command.

    Returns:
        The parser. Each subcommand stores its handler in ``args.handler``.
    """
    parser = argparse.ArgumentParser(
        prog="soase-validator",
        description="Validate Sins of a Solar Empire mod files.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    init = commands.add_parser("init", help="create soase.json in a directory")
    init.add_argument("--path", default=".", help="project directory (default: current)")
    init.add_argument("--game-version", help=f"Game Version (default: {_DEFAULT_VERSION})")
    init.add_argument("--reference-root", help="base game data directory for the Game Version")
    init.add_argument("--mod-root", action="append", default=[], help="Mod Root (repeatable)")
    init.add_argument(
        "--layer", action="append", default=[], help="parent Layer, lowest first (repeatable)"
    )
    init.add_argument("--language", help="localization folder name")
    init.add_argument(
        "--overwrite", action="store_true", help="replace values that differ from the options"
    )
    init.add_argument("--no-prompt", action="store_true", help="never prompt")
    init.set_defaults(handler=_run_init)

    config = commands.add_parser("config", help="view or change configuration")
    config_commands = config.add_subparsers(
        dest="config_command", metavar="<subcommand>", required=True
    )
    setter = config_commands.add_parser(
        "set-reference-root", help="set the Reference Root of a Game Version"
    )
    setter.add_argument("root", help="base game data directory")
    setter.add_argument(
        "--game-version",
        default=_DEFAULT_VERSION,
        help=f"Game Version (default: {_DEFAULT_VERSION})",
    )
    setter.add_argument("--path", default=".", help="project file or directory (default: current)")
    setter.add_argument(
        "--user", action="store_true", help="store as the user-level default instead"
    )
    setter.set_defaults(handler=_run_set_reference_root)
    show = config_commands.add_parser("show", help="print the effective configuration")
    show.add_argument("--path", default=".", help="project file or directory (default: current)")
    show.set_defaults(handler=_run_config_show)

    validate = commands.add_parser(
        "validate", help="validate mod files and directories; exit 1 when there are errors"
    )
    validate.add_argument("paths", nargs="*", metavar="PATH", help="files or directories")
    validate.add_argument(
        "--path",
        default=".",
        help="directory validated when no PATH is given (default: current)",
    )
    validate.add_argument(
        "--game-version",
        help="Game Version used when no soase.json or environment setting names one",
    )
    validate.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format (default: text)"
    )
    validate.add_argument(
        "--output",
        metavar="FILE",
        help="write the report (files with findings only) to FILE in the chosen format "
        "and print one summary line",
    )
    validate.set_defaults(handler=_run_validate)

    manifest = commands.add_parser("manifest", help="check or sync *.manifest files")
    manifest_commands = manifest.add_subparsers(
        dest="manifest_command", metavar="<subcommand>", required=True
    )
    check = manifest_commands.add_parser(
        "check", help="report manifest problems; exit 1 when there are errors"
    )
    check.add_argument("--path", default=".", help="project file or directory (default: current)")
    check.set_defaults(handler=_run_manifest_check)
    sync = manifest_commands.add_parser(
        "sync", help="add missing names to Project manifests (dry run by default)"
    )
    sync.add_argument("--path", default=".", help="project file or directory (default: current)")
    sync.add_argument(
        "--write", action="store_true", help="write the changes, saving <name>.old backups"
    )
    sync.add_argument(
        "--remove-stale", action="store_true", help="also remove entries that match no file"
    )
    sync.set_defaults(handler=_run_manifest_sync)

    versions = commands.add_parser(
        "versions", help="list Game Versions with audit status and unverified gate tokens"
    )
    versions.set_defaults(handler=_run_versions)
    return parser


def main(argv: Sequence[str] | None = None, engine: Engine | None = None) -> int:
    """Run the soase-validator command-line interface.

    Args:
        argv: Command-line arguments excluding the program name. Defaults to
            ``sys.argv[1:]``.
        engine: The Engine to use; a new one is created when omitted.

    Returns:
        The process exit code.

    Raises:
        SystemExit: When argparse handles ``--help``, ``--version`` or a usage
            error.
    """
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace, Engine], int] = args.handler
    return handler(args, Engine() if engine is None else engine)


if __name__ == "__main__":
    sys.exit(main())
