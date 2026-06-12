"""Configuration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULT_TARGETS_PATH = Path("config/targets.yaml")


def load_targets(path: Path = DEFAULT_TARGETS_PATH) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"targets config must be a mapping: {path}")
    product = data.get("product")
    if not isinstance(product, dict):
        raise ValueError("targets config missing product mapping")
    return product
