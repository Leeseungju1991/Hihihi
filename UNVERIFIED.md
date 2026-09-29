# 미검증 연동 목록 — 회사에서 연결·검증 예정

아래 3가지 외부 연동은 **기능(코드)만 구현했고 실제 연동 검증은 하지 않았습니다.**
이 개발 환경에서는 회사 GCP·IAP·모델에 접근할 수 없기 때문입니다.
회사에서 연결할 때 이 문서를 체크리스트로 사용합니다.

코드에서는 `[미검증 · 회사 연결 예정]` 표기로 찾을 수 있습니다.

```bash
grep -rn "미검증 · 회사 연결 예정" backend dataform
```

| # | 연동 | 구현 위치 | 현재 상태 | 로컬 대체 동작 |
|---|---|---|---|---|
| 1 | **프리즘 / BigQuery 조회** (운영 원천 읽기 + 결과 저장) | `backend/settlement/adapters/bigquery.py`<br>`dataform/definitions/**`<br>`backend/sql/ddl/001_app_tables.sql` | SQL 문자열·파라미터 바인딩·직렬화만 FakeExecutor로 단위 테스트함. **실제 BigQuery 실행, Dataform 컴파일, DDL 실행은 해보지 않음.** 원천 컬럼 매핑은 `TODO(회사)` 자리표시 상태 | `AX_BACKEND=memory` (기본값): `fixtures.py` 가상 데이터 |
| 2 | **IAP 인증** (+ user-py) | `backend/settlement/api/auth.py` `_verify_iap_jwt()`, `current_user()` | IAP 헤더(`X-Goog-Authenticated-User-Email`)에서 사용자를 읽는 경로만 테스트함. **JWT 서명 검증(`AX_IAP_AUDIENCE`)과 user-py 연결은 실행하지 않음** | `AX_DEV_USER` env로 고정 사용자 |
| 3 | **LLM 연동** (Vertex AI) | `backend/settlement/llm/vertex.py` `make_vertex_complete()` | **실제 모델 호출은 하지 않음.** 프롬프트 생성, 가드(근거 숫자 검증), 실패 시 규칙 기반 대체는 가짜 모델로 테스트함 | `AX_LLM` 미설정 (기본값): 규칙 기반 설명·요약 |

위 3가지 외 배포 파일(`Dockerfile`, `deploy/helm/`)도 빌드·lint를 실행하지 않았습니다.

## 회사에서 연결 순서

1. **프리즘 / BigQuery**
   1. `dataform/definitions/declarations/ops_tables.js`의 운영 데이터셋·테이블명을 채웁니다.
   2. `dataform/definitions/sources/*.sqlx`의 `TODO(회사)` SELECT 절을 실제 컬럼으로 매핑합니다.
   3. Dataform을 실행해 assertion(uniqueKey·nonNull) 통과를 확인합니다.
   4. `backend/sql/ddl/001_app_tables.sql`의 `PROJECT_ID`를 치환한 뒤 실행합니다.
   5. `AX_BACKEND=bigquery`, `AX_BQ_PROJECT=...`로 기동하고 ① 데이터 불러오기 건수가 운영과 일치하는지 봅니다.
   6. 사내 "프리즘" 조회 계층이 BigQuery 직접 조회가 아니라 별도 API라면, `adapters/bigquery.py`의 `Executor.query()` 한 메서드만 프리즘 호출로 바꿉니다. SQL과 파라미터는 그대로 씁니다.
2. **IAP / user-py**
   1. `api/auth.py`의 `current_user()`를 user-py 의존성으로 교체합니다. 반환값 `User(email, is_approver)`는 유지합니다.
   2. `AX_IAP_AUDIENCE`를 설정하고 IAP 뒤에서 401/403 흐름을 확인합니다.
3. **LLM**
   1. `pip install ".[vertex]"` 후 `AX_LLM=vertex`, `AX_LLM_MODEL`, `GOOGLE_CLOUD_PROJECT`를 설정합니다.
   2. ④ 상세 화면의 실패 원인 배지가 `LLM 분석`으로 표시되는지 봅니다. `규칙 기반`이면 가드가 LLM 응답을 폐기한 것이고, 폐기 사유는 화면에 표시됩니다.
   3. 사내 LLM 게이트웨이를 쓰면 `vertex.py`의 `complete(prompt) -> str` 한 함수만 바꿉니다.

## 검증 완료 범위 (참고)

- 규칙 엔진·워크플로·API·리포트: 백엔드 pytest (Python 3.8/3.12, pydantic v1/v2)
- 화면: vue-tsc 타입 검사, vitest 단위 테스트, Playwright E2E (라이트·다크 전 흐름)
- 모두 메모리 저장소와 가상 데이터 기준입니다.
