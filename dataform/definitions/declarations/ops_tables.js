// [미검증 · 회사 연결 예정] Dataform 미컴파일. UNVERIFIED.md §1
// 운영 원천 테이블 선언 (읽기 전용). schema/name 은 회사 실제 위치로 바꾼다.
// TODO(회사): 데이터셋명 확인
const OPS = "ops_dataset_TODO";

declare({ schema: OPS, name: "pv_biz_bal_item" });       // 분개장 (412 매출)
declare({ schema: OPS, name: "pv_sales_invoice" });      // 송장
declare({ schema: OPS, name: "stg_nts_tax_invoice" });   // 국세청 세금계산서
declare({ schema: OPS, name: "TODO_plant_master" });     // 발전소 마스터
declare({ schema: OPS, name: "TODO_kpx_confirmed_smp" }); // 한전/전력거래소 확정 단가
declare({ schema: OPS, name: "TODO_monitoring_meter" });  // 모니터링(RTU) 누적 발전량 — 그라파나 원천
