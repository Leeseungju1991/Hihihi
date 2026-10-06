# CLAUDE.md — AX 정산 오케스트레이터

발전매출 확정 정산에서 분개(412)·송장·세금계산서를 발전소 단위로 3자 대조하고, 예외·보정으로 해소한 뒤 담당자가 확정한다.
회사 통합 작업은 `INTEGRATION.md`를 따른다.

## 미검증 연동
프리즘/BigQuery 조회(`adapters/bigquery.py`, `dataform/`), IAP(`api/auth.py`), LLM(`llm/vertex.py`)은 **기능만 구현하고 검증하지 않았다.**
코드에 `[미검증 · 회사 연결 예정]`으로 표기되어 있다. 연결과 검증은 `UNVERIFIED.md` 순서를 따른다.

## 불변 규칙 (변경 금지)
- **운영 원천은 읽기 전용.** `SourceRepository`에는 쓰기 메서드가 없다. 쓰기는 `ax_settlement` 데이터셋에만 한다.
- **금액은 보정하지 않는다.** 보정(`Adjustment`)은 kWh만 바꾼다. 분개·세금계산서 금액은 원천 그대로 쓴다.
- **append-only.** 결과 테이블에 UPDATE/DELETE를 하지 않는다. 수정·종료·해제·되돌림은 모두 새 행으로 남긴다.
- **LLM은 설명만 한다.** 판정·금액·발전량을 결정하지 않는다. 출력은 `llm/explainer.py` 가드를 통과해야 표시된다.
- **최종 확정은 사람이 한다.** 확정 후에는 해당 정산월이 잠긴다(423).
- 규칙 엔진(`engine/`)은 I/O 없는 순수 함수로 유지한다.

## 구조
```
backend/settlement/
  domain/      models.py(dataclass), validation.py(예외 유형별 필수값)
  engine/      ledger(발전소 원장) → adjustments(보정 후보) → reconcile(1~4단계·분류)
  workflow/    service.py — 대조·자동화(미리보기/실행/재검증/되돌림)·보류·예외·확정
  llm/         explainer.py(프롬프트·가드·규칙 기반 대체), vertex.py
  report/      builder.py — 리포트 JSON
  adapters/    memory.py(로컬), bigquery.py(회사), codec.py
  api/         app.py(FastAPI), auth.py(IAP/user-py 교체 지점)
  fixtures.py  가상 시나리오 12개소 (P001~P012)
frontend/src/  Quasar 페이지 ①~⑤, api/types.ts(백엔드 계약)
dataform/      정규화 원천 뷰 — 회사 컬럼 매핑은 여기서만
```

## 명령
```bash
# 백엔드 (Python 3.8~3.12, pydantic v1/v2 모두 지원)
cd backend && uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
AX_DEV_USER=dev@local AX_APPROVERS=dev@local .venv/bin/uvicorn settlement.api.app:app --reload   # :8000, 가상 데이터

# 프론트
cd frontend && npm install && npm run dev        # :9000, /api → :8000 프록시
npm run typecheck && npm test && npm run build
npm run e2e                                      # Playwright: ①~⑤ 전 흐름 × 라이트/다크 (백엔드 venv 필요)
#   브라우저가 없으면 npx playwright install chromium, 또는 PW_CHROMIUM=<chrome 경로>
```

## 코드 규칙
- Python 3.8 호환: `from __future__ import annotations`, `typing.List/Dict/Optional`, match·walrus·`str.removeprefix` 금지.
- API 요청 스키마는 pydantic v1/v2 공용 문법만 쓴다(validator 금지). 검증은 `domain/validation.py`에 둔다.
- 금액·kWh는 `Decimal`로 다루고, JSON에서는 문자열로 보낸다(`api/serialize.py`). float를 쓰지 않는다.
- 응답 필드를 바꾸면 `frontend/src/api/types.ts`도 함께 바꾼다.
- 화면 색상은 `src/css/app.css`의 토큰(`--app-*`, `.text-muted`, `.callout*`)만 쓴다. `bg-white`·`text-grey-7` 같은 고정색은 다크 모드를 깨뜨린다.
- 애니메이션은 절제한다: 페이지 전환 160ms, 카드 hover, 진행중 점 정도. `prefers-reduced-motion`을 지킨다.
- 화면에 이메일 전체를 표시하지 않는다. 처리자는 `who()`로 계정명만 표시한다(원본은 이력에 저장).
- 새 규칙을 추가하면 `fixtures.py`에 시나리오를 추가하고 `tests/test_engine.py`에 기대 분류를 적는다.

## DXF 도면 검증기 (`autocad-dxf-validator/`)
정산 오케스트레이터와 별개 프로젝트다. 사용자가 DXF 도면 ZIP을 첨부하면 `autocad-dxf-validator/CLAUDE.md` 절차대로 `dxfcheck`을 돌려 KEC 기준 검증 결과를 보고한다.
