# 회사 코드 합치기 가이드

> **프리즘/BigQuery 조회 · IAP · LLM 연동은 기능만 구현했고 검증하지 않았습니다.** 연결 순서와 대상 파일은 [UNVERIFIED.md](UNVERIFIED.md)를 보세요.

이 레포는 회사 인프라 없이 만들 수 있는 부분(규칙 엔진·워크플로·API·화면·DDL)을 끝내 둔 상태입니다.
회사에서는 **아래 체크리스트의 `TODO(회사)`만 채우면** 됩니다. 로직은 수정하지 않아도 됩니다.

```
[완료 · 그대로 복사]                      [회사에서 채울 것]
backend/settlement/engine/   규칙 엔진     dataform/definitions/sources/*.sqlx  컬럼 매핑
backend/settlement/workflow/ 워크플로      dataform/definitions/declarations/   운영 테이블 위치
backend/settlement/api/      FastAPI       backend/settlement/api/auth.py      user-py 연결
backend/settlement/adapters/ BQ·메모리     backend/sql/ddl/                    PROJECT_ID 치환 후 실행
frontend/src/                Quasar 화면   deploy/helm/                        umbrella values 에 맞춤
```

---

## 1. 원천 매핑 (Dataform) — 가장 먼저

앱은 운영 테이블을 직접 읽지 않습니다. `ax_settlement_src` 데이터셋의 **정규화 뷰 7개**만 읽습니다.
그래서 회사 스키마에 맞출 곳은 `.sqlx` 파일의 SELECT 절뿐이고, Python 코드는 수정하지 않아도 됩니다.

| 정규화 뷰 | 원천 | 컬럼 계약 | 선행 확인 |
|---|---|---|---|
| `v_plant` | 발전소 마스터 | plant_id, name, capacity_kw, region, partner_id | region = 인근 발전소 그룹 기준 |
| `v_journal_412` | `pv_biz_bal_item` | entry_id, plant_id, month(YYYY-MM), partner_id, amount | **분개 기준 테이블 확정**, 412 필터 |
| `v_sales_invoice` | `pv_sales_invoice` | invoice_id, plant_id, month, partner_id, meter_kwh, amount | 취소 송장 제외 조건 |
| `v_tax_invoice` | `stg_nts_tax_invoice` | nts_id, plant_id, month, partner_id, supply_amount, status(VALID/DISABLE), issue_date | disable 판정 컬럼, 사업자번호→발전소 매핑 |
| `v_confirmed_price` | 한전 확정 SMP (+발전소별 계약단가) | month, plant_id(NULL=공통), unit_price | 고정가/PPA 단가 원천 |
| `v_meter_cumulative` | 모니터링(RTU) 누적 발전량 | plant_id, date, cumulative_kwh | **모니터링 발전량 원천 테이블** (그라파나 데이터 소스) |
| `v_daily_hours_history` | 위 뷰에서 파생 | month, plant_id, daily_hours | 수정할 필요 없음 |

작업 순서
1. `declarations/ops_tables.js`의 데이터셋·테이블명을 실제 이름으로 바꿉니다.
2. 각 `.sqlx`의 `TODO(회사)` SELECT 절을 실제 컬럼으로 바꿉니다. `columns`와 `assertions`는 그대로 둡니다.
3. `dataform run --tags` 또는 콘솔에서 실행합니다. `uniqueKey`·`nonNull` assertion이 매핑 실수를 잡아 줍니다.

> 주의: **월 형식은 반드시 `'YYYY-MM'` 문자열**, 금액·kWh는 `NUMERIC`이어야 합니다. FLOAT는 쓰지 않습니다.

## 2. 결과 데이터셋 (BigQuery)

```bash
sed 's/PROJECT_ID/<프로젝트>/g' backend/sql/ddl/001_app_tables.sql | bq query --use_legacy_sql=false
```

