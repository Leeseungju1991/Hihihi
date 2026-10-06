/**
 * dxfcheck API 클라이언트 (TypeScript · Node 18+ / 브라우저 공용, 의존성 없음).
 *
 * 화면(껍데기)에서 쓰는 흐름
 *   1) validate(zip)            → report.packages[0].items21 (E-01~E-21 21개 항목) 표시
 *   2) hasFailures(report)      → [재설계] 버튼 노출
 *   3) sendFeedback(jobId, …)   → 지적별 승인/거부/수정 문자 (선택, 학습됨)
 *   4) redesign(jobId)          → 수정 → 재검증(회귀) 반복 결과 (before/after/changes/manual)
 *   5) downloadUrl(jobId)       → ZIP (수정 도면 + 전후 보고서)
 *
 * Gemini 키는 서버(Cloud Run)가 Secret Manager 에서 읽는다. 이 클라이언트는 키를 다루지 않는다.
 * 응답 형식은 src/dxfcheck/model.py · api.py 와 같다(필드를 바꾸면 이 파일도 함께 바꾼다).
 */

export type Severity = "error" | "warning" | "info";
export type Verdict = "적합" | "조건부 적합" | "부적합" | "검증 불가";
export type ItemStatus = "적합" | "조건부 적합" | "부적합" | "누락" | "해당없음";
export type LlmProvider = "off" | "gemini" | "vertex";

export interface FixOp {
  op: "replace_number" | "replace_text" | "replace_regex" | "set_text" | "set_attrib" | "set_header"
    | "delete_entity" | "set_style" | "regenerate";
  file?: string;
  handle?: string;
  [key: string]: unknown;
}

export interface Fix {
  ops?: FixOp[];
  reason?: string;
  confidence?: "rule" | "majority" | "memory" | "llm" | "generator";
}

export interface Finding {
  id: string;
  rule_id: string;
  category: string;
  severity: Severity;
  title: string;
  message: string;
  reference: string;
  location: { layer?: string; layout?: string; handle?: string; x?: number; y?: number; drawing?: string; basis?: string };
  evidence: string[];
  fix: Fix;
  fixable: boolean;
  file: string;
}

/** 도면별 결과 — 21개(E-01~E-21) 고정 순서 */
export interface Item21 {
  no: string;                 // "E-04"
  name: string;               // 정본 도면명
  status: ItemStatus;
  files: string[];
  keywords: string[];         // 내용 단어 (예: "설비용량 99kW", "15직렬×6병렬", "WHM 계량기")
  summary: string;            // keywords 앞 6개를 ' · ' 로 이은 한 줄
  errors: number;
  warnings: number;
  issues: string[];           // 주요 지적 제목 최대 3개
  finding_ids: string[];
}

export interface CircuitRow {
  breaker: string; cable: string; in_a: number | null; iz_a: number | null;
  result: "적합" | "부적합" | "주의" | "판정불가"; basis: string; note: string;
}

export interface FileReport {
  path: string; kind: "dxf" | "dwg" | "other"; verdict: Verdict; score: number;
  counts: Record<Severity, number>; overview: Record<string, string | number>;
  circuits: CircuitRow[]; findings: Finding[];
}

export interface PackageReport {
  name: string;
  items21: Item21[];
  sheets: Array<Record<string, string>>;
  facts: Record<string, Record<string, string>>;   // 항목 → { 도면번호 | "설계값": 값 }
  metadata: Record<string, unknown>;
  profile: Record<string, unknown>;
  findings: Finding[];
}

export interface Report {
  inputs: string[];
  generated_at: string;
  verdict: Verdict;
  counts: Record<Severity, number>;
  archive_findings: Finding[];
  packages: PackageReport[];
  llm: Record<string, string>;
  files: FileReport[];
  settings: Record<string, unknown>;
}

export interface ValidateResponse { job_id: string; warning: string; report: Report; download_url: string }

export interface FeedbackItem {
  finding_id: string;
  decision: "accept" | "reject" | "correct";
  correction?: string;        // decision=correct: 해당 도면 문자 전체를 이렇게 바꿔라
  note?: string;
}

