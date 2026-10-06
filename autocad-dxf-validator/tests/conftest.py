from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from dxfcheck.analyzer import analyze_dxf
from dxfcheck.config import Settings
from dxfcheck.samples import build_bad, build_good


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("samples")
    build_good(d / "good.dxf")
    build_bad(d / "bad.dxf")
    return d


@pytest.fixture(scope="session")
def good_report(sample_dir):
    return analyze_dxf(sample_dir / "good.dxf", "good.dxf", Settings())


@pytest.fixture(scope="session")
def bad_report(sample_dir):
    return analyze_dxf(sample_dir / "bad.dxf", "bad.dxf", Settings())


@pytest.fixture
def make_dxf(tmp_path):
    """문자 목록으로 DXF를 만든다: [(text, x, y), ...]."""

    def _make(texts, name="t.dxf", units=4, height=2.5, settings=None):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = units
        msp = doc.modelspace()
        for text, x, y in texts:
            msp.add_text(text, dxfattribs={"height": height}).set_placement((x, y))
        p = tmp_path / name
        doc.saveas(p)
        return analyze_dxf(p, name, settings or Settings())

    return _make


def ids(report, severity=None):
    return [f.rule_id for f in report.findings if severity is None or f.severity.value == severity]