- 모든 테이블은 **append-only**입니다. UPDATE/DELETE를 쓰지 않고, 최신 상태는 `ROW_NUMBER()`로 계산합니다. 그래서 모든 행이 그대로 감사 이력이 됩니다.
- 서비스 계정 권한
  - `ax_settlement_src`: `roles/bigquery.dataViewer` (운영 원천 뷰가 참조하는 데이터셋도 dataViewer)
  - `ax_settlement`: `roles/bigquery.dataEditor`
  - 프로젝트: `roles/bigquery.jobUser`
  - **운영 데이터셋에는 쓰기 권한을 주지 않습니다.** 이렇게 하면 "운영 DB 쓰기 0"이 권한 수준에서 보장됩니다.
- 실행 env: `AX_BACKEND=bigquery`, `AX_BQ_PROJECT`, (옵션) `AX_BQ_SRC_DATASET`, `AX_BQ_APP_DATASET`, `AX_BQ_LOCATION`

`adapters/bigquery.py`는 SQL·파라미터·직렬화를 FakeExecutor로만 검증했습니다(`tests/test_bigquery_adapter.py`).
**실제 BigQuery에서는 처음 실행해 보는 것**이므로, 첫 실행에서 타입 캐스팅 오류가 나면 이 파일만 수정하면 됩니다.

## 3. 인증 — `user-py` 연결

교체 지점은 **`backend/settlement/api/auth.py`의 `current_user()` 함수 하나**입니다.

```python
# 현재: IAP 헤더(X-Goog-Authenticated-User-Email) → User(email, is_approver)
# 회사: user-py 의 현재 사용자 의존성으로 바꾸고, User(email=..., is_approver=<권한 판정>) 만 반환
```

- 라우터는 모두 `Depends(current_user)`를 쓰므로 다른 곳은 바꿀 필요가 없습니다.
- 확정(승인) 권한은 `User.is_approver`로 판단합니다. 현재는 `AX_APPROVERS` env로 판정하며, user-py의 역할로 대체하면 됩니다.
- 작성자·처리자·승인자는 모두 `user.email`로 자동 기록됩니다.

## 4. 프론트 (Quasar) 합치기

아래 파일을 회사 Quasar 앱의 `src/`로 복사합니다(경로를 유지하면 import를 수정하지 않아도 됩니다).

```
src/api/{client,types}.ts
src/components/*            (StepNav: 상단 단계 진행 표시)
src/composables/useTheme.ts (라이트/다크 전환, localStorage 저장)
src/layouts/SettlementLayout.vue
src/pages/{Load,Exceptions,Reconcile,Review,Report}Page.vue
src/stores/settlement.ts
src/utils/{format,steps}.ts
src/css/app.css            (색상 토큰·타이포·애니메이션·인쇄 — 회사 전역 CSS와 겹치면 토큰만 가져감)
```

1. `src/router/routes.ts`의 `settlementRoutes` 배열을 회사 routes에 추가합니다. 회사 메인 레이아웃 안에 넣으려면 `SettlementLayout`을 회사 레이아웃의 child로 둡니다.
2. `quasar.config`의 `framework.plugins`에 `Dialog`, `Notify`, `Loading`을 추가합니다. 다크 모드를 쓰려면 `framework.config.dark: 'auto'`도 설정합니다.
   - 폰트: `npm i pretendard`. `App.vue`에서 `pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css`를 import하면 CDN 없이 번들됩니다. 회사 공통 폰트가 있으면 이 import는 생략합니다.
3. 회사가 axios boot(`api` 인스턴스)를 쓰면 `src/api/client.ts`의 `request()` 함수 하나만 axios로 바꿉니다.
4. Pinia가 없으면 `stores/index.ts`를 추가합니다.
5. PDF는 브라우저 인쇄로 처리합니다(`window.print`, 인쇄 CSS 포함). 서버 PDF가 필요하면 `/report` JSON을 그대로 렌더링하면 됩니다.

