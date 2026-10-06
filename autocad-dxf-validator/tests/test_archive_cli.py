from __future__ import annotations

import json
import zipfile

from dxfcheck.analyzer import analyze_paths
from dxfcheck.cli import main
from dxfcheck.report import to_markdown


def _zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


def test_zip_slip_blocked(tmp_path, sample_dir):
    z = _zip(tmp_path / "evil.zip", [("../../evil.dxf", "x"), ("ok/a.dxf", (sample_dir / "good.dxf").read_bytes())])
    r = analyze_paths([z])
    assert any(f.rule_id == "ZIP-003" for f in r.archive_findings)
    assert [f.path for f in r.files] == ["evil.zip/ok/a.dxf"]
    assert not (tmp_path.parent / "evil.dxf").exists()


def test_nested_zip_and_dwg(tmp_path, sample_dir):
    inner = _zip(tmp_path / "inner.zip", [("b.dxf", (sample_dir / "bad.dxf").read_bytes())])
    z = _zip(tmp_path / "outer.zip", [("inner.zip", inner.read_bytes()), ("c.dwg", b"AC1032" + b"\0" * 100),
                                      ("note.pdf", b"%PDF")])
    r = analyze_paths([z])
    kinds = {f.path: f.kind for f in r.files}
    assert kinds["outer.zip/inner.zip/b.dxf"] == "dxf"
    assert kinds["outer.zip/c.dwg"] == "dwg"
    assert any(f.rule_id == "FILE-003" for f in r.archive_findings)


def test_cp949_filename(tmp_path, sample_dir):
    # 한글 Windows 압축: UTF-8 플래그 없이 cp949 바이트로 저장된 파일명
    z = tmp_path / "kr.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ABCD.dxf", (sample_dir / "good.dxf").read_bytes())
    z.write_bytes(z.read_bytes().replace(b"ABCD.dxf", "도면.dxf".encode("cp949")))
    r = analyze_paths([z])
    assert r.files[0].path == "kr.zip/도면.dxf"


def test_no_dxf(tmp_path):
    z = _zip(tmp_path / "x.zip", [("a.txt", "hi")])
    r = analyze_paths([z])
    assert r.verdict == "검증 불가"
    assert any(f.rule_id == "FILE-001" for f in r.archive_findings)


def test_corrupt_dxf(tmp_path):
    z = _zip(tmp_path / "x.zip", [("broken.dxf", "garbage\nnot a dxf")])
    r = analyze_paths([z])
    assert r.files[0].verdict == "검증 불가"


def test_cli_outputs(tmp_path, sample_dir):
    z = _zip(tmp_path / "s.zip", [("good.dxf", (sample_dir / "good.dxf").read_bytes()),
                                  ("bad.dxf", (sample_dir / "bad.dxf").read_bytes())])
    out = tmp_path / "rep" / "result"
    code = main([str(z), "-f", "both", "-o", str(out), "--fail-on", "error"])
    assert code == 1
    data = json.loads((tmp_path / "rep" / "result.json").read_text(encoding="utf-8"))
    assert data["verdict"] == "부적합"
    md = (tmp_path / "rep" / "result.md").read_text(encoding="utf-8")
    assert "회로 대조" in md and "KEC-212.4.1" in md


def test_markdown_renders_for_empty(tmp_path):
    r = analyze_paths([tmp_path / "missing.zip"])
    assert "검증 불가" in to_markdown(r)
