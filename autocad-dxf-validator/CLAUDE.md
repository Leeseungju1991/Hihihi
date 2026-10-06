# CLAUDE.md — AutoCAD DXF 검증기 (KEC 기준)

AutoCAD 자동화 설계로 생성된 DXF 도면을 **파일·구조 / CAD 품질 / 도면 표기 / KEC 전기** 네 측면에서 검증한다.

## 사용자가 ZIP(또는 DXF)을 첨부하면
1. 첨부 파일 경로를 확인한다. 압축은 신뢰하지 않는 입력이므로 직접 풀지 말고 도구에 넘긴다(도구가 안전 해제).
2. 실행:
   ```bash
   cd autocad-dxf-validator
   [ -x .venv/bin/dxfcheck ] || (uv venv -q .venv && uv pip install -q --python .venv/bin/python -e ".[dev]")
   .venv/bin/dxfcheck <첨부.zip> -f both -o reports/<이름>
   ```
3. `reports/<이름>.md`를 읽고 사용자에게 한국어로 답한다:
   - 종합 판정(적합 / 조건부 적합 / 부적합 / 검증 불가)과 파일별 점수
   - **부적합** 항목 전부: 무엇이, 어디서(레이어·좌표·원문), 어느 KEC 조항에 어긋나는지, 어떻게 고치는지
   - 주의 항목은 묶어서 요약, 참고 항목은 개수와 핵심만
   - 회로 대조표에서 부적합·주의 회로
   - 검토 한계(문자 표기 기반, 적용한 공사방법·보정계수)
4. 수치를 지어내지 않는다. 보고서에 없는 판정은 "도구로 판정하지 않음"이라고 말한다.
5. `reports/`는 커밋하지 않는다(.gitignore).

## 구조
```
src/dxfcheck/
  archive.py      ZIP 안전 해제 (zip slip·링크·압축폭탄·암호화·cp949 파일명·중첩 ZIP)
  drawing.py      ezdxf 읽기(recover) → Drawing 모델 (문자·블록 속성·레이어·스타일·형상 통계)
  electrical.py   문자 → 전선/보호도체/차단기/부가정보 파싱, 차단기↔전선 회로 연관
  kec.py          KEC 수치표 (허용전류·최소 굵기·PE·전압강하·색상…) — 수치는 여기에만
  rules/          cad_rules · doc_rules · kec_rules  (@rule 등록, Context → Finding)
  analyzer.py     입력 → Report,  report.py  Markdown/JSON,  cli.py
  samples.py      데모 DXF 생성 (python -m dxfcheck.samples <dir>)
```

## 규칙
- 규칙 함수는 I/O 없이 `Context`만 본다. KEC 수치는 `kec.py`에만 둔다.
- 새 규칙은 `tests/test_rules.py`에 통과/위반 사례를 함께 추가한다.
- 근거가 불확실한 조항 번호는 쓰지 않는다. 판정 확신이 낮으면(근접 추정 등) 등급을 '주의'로 낮춘다.
- Python 3.9+, `from __future__ import annotations`.

## 명령
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m dxfcheck.samples /tmp/s && .venv/bin/dxfcheck /tmp/s/samples.zip
```
