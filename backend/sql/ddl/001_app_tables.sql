-- [미검증 · 회사 연결 예정] DDL 미실행. UNVERIFIED.md §1
-- AX 정산 오케스트레이터 결과 데이터셋 (append-only).
-- 운영 원천 데이터셋과 분리된 별도 데이터셋. UPDATE/DELETE 없이 insert 만 하며, 최신 상태는
-- ROW_NUMBER() 로 계산한다 (adapters/bigquery.py). 모든 행이 곧 이력/감사 기록이다.
--
-- 실행 전 `PROJECT_ID` 를 실제 프로젝트로 치환:  sed 's/PROJECT_ID/my-proj/g' 001_app_tables.sql | bq query --use_legacy_sql=false

CREATE SCHEMA IF NOT EXISTS `PROJECT_ID.ax_settlement`
OPTIONS (location = 'asia-northeast3', description = 'AX 정산 오케스트레이터 결과 (보정·예외·보류·이력)');

-- ② 예외 관리 (버전 = 이력)
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.exception_versions` (
  exception_id   STRING NOT NULL,
  version        INT64  NOT NULL,
  month          STRING NOT NULL,          -- YYYY-MM
  plant_id       STRING NOT NULL,
  type           STRING NOT NULL,          -- TRANSFER | MANUAL_ISSUE | PARTNER_CHANGE | PPA_DELAY | OTHER
  status         STRING NOT NULL,          -- REGISTERED | ACTIVE | CLOSED
  base_date      DATE,
  partner_before STRING,
  partner_after  STRING,
  manual_kwh     NUMERIC,
  note           STRING,
  updated_by     STRING,
  updated_at     TIMESTAMP,
  recorded_at    TIMESTAMP NOT NULL
)
CLUSTER BY month, plant_id;

-- 보정 테이블 — 검침량(kWh)만. 금액 컬럼 없음.
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.adjustments` (
  adjustment_id STRING NOT NULL,
  month         STRING NOT NULL,
  plant_id      STRING NOT NULL,
  kind          STRING NOT NULL,           -- MANUAL_INVOICE | PRORATION | METER_CORRECTION
  partner_id    STRING,
  kwh_before    NUMERIC NOT NULL,
  kwh_after     NUMERIC NOT NULL,
  basis         STRING NOT NULL,           -- ACTUAL(실제) | ESTIMATED(추정)
  formula       STRING NOT NULL,           -- 적용 공식 (감사용)
  exception_id  STRING,
  applied_by    STRING,
  applied_at    TIMESTAMP,
  reverts       STRING,                    -- 되돌림 행이면 원래 adjustment_id (재검증 미통과)
  recorded_at   TIMESTAMP NOT NULL
)
CLUSTER BY month, plant_id;

-- 보류 (해제도 새 행)
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.holds` (
  month       STRING NOT NULL,
  plant_id    STRING NOT NULL,
  reason      STRING NOT NULL,
  actor       STRING NOT NULL,
  at          TIMESTAMP NOT NULL,
  released    BOOL NOT NULL,
  released_by STRING,
  released_at TIMESTAMP,
  recorded_at TIMESTAMP NOT NULL
)
CLUSTER BY month, plant_id;

-- 에러 케이스
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.error_cases` (
  case_no     STRING NOT NULL,
  occurred_on DATE NOT NULL,
  month       STRING NOT NULL,
  plant_id    STRING NOT NULL,
  symptom     STRING NOT NULL,
  created_by  STRING,
  recorded_at TIMESTAMP NOT NULL
)
CLUSTER BY month;

-- ③ 대조 결과 스냅샷 (재검증마다 같은 run_id 로 새 스냅샷)
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.run_snapshots` (
  run_id     STRING NOT NULL,
  month      STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING,
  saved_at   TIMESTAMP NOT NULL,
  payload    STRING NOT NULL               -- ReconcileRun JSON
)
PARTITION BY DATE(saved_at)
CLUSTER BY month, run_id;

-- 재검증 이력 (LLM 실패 원인 포함)
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.rechecks` (
  month              STRING NOT NULL,
  plant_id           STRING NOT NULL,
  attempt            INT64 NOT NULL,
  passed             BOOL NOT NULL,
  category           STRING NOT NULL,
  cause              STRING,
  recommended_action STRING,
  evidence           STRING,               -- [{key,label,value}] JSON
  actor              STRING,
  at                 TIMESTAMP NOT NULL,
  `trigger`          STRING,               -- AUTOMATION | MANUAL
  tried_signature    STRING,               -- 자동화 재검증 시 시도한 보정 묶음 서명
  recorded_at        TIMESTAMP NOT NULL
)
CLUSTER BY month, plant_id;

-- 최종 확정(승인) — 존재하면 해당 정산월 잠금
CREATE TABLE IF NOT EXISTS `PROJECT_ID.ax_settlement.approvals` (
  month       STRING NOT NULL,
  actor       STRING NOT NULL,
  at          TIMESTAMP NOT NULL,
  open_holds  ARRAY<STRING>,
  note        STRING,
  recorded_at TIMESTAMP NOT NULL
);
