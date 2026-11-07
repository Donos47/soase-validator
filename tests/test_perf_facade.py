"""Opt-in performance check of the Engine facade.

Run with ``uv run pytest -m perf``. The test needs a Rebellion 1.98 Reference
Root and is skipped when none is configured.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from tests.conftest import DEFAULT_REFERENCE_VERSION, reference_root_env_var

from soase_validator.engine.facade import Engine
from soase_validator.engine.layercache import LayerCache

BUDGET_SECONDS = 0.5
REPEATS = 5
LINES = 300


def _synthetic_entity() -> str:
    """Build an entity-shaped file of a typical size from simple fields."""
    lines = ["TXT2", "SinsArchiveVersion 194", 'entityType "Frigate"']
    for i in range(LINES):
        lines.append(f"someField{i} {i}.000000")
    return "\n".join(lines) + "\n"


@pytest.mark.perf
def test_typical_entity_validates_within_budget_on_a_warm_index(
    reference_root: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    (project / "GameInfo").mkdir(parents=True)
    (project / "soase.json").write_text("{}", encoding="utf-8")
    file = project / "GameInfo" / "Synthetic.entity"
    file.write_text(_synthetic_entity(), encoding="utf-8")
    engine = Engine(
        user_config_path=tmp_path / "no-user-file.json",
        env={reference_root_env_var(DEFAULT_REFERENCE_VERSION): str(reference_root)},
        layer_cache=LayerCache(tmp_path / "cache"),
    )
    engine.validate_file(file)

    elapsed = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        engine.validate_file(file)
        elapsed.append(time.perf_counter() - started)

    assert min(elapsed) < BUDGET_SECONDS
