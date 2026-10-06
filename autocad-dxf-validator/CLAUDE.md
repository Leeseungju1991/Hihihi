# CLAUDE.md — AutoCAD DXF 검증기 (KEC 기준)

AutoCAD 자동화 설계로 생성된 DXF 도면을 **파일·구조 / CAD 품질 / 도면 표기 / KEC 전기 / 도면 세트 정합성(E-01~E-21) / 학습 기준 비교**로 검증한다.

## 사용자가 ZIP(또는 DXF)을 첨부하면
1. 첨부 파일 경로를 확인한다. 압축은 신뢰하지 않는 입력이므로 직접 풀지 말고 도구에 넘긴다(도구가 안전 해제).
2. 첨부의 용도를 구분한다. 분명하지 않으면 묻는다.
   - **기준(학습)용** — "기준으로 학습", "정상 도면", "승인본" 등: `learn`으로 프로파일에 누적
   - **검증 대상** — 그 외: 검증 실행. `profiles/`에 프로파일이 있으면 `--profile`로 함께 비교
3. 실행:
   ```bash
   cd autocad-dxf-validator
   [ -x .venv/bin/dxfcheck ] || (uv venv -q .venv && uv pip install -q --python .venv/bin/python -e ".[dev]")
   .venv/bin/dxfcheck learn <기준.zip> --profile profiles/<이름>.json          # 학습(누적)
   .venv/bin/dxfcheck <첨부.zip> -f both -o reports/<이름> [--profile profiles/<이름>.json]   # 검증
   ```
   - 학습 로그에 "기준 도면에 부적합 N건"이 나오면 그 도면이 정말 승인본인지 사용자에게 확인한다.
   - `profiles/*.json`은 실제 도면에서 뽑은 레이어·문구를 담는다. 커밋 전에 사용자에게 묻는다
     (컨테이너는 휘발되므로 커밋하지 않으면 다음 세션에서 학습 결과가 사라진다는 점도 알린다).
4. `reports/<이름>.md`를 읽고 사용자에게 한국어로 답한다:
   - 종합 판정(적합 / 조건부 적합 / 부적합 / 검증 불가)과 파일별 점수
   - 도면 세트가 인식되면: 도면 인식 표, 도면 간 수치 대조표의 ⚠ 항목, 세트 지적 사항(SET-*)
   - 학습 비교(PRF-*)는 기준 샘플 수와 함께 말한다(샘플 3개 미만이면 '참고' 등급)
   - **부적합** 항목 전부: 무엇이, 어디서(레이어·좌표·원문), 어느 KEC 조항에 어긋나는지, 어떻게 고치는지
   - 주의 항목은 묶어서 요약, 참고 항목은 개수와 핵심만
   - 회로 대조표에서 부적합·주의 회로
   - 검토 한계(문자 표기 기반, 적용한 공사방법·보정계수)
5. 수치를 지어내지 않는다. 보고서에 없는 판정은 "도구로 판정하지 않음"이라고 말한다.
6. `reports/`는 커밋하지 않는다(.gitignore).

## 구조
```
src/dxfcheck/
  archive.py      ZIP 안전 해제 (zip slip·링크·압축폭탄·암호화·cp949 파일명·중첩 ZIP)
  drawing.py      ezdxf 읽기(recover) → Drawing 모델 (문자·블록 속성·레이어·스타일·형상 통계)
  electrical.py   문자 → 전선/보호도체/차단기/부가정보 파싱, 차단기↔전선 회로 연관
  kec.py          KEC 수치표 (허용전류·최소 굵기·PE·전압강하·색상…) — 수치는 여기에만
  rules/          cad_rules · doc_rules · kec_rules  (@rule 등록, Context → Finding)
                  set_rules  도면 세트 E-01~E-21 (@set_rule, SetContext → Finding)
  drawingset.py   도면번호 인식(파일명→표제란→문자), 정본 목록(CATALOG), 사실 추출, XRECORD 메타데이터 매핑
  profile.py      기준 도면 학습(통계 프로파일)·비교 (PRF-*)
  analyzer.py     입력 → Report,  report.py  Markdown/JSON,  cli.py
  samples.py      데모 DXF 생성 (python -m dxfcheck.samples <dir>) — 분전반 정상/불량, 태양광 세트 정상/불량
```

## 규칙
- 규칙 함수는 I/O 없이 `Context`만 본다. KEC 수치는 `kec.py`에만 둔다.
- 새 규칙은 `tests/test_rules.py`에 통과/위반 사례를 함께 추가한다.
- 근거가 불확실한 조항 번호는 쓰지 않는다. 판정 확신이 낮으면(근접 추정 등) 등급을 '주의'로 낮춘다.
- 세트 기준값: XRECORD 설계 메타데이터 → 없으면 도면 간 다수값. `p_pv_kw`는 목표 용량이라 기준값으로 쓰지 않는다.
- XRECORD 형식·메타데이터 키 이름은 [미검증 · 실제 SolarAutoDesign 출력으로 확인 예정] — `config.meta_keys`로 맞춘다.
- Python 3.9+, `from __future__ import annotations`.

## 명령
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m dxfcheck.samples /tmp/s && .venv/bin/dxfcheck /tmp/s/samples.zip
```
