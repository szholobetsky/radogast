"""Configuration: defaults + optional .radogast/ override."""
from pathlib import Path
import yaml

WINDOWS: list[int] = [1, 3, 5]
DRIFT_THRESHOLD_DEG: float = 40.0
BIAS_THRESHOLD: float = 3.0
EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
HYBRID: bool = True

# Project-local radogast directory (created by `radogast init`)
LOCAL_DIR = Path(".radogast")


def load() -> dict:
    """Load config. Search order: .radogast/config.yaml → .radogast.yaml → ~/.radogast/config.yaml."""
    cfg = {
        "windows": WINDOWS,
        "drift_threshold_deg": DRIFT_THRESHOLD_DEG,
        "bias_threshold": BIAS_THRESHOLD,
        "embedding_model": EMBEDDING_MODEL,
        "hybrid": HYBRID,
    }
    for candidate in (
        Path.cwd() / ".radogast" / "config.yaml",
        Path.cwd() / ".radogast.yaml",
        Path.home() / ".radogast" / "config.yaml",
    ):
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as f:
                overrides = yaml.safe_load(f) or {}
            cfg.update(overrides)
            break
    return cfg


def find_target() -> Path | None:
    """Find task.yaml. Search order: .radogast/task.yaml → ~/.radogast/task.yaml."""
    for candidate in (
        Path.cwd() / ".radogast" / "task.yaml",
        Path.home() / ".radogast" / "task.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None
