"""AutoCAD DXF 도면 검증기 (KEC 한국전기설비규정 기준)."""
from __future__ import annotations

__version__ = "0.1.0"

from .analyzer import analyze_paths  # noqa: E402,F401
from .config import Settings  # noqa: E402,F401
