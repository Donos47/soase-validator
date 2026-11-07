"""Write planned manifest edits to disk.

This is the only module that changes manifests. Each manifest is copied to
``<name>.old`` beside it, replacing any earlier backup, then replaced through
a temporary file in the same directory, so a failed write leaves the original
in place.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path

from soase_validator.engine.manifests import BackupRecord, ManifestEdit, SyncPlan

BACKUP_SUFFIX = ".old"
_BOM = b"\xef\xbb\xbf"


def manifest_apply(plan: SyncPlan) -> list[BackupRecord]:
    """Write the edits of a plan.

    Every edit is checked and encoded before any file is touched. Each file
    is then backed up and replaced in turn.

    Args:
        plan: The plan. Advisories are not applied.

    Returns:
        One record per written manifest, in plan order.

    Raises:
        ValueError: If a manifest changed on disk since it was planned.
        UnicodeEncodeError: If the new text cannot be encoded the way the
            manifest is stored.
        OSError: If a backup or write fails. The failing manifest keeps its
            original content and no temporary file remains.
    """
    prepared: list[tuple[ManifestEdit, bytes]] = []
    for edit in plan.edits:
        current = edit.manifest_path.read_bytes()
        if _decode(current) != edit.original_text:
            raise ValueError(f"{edit.manifest_path.name} changed since it was planned")
        prepared.append((edit, _encode_like(current, edit.new_text)))

    records: list[BackupRecord] = []
    for edit, data in prepared:
        backup = edit.manifest_path.with_name(edit.manifest_path.name + BACKUP_SUFFIX)
        shutil.copy2(edit.manifest_path, backup)
        _replace(edit.manifest_path, data)
        records.append(BackupRecord(edit.manifest_path, backup))
    return records


def _replace(path: Path, data: bytes) -> None:
    """Replace a file atomically.

    Args:
        path: The file to replace.
        data: The new content.

    Raises:
        OSError: If writing or replacing fails; the temporary file is removed.
    """
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def _decode(data: bytes) -> str:
    """Decode stored bytes the way the readers do.

    Args:
        data: The file content.

    Returns:
        UTF-8 text without a BOM, or Latin-1 text when not valid UTF-8.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _encode_like(original: bytes, text: str) -> bytes:
    """Encode text in the encoding of the file it replaces.

    Args:
        original: The current file content.
        text: The new text.

    Returns:
        UTF-8 (with a BOM when the original had one), or Latin-1 when the
        original was not valid UTF-8.

    Raises:
        UnicodeEncodeError: If the text does not fit that encoding.
    """
    try:
        original.decode("utf-8")
    except UnicodeDecodeError:
        return text.encode("latin-1")
    body = text.encode("utf-8")
    return _BOM + body if original.startswith(_BOM) else body


__all__ = ["BACKUP_SUFFIX", "manifest_apply"]
