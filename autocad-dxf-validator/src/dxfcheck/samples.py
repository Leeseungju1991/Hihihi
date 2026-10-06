"""데모·테스트용 DXF 생성기.

    python -m dxfcheck.samples <출력폴더>   →  good_panel.dxf, bad_panel.dxf, samples.zip
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import ezdxf

H = 250.0  # 1/100 축척에서 출력 2.5mm


def _title_block(doc, msp, values: dict) -> None:
    blk = doc.blocks.new("TITLE_BLOCK")
    blk.add_lwpolyline([(0, 0), (18000, 0), (18000, 4000), (0, 4000)], close=True)
    tags = ["공사명", "도면명", "도면번호", "축척", "일자", "설계", "검토", "REV"]
    for i, tag in enumerate(tags):
        blk.add_attdef(tag, (200, 3500 - i * 450), dxfattribs={"height": H, "style": "KOR"})
    ref = msp.add_blockref("TITLE_BLOCK", (0, -6000), dxfattribs={"layer": "TITLE"})
    ref.add_auto_attribs(values)


def build_good(path: Path) -> Path:
    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.styles.new("KOR", dxfattribs={"font": "romans.shx", "bigfont": "whgtxt.shx"})
    for name, color in (("E-POWER", 1), ("E-TEXT", 7), ("E-GROUND", 3), ("TITLE", 7)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    t = dict(height=H, style="KOR", layer="E-TEXT")

    msp.add_text("분전반 LP-1 결선도  380/220V 3Φ4W  TN-C-S 계통", dxfattribs=t).set_placement((0, 9000))
    rows = [
        ("MAIN MCCB 4P 100AF 75AT 25kA", "0.6/1kV F-CV 4C 25㎟ + E 16㎟", "동력 주간선"),
        ("ELB 2P 30AF 20AT 30mA", "HFIX 2.5㎟ X 2, E 2.5㎟ (E22)", "전열 콘센트"),
        ("MCCB 2P 30AF 15AT 2.5kA", "HFIX 2.5㎟ X 2, E 2.5㎟ (E16)", "조명 L=40m IB=8A"),
    ]
    for i, (brk, cable, use) in enumerate(rows):
        y = 7000 - i * 800
        msp.add_text(brk, dxfattribs=t).set_placement((0, y))
        msp.add_text(cable, dxfattribs=t).set_placement((8000, y))
        msp.add_text(use, dxfattribs=t).set_placement((16000, y))
        msp.add_line((7500, y + 100), (7900, y + 100), dxfattribs={"layer": "E-POWER"})
    msp.add_text("접지도체 F-GV 16㎟ (주접지단자)", dxfattribs={**t, "layer": "E-GROUND"}).set_placement((0, 4000))
    msp.add_text("범례: L1 갈색, L2 흑색, L3 회색, N 청색, PE 녹색-노란색", dxfattribs=t).set_placement((0, 3200))
    msp.add_text("설계: 전기기술사 홍길동", dxfattribs=t).set_placement((0, 2400))
    _title_block(doc, msp, {"공사명": "OO빌딩 전기공사", "도면명": "분전반 결선도", "도면번호": "E-101",
                            "축척": "1/100", "일자": "2026-10-06", "설계": "홍길동", "검토": "김검토", "REV": "0"})
    doc.saveas(path)
    return path


def build_bad(path: Path) -> Path:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 0
    msp = doc.modelspace()
    t = dict(height=2.5)  # Standard(txt.shx) — 한글 빅폰트 없음
    lines = [
        ("MCCB 3P 100AF 75AT", "F-CV 4C 6SQ", "동력"),           # In 75 > Iz 52
        ("MCCB 3P 50AF 60AT", "F-CV 4C 16SQ", "동력"),           # AT > AF
        ("MCCB 2P 30AF 20AT", "HFIX 1.5SQ X 2", "전등"),         # 1.5㎟ 미달
        ("ELB 2P 30AF 20AT 30mA", "HFIX 2.5SQ X 3", "욕실 콘센트"),  # 15mA 초과
        ("MCCB 3P 100AF 60AT", "F-CV 4C 16SQ L=300m 30kW", "급수펌프"),  # 전압강하
        ("MCCB 2P 30AF 20AT", "HFIX 4SQ X 2", "옥외 콘센트"),       # 누전차단기 없음
    ]
    for i, (brk, cable, use) in enumerate(lines):
        y = 100 - i * 6
        msp.add_text(brk, dxfattribs=t).set_placement((0, y))
        msp.add_text(cable, dxfattribs=t).set_placement((40, y))
        msp.add_text(use, dxfattribs=t).set_placement((90, y))
    msp.add_text("외함 제3종 접지 시행", dxfattribs=t).set_placement((0, 40))
    msp.add_text("접지선 GV 4SQ", dxfattribs=t).set_placement((0, 34))
    msp.add_text("L1(적색) L2(흑색) L3(청색)", dxfattribs=t).set_placement((0, 28))
    msp.add_line((0, 0), (0, 0))
    msp.add_line((0, 0), (50, 0))
    msp.add_line((50, 0), (0, 0))
    dim = msp.add_linear_dim(base=(0, -10), p1=(0, 0), p2=(50, 0), text="60")
    dim.render()
    doc.saveas(path)
    return path


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    out = Path(argv[0] if argv else "samples")
    out.mkdir(parents=True, exist_ok=True)
    good = build_good(out / "good_panel.dxf")
    bad = build_bad(out / "bad_panel.dxf")
    with zipfile.ZipFile(out / "samples.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(good, "도면/E-101_분전반.dxf")
        zf.write(bad, "도면/E-102_불량.dxf")
        zf.writestr("도면/readme.txt", "sample")
    print(out / "samples.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
