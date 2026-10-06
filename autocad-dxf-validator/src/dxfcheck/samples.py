"""데모·테스트용 DXF 생성기.

    python -m dxfcheck.samples <출력폴더>
      → samples.zip (분전반 정상/불량), pv_good.zip / pv_bad.zip (태양광 E-01~E-21 세트)
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
        zf.write(good, "도면/P-101_분전반.dxf")
        zf.write(bad, "도면/P-102_불량.dxf")
        zf.writestr("도면/readme.txt", "sample")
    for name, bad_set in (("pv_good", False), ("pv_bad", True)):
        d = build_pv_set(out / name, bad_set)
        with zipfile.ZipFile(out / (name + ".zip"), "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(d.glob("*.dxf")):
                zf.write(f, "%s/%s" % (name, f.name))
    print("\n".join(str(out / n) for n in ("samples.zip", "pv_good.zip", "pv_bad.zip")))
    return 0



# ── 태양광 도면 세트 (E-01~E-21) ─────────────────────────────────────────
GOOD_META = {
    "design": {"as_designed_kw": 99.0, "p_pv_kw": 100, "module_count": 180, "inverter_count": 2,
               "n_series": 15, "n_parallel": 6, "fuse_pick_a": 15, "dc_sq": 6, "ac_sq": 35, "mppt_count": 3,
               "receiving": "저압", "install_type": "지상형", "tray_type": "래더",
               "skip_inverter_outline": False},
    "equipment": {"module_model": "HE-550M", "inverter_model": "HI-50K", "module_width_mm": 1134,
                  "module_height_mm": 2279, "module_depth_mm": 35, "module_weight_kg": 28.6},
}


def _pv_sheet_texts(no: str, bad: bool, page: int = 0):
    cap = "설비용량 100kW" if (bad and no == "E-04") else "설비용량 99kW"
    rcv = "고압 수전 22.9kV" if bad else "저압 수전"
    t = {
        "E-01": [cap],
        "E-02": [cap, "모듈 HE-550M 550Wp × 180장", "인버터 HI-50K 50kW × 2대", "설치 형태: 지상형", rcv],
        "E-03": ["총 발전량 99kW", rcv + " 인입", "WHM 한전 거래용 계량기"],
        "E-04": [cap, "모듈 HE-550M 550Wp × 180장", "15직렬 X 6병렬 (인버터당)", "인버터 HI-50K 50kW × 2대",
                 "380/220V 3Φ4W TN-C-S 계통", "최대 스트링 전압 %s" % ("1050V" if bad else "742V"),
                 "인버터 최대 입력전압 1000V"] + ([] if bad else ["저압 수전"]),
        "E-05": ["전력간선도", "H1Z2Z2-K 1C %s (DC)" % ("6mm²" if bad else "6㎟"), "접지선 TFR-GV 16㎟",
                 "케이블트레이 래더형"],
        "E-06": ["접지설비평면도", "주접지선 PEN", "외함 보호접지 PE F-GV 16㎟", "접지도체 F-GV 16㎟ 피뢰 접속"]
                + ([] if bad else ["보호등전위본딩 F-GV 6㎟"]),
        "E-07": ["ARRAY 구조물 접지 상세도", "접지 클램프 SUS304", "접지선 F-GV 16㎟"],
        "E-08": ["모듈결선도", "15직렬 X 6병렬", "(+)", "(-)"],
        "E-09": ["태양광발전설비 계통도", "모듈 180장 → 접속반 → 인버터 2대 → AC반", "스트링 6회로", "DC FUSE 15A"],
        "E-10": ["ARRAY 계통도", "MPPT 수: 3", "DC FUSE %s" % ("20A" if bad else "15A"), "15직렬 X 6병렬"],
        "E-11": ["DC 전력 간선도 INV-%d" % page, "H1Z2Z2-K 1C 6㎟ (DC)"],
        "E-12": ["모듈 상세도 HE-550M", "2279 X 1134 X 35", "중량 28.6kg"],
        "E-13": ["인버터 회로도 HI-50K", "MPPT 수: 3"],
        "E-14": ["인버터 외형도 HI-50K"],
        "E-15": ["LV-M 계량기형 외형도", "WHM 장착"],
        "E-16": ["울타리/대문 상세도", "기초 콘크리트 300X300", "지상형"],
        "E-17": ["케이블트레이 상세도(1)", "래더형 트레이"],
        "E-18": ["케이블트레이 상세도(2)", "지지대 간격 1500"],
        "E-19": ["구조물 상세도(1)", "지상형 구조물"],
        "E-20": ["구조물 상세도(2)", "포스맥 T=2.3", "M12 볼트"],
        "E-21": ["MPPT 구성도"] + ["MPPT%d: 2스트링" % i for i in range(1, 3 if bad else 4)],
    }
    return t[no]


def _pv_rows(no: str, bad: bool):
    """같은 행 (차단기, 전선) 쌍."""
    if no == "E-04":
        return [("DC FUSE 15A", "H1Z2Z2-K 1C 6㎟ (DC)"),
                ("MCCB 3P 100AF 100AT 25kA", "F-CV 4C 35㎟ + E 16㎟"),
                ("MAIN MCCB 4P 225AF 200AT 35kA", "F-CV 4C 95㎟ + E 50㎟")]
    if no == "E-05":
        return [("MCCB 3P 100AF 100AT 25kA", "F-CV 4C %s㎟ + E 16㎟" % ("70" if bad else "35")),
                ("MAIN MCCB 4P 225AF 200AT 35kA", "F-CV 4C 95㎟ + E 50㎟")]
    return []


def _embed_meta(doc, meta: dict) -> None:
    import json
    import zlib
    from ezdxf.lldxf.types import DXFBinaryTag

    data = zlib.compress(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    d = doc.rootdict.add_new_dict("SOLAR_AUTODESIGN")
    xr = doc.objects.add_xrecord(owner=d.dxf.handle)
    xr.extend([DXFBinaryTag(310, data[i:i + 127]) for i in range(0, len(data), 127)])
    d["DESIGN"] = xr


def build_pv_sheet(path: Path, no: str, bad: bool = False, page: int = 0, meta: dict = None) -> Path:
    from .drawingset import CATALOG

    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.styles.new("KOR", dxfattribs={"font": "romans.shx", "bigfont": "whgtxt.shx"})
    for name in ("E-TEXT", "E-POWER", "TITLE", "E-SYMBOL"):
        doc.layers.add(name)
    msp = doc.modelspace()
    t = dict(height=H, style="KOR", layer="E-TEXT")
    y = 9000
    for s in _pv_sheet_texts(no, bad, page):
        msp.add_text(s, dxfattribs=t).set_placement((0, y))
        y -= 600
    for brk, cable in _pv_rows(no, bad):
        msp.add_text(brk, dxfattribs=t).set_placement((0, y))
        msp.add_text(cable, dxfattribs=t).set_placement((7000, y))
        y -= 600
    if no == "E-01":
        nos = [n for n in CATALOG]
        for i, n in enumerate(nos):
            yy = -12000 - i * 400
            msp.add_text(n, dxfattribs=t).set_placement((0, yy))
            msp.add_text(CATALOG[n][0], dxfattribs=t).set_placement((2500, yy))
    if no == "E-03":
        blk = doc.blocks.new("SITE")
        blk.add_lwpolyline([(0, 0), (1000, 0), (1000, 1000), (0, 1000)], close=True)
        msp.add_blockref("SITE", (12000, 6000), dxfattribs={"layer": "E-SYMBOL", "xscale": 2.0 if bad else 1.0,
                                                           "yscale": 1.0})
    title = CATALOG[no][0]
    blk = doc.blocks.new("TITLE_BLOCK")
    blk.add_lwpolyline([(0, 0), (18000, 0), (18000, 4000), (0, 4000)], close=True)
    tags = ["회사명", "공사명", "도면명", "도면번호", "축척", "일자", "설계", "검토", "REV"]
    for i, tag in enumerate(tags):
        blk.add_attdef(tag, (200, 3700 - i * 400), dxfattribs={"height": H, "style": "KOR"})
    ref = msp.add_blockref("TITLE_BLOCK", (0, -6000), dxfattribs={"layer": "TITLE"})
    ref.add_auto_attribs({"회사명": "" if (bad and no == "E-12") else "에이치에너지", "공사명": "OO 태양광 발전소",
                          "도면명": title, "도면번호": no + ("-%d" % page if page else ""), "축척": "1/100",
                          "일자": "2026-10-06", "설계": "홍길동", "검토": "김검토", "REV": "0"})
    if meta:
        _embed_meta(doc, meta)
    doc.saveas(path)
    return path


def build_pv_set(out: Path, bad: bool = False) -> Path:
    """E-01~E-21 세트 폴더를 만든다. bad=True 면 정합성 오류를 심는다."""
    from .drawingset import CATALOG

    out.mkdir(parents=True, exist_ok=True)
    for no in CATALOG:
        if bad and no == "E-07":
            continue   # 목록표에는 있지만 파일 누락
        meta = None if bad else GOOD_META
        if no == "E-11":
            for p in ((1,) if bad else (1, 2)):
                build_pv_sheet(out / ("%s-%d_DC간선도.dxf" % (no, p)), no, bad, p, meta)
            continue
        build_pv_sheet(out / ("%s_%s.dxf" % (no, CATALOG[no][0].replace("/", "_"))), no, bad, 0, meta)
    return out


if __name__ == "__main__":
    sys.exit(main())