export interface Change {
  file: string; op: string; handle: string; before: string; after: string; ok: boolean; detail: string;
  finding_id: string; rule_id: string; reason: string; confidence: string; reverted: boolean;
}

export interface RoundLog {
  round: number; applied: number; failed: number; reverted: number; llm_proposals: number;
  regenerated: string[]; errors_before: number; errors_after: number;
  warnings_before: number; warnings_after: number; resolved: string[]; new_errors: string[];
}

export interface ManualItem {
  finding_id: string; rule_id: string; title: string; why: string;
  severity?: Severity; file?: string; message?: string; regenerate?: FixOp;
}

export interface Snapshot { verdict: Verdict; counts: Record<Severity, number>; items21: Item21[] }

export interface RedesignResponse {
  status: "통과" | "개선" | "미해결" | "변경 없음";
  rounds: RoundLog[];
  before: Snapshot;
  after: Snapshot;
  changes: Change[];
  manual: ManualItem[];
  after_report: Report;
  warning: string;
  download_url: string;
}

export interface RedesignOptions {
  max_rounds?: number;        // 기본 3
  llm?: LlmProvider;          // 미인식 표기 해석 (기본: 검증 때 값)
  fix_llm?: LlmProvider;      // 규칙이 못 고친 지적의 LLM 수정안 (기본 off)
}

export interface ClientOptions {
  baseUrl: string;                          // 예: https://dxfcheck-xxxx.a.run.app
  headers?: Record<string, string>;         // 예: IAP/ID 토큰 Authorization
  fetch?: typeof fetch;
}

export class DxfcheckError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** 부적합·주의가 있으면 재설계 버튼을 보인다. */
export function hasFailures(report: Report | Snapshot): boolean {
  return report.counts.error > 0 || report.counts.warning > 0;
}

/** items21 이 없으면(도면번호 미인식) 빈 배열. */
export function items21(report: Report): Item21[] {
  return report.packages[0]?.items21 ?? [];
}

export function createDxfcheckClient(opts: ClientOptions) {
  const f = opts.fetch ?? fetch;
  const base = opts.baseUrl.replace(/\/+$/, "");

  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await f(base + path, { ...init, headers: { ...(opts.headers ?? {}), ...(init.headers ?? {}) } });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = ((await res.json()) as { detail?: string }).detail ?? msg; } catch { /* 본문 없음 */ }
      throw new DxfcheckError(res.status, msg);
    }
    return (await res.json()) as T;
  }

  const json = (body: unknown): RequestInit => ({
    method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" },
  });

  return {
    /** ZIP(또는 DXF) 검증. file: Blob/File (Node 는 new Blob([buffer])) */
    validate(file: Blob, filename: string, o: { llm?: LlmProvider; profile?: string } = {}) {
      const form = new FormData();
      form.append("file", file, filename);
      form.append("llm", o.llm ?? "off");
      form.append("profile", o.profile ?? "");
      return call<ValidateResponse>("/api/validate", { method: "POST", body: form });
    },
    getJob(jobId: string) {
      return call<{ job: Record<string, unknown>; report: Report; redesign: RedesignResponse | null }>(
        `/api/jobs/${jobId}`);
    },
    sendFeedback(jobId: string, items: FeedbackItem[]) {
      return call<{ saved: number; errors: Array<{ finding_id: string; error: string }> }>(
        `/api/jobs/${jobId}/feedback`, json({ items }));
    },
    /** [재설계] 버튼 */
    redesign(jobId: string, o: RedesignOptions = {}) {
      return call<RedesignResponse>(`/api/jobs/${jobId}/redesign`, json(o));
    },
    downloadUrl(jobId: string) {
      return `${base}/api/jobs/${jobId}/download`;
    },
    /** 서버 경유 다운로드가 필요할 때(인증 헤더 포함) */
    async download(jobId: string): Promise<ArrayBuffer> {
      const res = await f(`${base}/api/jobs/${jobId}/download`, { headers: opts.headers });
      if (!res.ok) throw new DxfcheckError(res.status, res.statusText);
      return res.arrayBuffer();
    },
  };
}

export type DxfcheckClient = ReturnType<typeof createDxfcheckClient>;
