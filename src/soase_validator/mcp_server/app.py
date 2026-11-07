"""MCP server for soase-validator.

The server translates between MCP tool arguments and results and the Engine
model types, and calls the Engine facade; it holds no validation logic. All
code that touches the MCP SDK lives in this module. stdout carries the stdio
transport, so logging goes to stderr only.

Diagnostics are returned as mappings with one-based ``line`` and ``column``
(and ``end_line`` and ``end_column``), because the Engine's zero-based
positions are an internal detail. Input positions are one-based as well.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from soase_validator.engine.chain import ChainProblem, Layer
from soase_validator.engine.config import EffectiveConfig
from soase_validator.engine.facade import Engine
from soase_validator.engine.manifests import SyncPlan, format_plan
from soase_validator.engine.model import (
    CompletionItem,
    Diagnostic,
    FieldHelp,
    Position,
)
from soase_validator.engine.parser import read_text_file
from soase_validator.engine.versions import GameVersion, VersionListing, parse_game_version
from soase_validator.reports import (
    build_report,
    diagnostic_to_dict,
    format_json,
    summary_to_dict,
    write_report,
)

SERVER_NAME = "soase-validator"
SERVER_VERSION = "0.1.0"

_LOG = logging.getLogger(__name__)


def _diagnostics_to_dicts(diagnostics: Iterable[Diagnostic]) -> list[dict[str, Any]]:
    """Convert Diagnostics, keeping their order.

    Args:
        diagnostics: The Engine Diagnostics.

    Returns:
        One mapping per Diagnostic.
    """
    return [diagnostic_to_dict(item) for item in diagnostics]


def completion_to_dict(item: CompletionItem) -> dict[str, Any]:
    """Convert a completion candidate to its MCP form.

    Args:
        item: The Engine candidate.

    Returns:
        A mapping with ``label``, ``kind``, ``detail`` and
        ``documentation``.
    """
    return {
        "label": item.label,
        "kind": item.kind,
        "detail": item.detail,
        "documentation": item.documentation,
    }


def field_help_to_dict(value: FieldHelp) -> dict[str, Any]:
    """Convert field help to its MCP form.

    Args:
        value: The Engine help.

    Returns:
        A mapping holding every attribute of the help.
    """
    return {
        "structure": value.structure,
        "field": value.field,
        "validation_type": value.validation_type,
        "required": value.required,
        "help": value.help,
        "version_gate": value.version_gate,
    }


def plan_to_dict(plan: SyncPlan) -> dict[str, Any]:
    """Convert a manifest sync plan to its MCP form.

    Args:
        plan: The plan.

    Returns:
        A mapping with the unified ``diff`` text, the per-manifest
        ``edits`` and the ``advisories`` for manifests of lower Layers.
    """
    return {
        "diff": format_plan(plan),
        "edits": [
            {
                "manifest": str(edit.manifest_path),
                "added": list(edit.added),
                "removed": list(edit.removed),
            }
            for edit in plan.edits
        ],
        "advisories": [
            {
                "manifest": str(advisory.manifest_path),
                "layer": advisory.layer_name,
                "names": list(advisory.names),
            }
            for advisory in plan.advisories
        ],
    }


def layer_to_dict(layer: Layer) -> dict[str, Any]:
    """Convert a Chain Layer to its MCP form.

    Args:
        layer: The Layer.

    Returns:
        A mapping with ``name``, ``path``, ``kind``, ``status`` and ``found``,
        which is false only for a missing directory.
    """
    return {
        "name": layer.name,
        "path": str(layer.path),
        "kind": layer.kind,
        "status": layer.status,
        "found": layer.status != "missing",
    }


def problem_to_dict(problem: ChainProblem) -> dict[str, Any]:
    """Convert a Chain problem to its MCP form.

    Args:
        problem: The problem.

    Returns:
        A mapping with ``code``, ``message`` and ``path``.
    """
    return {
        "code": problem.code,
        "message": problem.message,
        "path": None if problem.path is None else str(problem.path),
    }


def version_listing_to_dict(listing: VersionListing) -> dict[str, Any]:
    """Convert the Game Version listing to its MCP form.

    Args:
        listing: The Engine listing.

    Returns:
        A mapping with ``versions`` (``id``, ``name``, ``audit_status`` and
        ``label``) and ``unverified_tokens``.
    """
    return {
        "versions": [
            {
                "id": item.version.value,
                "name": item.name,
                "audit_status": item.audit_status,
                "label": item.label,
            }
            for item in listing.versions
        ],
        "unverified_tokens": list(listing.unverified_tokens),
    }


def effective_config_to_dict(report: EffectiveConfig, chain: Iterable[Layer]) -> dict[str, Any]:
    """Convert the effective configuration to its MCP form.

    Args:
        report: The Engine report.
        chain: The resolved Chain, lowest Layer first.

    Returns:
        A mapping with ``settings`` (name, value and source), the found
        status of each Reference Root, the configuration files involved,
        configuration ``problems`` and the ``chain``.
    """
    return {
        "settings": [
            {
                "name": entry.name,
                "value": entry.value,
                "source": entry.source.kind.value,
                "source_file": None if entry.source.path is None else str(entry.source.path),
            }
            for entry in report.entries
        ],
        "reference_roots_found": dict(report.reference_roots_found),
        "project_files": [str(file) for file in report.project_files],
        "user_file": None if report.user_file is None else str(report.user_file),
        "problems": [
            {
                "setting": problem.setting,
                "message": problem.message,
                "file": None if problem.file is None else str(problem.file),
            }
            for problem in report.settings.problems
        ],
        "chain": [layer_to_dict(layer) for layer in chain],
    }


def _version_for(engine: Engine, game_version: str | None, path: str | None) -> GameVersion:
    """Choose the Game Version for a request.

    Args:
        engine: The Engine.
        game_version: An explicit version name, or None.
        path: A file or directory whose Project decides the version when no
            explicit version is given; the working directory when None.

    Returns:
        The Game Version.

    Raises:
        ValueError: If ``game_version`` is not a known version name.
    """
    if game_version is not None:
        parsed = parse_game_version(game_version)
        if parsed is None:
            raise ValueError(f"unknown game version '{game_version}'")
        return parsed
    return engine.resolve_settings(Path.cwd() if path is None else Path(path)).game_version


def create_server(engine: Engine | None = None) -> MCPServer:
    """Build the MCP server.

    Args:
        engine: The Engine to call; a new one is created when omitted.

    Returns:
        The server with its tools and resources registered.
    """
    backend = Engine() if engine is None else engine
    server = MCPServer(SERVER_NAME, version=SERVER_VERSION)

    @server.tool()
    def validate_file(path: str, text: str | None = None) -> dict[str, Any]:
        """Validate one mod file and return its Diagnostics.

        Args:
            path: Path of the file.
            text: Current text, for example an unsaved buffer; the file is
                read from disk when omitted.
        """
        return {"diagnostics": _diagnostics_to_dicts(backend.validate_file(Path(path), text))}

    @server.tool()
    def validate_directory(path: str, output_path: str | None = None) -> dict[str, Any]:
        """Validate every supported file below a directory.

        With ``output_path`` the full JSON report is written to that file,
        replacing any existing file, and the result is a summary instead of
        the per-file Diagnostics.

        Args:
            path: Path of the directory.
            output_path: Report file; its directory must exist.
        """
        results = backend.validate_directory(Path(path))
        if output_path is not None:
            report = build_report(results)
            target = Path(output_path)
            write_report(target, format_json(report))
            return summary_to_dict(report, target)
        return {
            "files": {str(file): _diagnostics_to_dicts(found) for file, found in results.items()}
        }

    @server.tool()
    def complete(path: str, line: int, column: int, text: str | None = None) -> dict[str, Any]:
        """Return completions at a position of a file.

        Args:
            path: Path of the file.
            line: One-based line of the cursor.
            column: One-based column of the cursor.
            text: Current text; the file is read from disk when omitted.
        """
        if line < 1 or column < 1:
            raise ValueError("line and column are one-based and must be at least 1")
        file = Path(path)
        source = read_text_file(file) if text is None else text
        items = backend.complete(file, source, Position(line - 1, column - 1))
        return {"items": [completion_to_dict(item) for item in items]}

    @server.tool()
    def field_help(
        structure: str,
        field: str,
        game_version: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Return the help of a field of a structure Definition.

        Args:
            structure: Structure name, for example ``Ability``.
            field: Field key.
            game_version: Game Version name; the version of the Project that
                contains ``path`` when omitted.
            path: File or directory that selects the Project.
        """
        version = _version_for(backend, game_version, path)
        found = backend.field_help(structure, field, version)
        return {
            "found": found is not None,
            "help": None if found is None else field_help_to_dict(found),
        }

    @server.tool()
    def list_entity_types(
        game_version: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        """List the ``entityType`` values valid for a Game Version.

        Args:
            game_version: Game Version name; the version of the Project that
                contains ``path`` when omitted.
            path: File or directory that selects the Project.
        """
        version = _version_for(backend, game_version, path)
        return {"entity_types": backend.entity_types(version)}

    @server.tool()
    def manifest_check(path: str) -> dict[str, Any]:
        """Check the manifests of a Project against its files.

        Args:
            path: A file or directory of the Project.
        """
        return {"diagnostics": _diagnostics_to_dicts(backend.manifest_check(Path(path)))}

    @server.tool()
    def manifest_sync(path: str, write: bool = False, remove_stale: bool = False) -> dict[str, Any]:
        """Plan, and optionally write, the sync of a Project's manifests.

        The default is a dry run that returns a unified diff and changes
        nothing. With ``write`` set, each changed manifest is backed up to
        ``<name>.old`` and then replaced.

        Args:
            path: A file or directory of the Project.
            write: Write the changes instead of only reporting them.
            remove_stale: Also remove entries that match no file.
        """
        plan = backend.manifest_plan(Path(path), remove_stale=remove_stale)
        result = plan_to_dict(plan)
        result["dry_run"] = not write
        result["backups"] = []
        if write:
            records = backend.manifest_apply(plan)
            result["backups"] = [
                {"manifest": str(item.manifest_path), "backup": str(item.backup_path)}
                for item in records
            ]
        return result

    @server.tool()
    def get_config(path: str | None = None) -> dict[str, Any]:
        """Report the effective configuration of a Project.

        Each setting carries the source it came from. The Chain lists the
        Layers from lowest to highest with path, kind and whether the
        directory was found.

        Args:
            path: File or directory that selects the Project; the working
                directory when omitted.
        """
        location = Path.cwd() if path is None else Path(path)
        return effective_config_to_dict(
            backend.effective_config(location), backend.chain_layers(location)
        )

    @server.tool()
    def set_reference_root(
        game_version: str, root: str, path: str | None = None, user: bool = False
    ) -> dict[str, Any]:
        """Set the Reference Root of a Game Version.

        The root is stored in the Project's ``soase.json`` (created in the
        directory of ``path`` when none exists), or in the user-level file
        as a default when ``user`` is set. A root that does not exist is
        still saved and reported through ``found``. A root that is missing or
        holds no game data directory also yields an entry in ``warnings``.

        Args:
            game_version: Game Version name.
            root: Directory of the base game data.
            path: File or directory that selects the Project; the working
                directory when omitted.
            user: Write the user-level default instead of the Project file.
        """
        version = parse_game_version(game_version)
        if version is None:
            raise ValueError(f"unknown game version '{game_version}'")
        location = Path.cwd() if path is None else Path(path)
        file = backend.set_reference_root(location, version, root, user=user)
        problem = backend.reference_root_problem(file, root)
        return {
            "file": str(file),
            "game_version": version.value,
            "root": root,
            "found": backend.effective_config(location).reference_roots_found.get(version.value),
            "warnings": [] if problem is None else [problem_to_dict(problem)],
        }

    @server.tool()
    def edit_layers(
        action: str,
        layers: list[str],
        index: int | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Add, remove, move or reorder the parent Layers of a Project.

        Args:
            action: ``add`` inserts each entry at ``index`` or appends it,
                ``remove`` deletes entries, ``move`` places one configured
                entry at ``index``, ``reorder`` takes the complete new order.
            layers: Layer paths or ``@alias`` entries, lowest Layer first.
            index: Zero-based position, lowest Layer first.
            path: File or directory that selects the Project; the working
                directory when omitted.
        """
        location = Path.cwd() if path is None else Path(path)
        file, current = backend.edit_layers(location, action, layers, index)
        return {
            "file": str(file),
            "layers": current,
            "chain": [layer_to_dict(layer) for layer in backend.chain_layers(location)],
        }

    @server.tool()
    def configure(
        path: str | None = None,
        game_version: str | None = None,
        reference_root: str | None = None,
        layers: list[str] | None = None,
        mod_roots: list[str] | None = None,
        language: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Initialize the settings of a project (first-time setup).

        Creates ``soase.json`` in the project directory when none exists
        there. An existing file keeps its other keys; a key that already
        holds a different value is skipped unless ``overwrite`` is set.
        Invalid input is rejected and nothing is written. The user-level
        file is never changed. When no Reference Root is supplied, nothing is
        written for it; the result names the user-level default Reference
        Root in effect, if any. The result also carries the effective
        configuration and Chain, so missing Reference Roots and Layers show.
        A supplied Reference Root that is missing or holds no game data
        directory is still saved and yields an entry in ``warnings``.

        Args:
            path: Project directory; the working directory when omitted.
            game_version: Game Version name to store.
            reference_root: Directory of the base game data for
                ``game_version``, or for Rebellion 1.98 when that is omitted.
            layers: Parent Layer paths or ``@alias`` entries, lowest first.
            mod_roots: Mod Root directories, stored as ``modRoots``.
            language: Localization folder name, for example ``en``.
            overwrite: Replace values that differ from the supplied ones.
        """
        version = None
        if game_version is not None:
            version = parse_game_version(game_version)
            if version is None:
                raise ValueError(f"unknown game version '{game_version}'")
        location = Path.cwd() if path is None else Path(path)
        result = backend.configure_project(
            location,
            game_version=version,
            reference_root=reference_root,
            layers=layers,
            mod_roots=mod_roots,
            language=language,
            overwrite=overwrite,
        )
        default_root = result.default_reference_root
        report = effective_config_to_dict(
            backend.effective_config(location), backend.chain_layers(location)
        )
        problem = (
            None
            if reference_root is None
            else backend.reference_root_problem(result.file, reference_root)
        )
        return {
            "file": str(result.file),
            "created": result.created,
            "warnings": [] if problem is None else [problem_to_dict(problem)],
            "set": list(result.set_keys),
            "skipped": list(result.skipped_keys),
            "unchanged": list(result.unchanged_keys),
            "default_reference_root": None if default_root is None else str(default_root),
            "config": report,
        }

    @server.tool()
    def versions() -> dict[str, Any]:
        """List the Game Versions with their audit status.

        Rebellion 1.98 is audited; every other version is unaudited and
        best-effort. The result also names the gate tokens whose
        interpretation is unverified.
        """
        return version_listing_to_dict(backend.version_listing())

    @server.resource(
        "soase://definitions/{structure}",
        name="definition",
        description="A structure Definition as JSON.",
        mime_type="application/json",
    )
    def definition(structure: str) -> str:
        """Return a structure Definition as JSON text.

        Args:
            structure: Structure name.
        """
        found = backend.structure_definition(structure)
        if found is None:
            raise ValueError(f"unknown structure '{structure}'")
        return json.dumps(found, indent=2)

    return server


def main() -> None:
    """Run the MCP server over stdio.

    Logging goes to stderr because stdout carries the protocol.
    """
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    create_server().run("stdio")


if __name__ == "__main__":
    main()
