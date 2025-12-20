from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Type


class ChargingAppPlugin:
    """Interface for charging app OCR parsers."""

    name: str = "base"
    display_name: str = "Base Plugin"

    def detect(self, text: str) -> float:
        """Return a confidence score based on the OCR text."""
        raise NotImplementedError

    def parse(self, text: str) -> dict:
        """Extract a CSV row from OCR text."""
        raise NotImplementedError


def _import_plugin_modules() -> None:
    """Import all plugin modules in this package to register subclasses."""
    package_dir = Path(__file__).parent
    for path in package_dir.glob("*.py"):
        if path.name.startswith("_") or path.stem in {"__init__", "base"}:
            continue
        importlib.import_module(f"{__name__.rsplit('.', 1)[0]}.{path.stem}")


def _all_subclasses(cls: Type[ChargingAppPlugin]) -> List[Type[ChargingAppPlugin]]:
    subclasses = []
    for subclass in cls.__subclasses__():
        subclasses.append(subclass)
        subclasses.extend(_all_subclasses(subclass))  # type: ignore[arg-type]
    return subclasses


def discover_plugins() -> List[ChargingAppPlugin]:
    """Load and instantiate all available plugin classes."""
    _import_plugin_modules()
    plugins = []
    seen: set[str] = set()
    for cls in _all_subclasses(ChargingAppPlugin):
        if cls is ChargingAppPlugin:
            continue
        if cls.name in seen:
            continue
        seen.add(cls.name)
        plugins.append(cls())
    plugins.sort(key=lambda plugin: plugin.name)
    return plugins


def score_plugins(text: str, plugins: Sequence[ChargingAppPlugin]) -> List[Tuple[float, ChargingAppPlugin]]:
    scores: List[Tuple[float, ChargingAppPlugin]] = []
    for plugin in plugins:
        scores.append((plugin.detect(text), plugin))
    scores.sort(key=lambda pair: pair[0], reverse=True)
    return scores


def get_plugin_by_name(name: str, plugins: Sequence[ChargingAppPlugin]) -> Optional[ChargingAppPlugin]:
    lowered = name.lower()
    for plugin in plugins:
        if lowered in {plugin.name.lower(), plugin.display_name.lower()}:
            return plugin
    return None


def pick_plugin_from_scores(scores: Sequence[Tuple[float, ChargingAppPlugin]]) -> Optional[ChargingAppPlugin]:
    if not scores:
        return None
    top_score, top_plugin = scores[0]
    if top_score <= 0:
        return None
    if len(scores) == 1:
        return top_plugin
    next_score = scores[1][0]
    if top_score > next_score:
        return top_plugin
    # Ambiguous if the best score ties with another plugin.
    tied = [plugin for score, plugin in scores if score == top_score]
    return top_plugin if len(tied) == 1 else None