> Next.js(React 19) 쪽에 붙여야 한다면 `api/types.ts`와 `api/client.ts`는 그대로 쓸 수 있고, 화면만 다시 만들어야 합니다.

## 5. 배포

- `backend/Dockerfile` → Cloud Run 또는 GKE (`PORT` env 지원)
- `frontend/Dockerfile` → nginx 정적 서빙 (8080)
- `deploy/helm/ax-settlement/`: umbrella chart의 subchart용 최소 템플릿입니다. **helm lint를 돌려보지 않았습니다.** 회사 공통 subchart 템플릿이 있으면 values만 옮기고 이 템플릿은 버립니다.
- IAP: Ingress(BackendConfig `iap.enabled`) 뒤에 두고, 백엔드에 `AX_IAP_AUDIENCE`를 설정하면 JWT 서명까지 검증합니다.

## 6. LLM (Vertex AI)

- `AX_LLM=vertex`, `AX_LLM_MODEL=<회사 허용 모델>`, `GOOGLE_CLOUD_PROJECT`, (옵션) `AX_LLM_LOCATION`
- `pip install ".[vertex]"`
- 모델 호출은 `llm/vertex.py`의 `complete(prompt) -> str` 한 함수에만 있습니다. 회사 LLM 게이트웨이가 있으면 이 함수만 바꾸면 됩니다.
- 가드
  - 근거 키가 입력에 없거나, 문장에 **입력에 없는 숫자**가 있으면 LLM 응답을 폐기하고 규칙 기반 설명으로 대체합니다.
  - 대체 사유는 화면에 표시됩니다.
  - LLM 출력으로 금액·발전량을 쓰는 코드는 없습니다.

## 7. 결정해 둔 가정 (회사에서 확인 후 조정)

| 항목 | 현재 값·규칙 | 위치 |
|---|---|---|
| SMP 역산 허용 편차 | 0.5원/kWh | `config.py` (`AX_SMP_TOLERANCE`) |
| 분개↔세금계산서 허용 차이 | 10원 | `AX_AMOUNT_TOLERANCE` |
| 발전시간 상한 | 과거 12개월 99퍼센타일, 모집단 20개 미만이면 7.0h | `AX_HOURS_*` |
| 우선순위 | 차이 100만원 이상 높음, 10만원 이상 보통 | `AX_PRIORITY_*` |
| 일할 안분 | 기준일 = 변경 **후** 조합의 첫날. 기준일 전날까지 변경 전 조합 | `engine/adjustments.py` |
| 누적값 보정 | 월초·익월초 ±1일 이내 스냅샷만 인정, 음수 차이(리셋)는 무시 | `measured_month_kwh` |
| 추정 보정 | 같은 region의 통과 발전소 3개 이상, 비발전량 중앙값 × 설비용량 | `MIN_PEERS` |
| 자동화 원자성 | 발전소 단위로, 재검증 통과 시에만 유지하고 미통과면 되돌림 행을 기록. 같은 보정 묶음은 다시 자동화 대상으로 제안하지 않음 | `workflow/service.py` |
| 확정 경고 | 보류 건 + 미해결(자동화·확인·에러) 건이 있으면 경고, 확인 후 확정 가능 | `finalize` |
| 이중계상 | 같은 (조합, kWh, 금액) 송장, 같은 (조합, 금액) 세금계산서·분개, 역산 대비 검침량 초과 | `evaluate` |
| 무효 계산서 | 유효 상태 음수 계산서, 또는 무효만 있고 유효 합계 0 | `evaluate` |

## 8. 회사 세션 시작 프롬프트 예시

```
INTEGRATION.md 와 CLAUDE.md 를 읽고 §1 원천 매핑부터 진행해줘.
운영 테이블 스키마는 아래와 같아: (bq show --schema 결과 붙여넣기)
```

Claude에게 스키마를 붙여 주면 `.sqlx` 매핑만 작성하면 되고, 로직은 다시 설명하지 않아도 됩니다.
