// 백엔드 settlement/api 응답 계약. 금액·kWh·단가는 Decimal 문자열.
export type Dec = string;

export type Category = 'PASS' | 'AUTOMATABLE' | 'REVIEW' | 'HOLD' | 'ERROR';
export type IssueTag =
  | 'METER_SHORTAGE'
  | 'DOUBLE_COUNT'
  | 'PARTNER_MISMATCH'
  | 'HOURS_EXCEEDED'
  | 'INVALID_TAX_INVOICE';
export type Priority = 'HIGH' | 'MEDIUM' | 'LOW';
export type ExceptionType = 'TRANSFER' | 'MANUAL_ISSUE' | 'PARTNER_CHANGE' | 'PPA_DELAY' | 'OTHER';
export type ExceptionStatus = 'REGISTERED' | 'ACTIVE' | 'CLOSED';
export type Basis = 'ACTUAL' | 'ESTIMATED';
export type AdjustmentKind = 'MANUAL_INVOICE' | 'PRORATION' | 'METER_CORRECTION';

export interface Meta {
  user: { email: string; is_approver: boolean };
  categories: Record<Category, string>;
  tags: Record<IssueTag, string>;
  exception_types: { value: ExceptionType; label: string; required: string[] }[];
  exception_statuses: Record<ExceptionStatus, string>;
  rules: Record<string, string | number>;
}

export interface Plant {
  plant_id: string;
  name: string;
  capacity_kw: Dec;
  region: string;
  partner_id: string;
}

export interface Evidence {
  key: string;
  label: string;
  value: string;
}

export interface Adjustment {
  adjustment_id: string;
  month: string;
  plant_id: string;
  kind: AdjustmentKind;
  partner_id: string;
  kwh_before: Dec;
  kwh_after: Dec;
  kwh_delta: Dec;
  basis: Basis;
  formula: string;
  exception_id: string;
  applied_by: string;
  applied_at: string | null;
  reverts: string;
}

export interface PlantResult {
  plant_id: string;
  plant_name: string;
  month: string;
  category: Category;
  journal_amount: Dec;
  invoice_kwh: Dec;
  invoice_amount: Dec;
  tax_amount: Dec;
  unit_price: Dec | null;
  implied_price: Dec | null;
  implied_kwh: Dec | null;
  daily_hours: Dec | null;
  tags: IssueTag[];
  summary: string;
  priority: Priority;
  evidence: Evidence[];
  applied_exception_ids: string[];
  applied_adjustment_ids: string[];
  candidate_adjustments: Adjustment[];
  error: string;
  amount_diff: Dec;
  kwh_diff: Dec | null;
}

export interface ReconcileRun {
  run_id: string;
  month: string;
  created_at: string;
  created_by: string;
  counts: { journal: number; invoice: number; tax_invoice: number };
  results: PlantResult[];
  category_counts: Record<Category, number>;
}

export interface AdjustmentPreview {
  plant_id: string;
  plant_name: string;
  category_before: Category;
  adjustments: Adjustment[];
  kwh_before: Dec;
  kwh_after: Dec;
  implied_price_after: Dec | null;
  predicted_pass: boolean;
  remaining_issues: string[];
}

export interface AutomationPreview {
  run_id: string;
  month: string;
  target_count: number;
  formulas: AdjustmentKind[];
  items: AdjustmentPreview[];
}

export interface RecheckRecord {
  month: string;
  plant_id: string;
  attempt: number;
  passed: boolean;
  category: Category;
  cause: string;
  recommended_action: string;
  evidence: Evidence[];
  actor: string;
  at: string;
  trigger: 'AUTOMATION' | 'MANUAL';
  tried_signature: string;
}

export interface Hold {
  month: string;
  plant_id: string;
  reason: string;
  actor: string;
  at: string;
  released: boolean;
  released_by: string;
  released_at: string | null;
}

export interface SettlementException {
  exception_id: string;
  month: string;
  plant_id: string;
  type: ExceptionType;
  status: ExceptionStatus;
  base_date: string | null;
  partner_before: string;
  partner_after: string;
  manual_kwh: Dec | null;
  note: string;
  version: number;
  updated_by: string;
  updated_at: string | null;
}

export type ExceptionInput = Pick<
  SettlementException,
  'month' | 'plant_id' | 'type' | 'base_date' | 'partner_before' | 'partner_after' | 'note'
> & { manual_kwh: string | null };

export interface ErrorCase {
  case_no: string;
  occurred_on: string;
  month: string;
  plant_id: string;
  symptom: string;
  created_by: string;
}

export interface Explanation {
  cause: string;
  recommended_action: string;
  evidence: Evidence[];
  source: 'RULE' | 'LLM';
  rejected_reason: string;
}

export interface PlantDetail {
  result: PlantResult;
  explanation: Explanation | null;
  rechecks: RecheckRecord[];
  holds: Hold[];
  exceptions: SettlementException[];
  adjustments: Adjustment[];
}

export interface Approval {
  month: string;
  actor: string;
  at: string;
  open_holds: string[];
  note: string;
}

export interface MonthStatus {
  month: string;
  locked: boolean;
  approval: Approval | null;
  latest_run_id: string | null;
  category_counts: Record<Category, number> | null;
}

export interface FinalizeWarning {
  detail: string;
  warnings: string[];
  open_holds: string[];
  unresolved: string[];
}

export interface Report {
  kind: 'monthly' | 'unresolved';
  month: string;
  summary: string;
  summary_source: 'RULE' | 'LLM';
  generated_from_run: string;
  run_at: string;
  load_counts: ReconcileRun['counts'];
  category_counts: Record<Category, number>;
  applied_exception_ids: string[];
  exceptions: { exception_id: string; plant_id: string; type: ExceptionType; status: ExceptionStatus; version: number }[];
  automation: {
    plant_id: string;
    kind: AdjustmentKind;
    partner_id: string;
    kwh_before: Dec;
    kwh_after: Dec;
    basis: Basis;
    basis_label: string;
    formula: string;
    exception_id: string;
    applied_by: string;
    applied_at: string | null;
    reverted: boolean;
  }[];
  estimated_count: number;
  rechecks: { plant_id: string; attempts: number; passed: boolean; last_cause: string; last_action: string; evidence: Evidence[] }[];
  holds: { plant_id: string; reason: string; actor: string; at: string }[];
  items: {
    plant_id: string;
    plant_name: string;
    category: Category;
    journal_amount: Dec;
    invoice_kwh: Dec;
    tax_amount: Dec;
    tags: string[];
    summary: string;
    priority: Priority;
  }[];
  error_cases: { case_no: string; occurred_on: string; plant_id: string; symptom: string }[];
  approval: { actor: string; at: string; open_holds: string[]; note: string } | null;
}
