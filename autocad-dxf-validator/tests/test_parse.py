from __future__ import annotations

import pytest

from dxfcheck.drawing import normalize
from dxfcheck.electrical import parse_breakers, parse_cables


@pytest.mark.parametrize("text,type_,size,cores,parallel", [
    ("0.6/1kV F-CV 4C-25㎟", "F-CV", 25, 4, 1),
    ("F-CV 6SQ/4C", "F-CV", 6, 4, 1),
    ("CV 1C 95SQ×4", "CV", 95, 1, 1),
    ("2(CV 1C 240SQ×4)", "CV", 240, 1, 2),
    ("CV 1C 240SQ×8", "CV", 240, 1, 2),
    ("F-CV 4C 25SQ X 2", "F-CV", 25, 4, 2),
    ("HFIX 2.5mm² X 3", "HFIX", 2.5, None, 1),
    ("TFR-CV 3C 10㎟", "TFR-CV", 10, 3, 1),
])
def test_cable(text, type_, size, cores, parallel):
    cables, _ = parse_cables(normalize(text))
    assert len(cables) == 1
    c = cables[0]
    assert (c.type, c.size, c.cores, c.parallel) == (type_, size, cores, parallel)


def test_pe_and_grounding():
    cables, pes = parse_cables(normalize("F-CV 4C 25㎟ + E 16㎟"))
    assert cables[0].size == 25 and pes[0].size == 16 and not pes[0].grounding
    _, pes = parse_cables(normalize("접지선 GV 16SQ"))
    assert pes[0].grounding and pes[0].size == 16


def test_xlpe_not_pe():
    # XLPE 의 'PE' 를 보호도체로 읽지 않는다
    _, pes = parse_cables(normalize("XLPE 절연 6SQ"))
    assert pes == []


@pytest.mark.parametrize("text,kind,poles,af,at,ma", [
    ("MCCB 3P 100AF 75AT 25kA", "MCCB", 3, 100, 75, None),
    ("ELB 2P 30AF 20AT 30mA", "ELB", 2, 30, 20, 30),
    ("MCB 1P 20A", "MCB", 1, None, 20, None),
    ("누전차단기 2P 30AT 15mA", "ELB", 2, None, 30, 15),
    ("50AF/40AT", None, None, 50, 40, None),
])
def test_breaker(text, kind, poles, af, at, ma):
    b = parse_breakers(normalize(text))
    assert len(b) == 1
    assert (b[0].kind, b[0].poles, b[0].af, b[0].at, b[0].ma) == (kind, poles, af, at, ma)


def test_breaker_word_only_ignored():
    assert parse_breakers(normalize("차단기 설치 위치 확인")) == []


def test_two_breakers_in_one_text():
    b = parse_breakers(normalize("MCCB 3P 100AF 75AT / ELB 2P 30AF 20AT 30mA"))
    assert [x.kind for x in b] == ["MCCB", "ELB"]
