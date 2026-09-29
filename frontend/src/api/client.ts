// API 호출부. 회사 프로젝트에서 axios boot(api 인스턴스)를 쓰면 request() 한 곳만 바꾸면 된다.
// 인증은 IAP 가 쿠키로 처리하므로 헤더를 붙이지 않는다.
import type {
  Approval,
  AutomationPreview,
  ErrorCase,
  ExceptionInput,
  Hold,
  Meta,
  MonthStatus,
  Plant,
  PlantDetail,
  RecheckRecord,
  ReconcileRun,
  Report,
  SettlementException,
} from './types';

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api';

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: Record<string, unknown>,
  ) {
    super(typeof body.detail === 'string' ? body.detail : `HTTP ${status}`);
  }

  /** 422 필드 오류 {필드: 메시지} */
  get fieldErrors(): Record<string, string> {
    return (this.body.errors as Record<string, string>) ?? {};
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'include' };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, init);
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

const m = (month: string) => `/months/${encodeURIComponent(month)}`;
const p = (month: string, plantId: string) => `${m(month)}/plants/${encodeURIComponent(plantId)}`;

export const api = {
  meta: () => request<Meta>('GET', '/meta'),
  plants: (q = '') => request<Plant[]>('GET', `/plants?q=${encodeURIComponent(q)}`),

  // ① 데이터 불러오기
  load: (month: string) =>
    request<{ month: string; counts: ReconcileRun['counts']; locked: boolean }>('POST', `${m(month)}/load`),
  status: (month: string) => request<MonthStatus>('GET', `${m(month)}/status`),

  // ③ 3자 대조
  run: (month: string) => request<ReconcileRun>('POST', `${m(month)}/runs`),
  latestRun: (month: string) => request<ReconcileRun>('GET', `${m(month)}/runs/latest`),
  previewAutomation: (runId: string, plantIds?: string[]) =>
    request<AutomationPreview>('POST', `/runs/${runId}/automation/preview`, { plant_ids: plantIds ?? null }),
  executeAutomation: (runId: string, plantIds?: string[]) =>
    request<{ rechecks: RecheckRecord[]; run: ReconcileRun }>('POST', `/runs/${runId}/automation/execute`, {
      plant_ids: plantIds ?? null,
    }),

  // ④ 확인 대상
  detail: (month: string, plantId: string) => request<PlantDetail>('GET', p(month, plantId)),
  recheck: (month: string, plantId: string) => request<RecheckRecord>('POST', `${p(month, plantId)}/recheck`),
  hold: (month: string, plantId: string, reason: string) =>
    request<Hold>('POST', `${p(month, plantId)}/hold`, { reason }),
  releaseHold: (month: string, plantId: string) => request<RecheckRecord>('DELETE', `${p(month, plantId)}/hold`),

  // ② 예외 관리
  exceptions: (month?: string, plantId?: string) => {
    const qs = new URLSearchParams();
    if (month) qs.set('month', month);
    if (plantId) qs.set('plant_id', plantId);
    return request<SettlementException[]>('GET', `/exceptions?${qs.toString()}`);
  },
  createException: (body: ExceptionInput) => request<SettlementException>('POST', '/exceptions', body),
  updateException: (id: string, body: ExceptionInput) =>
    request<SettlementException>('PUT', `/exceptions/${encodeURIComponent(id)}`, body),
  closeException: (id: string) => request<SettlementException>('POST', `/exceptions/${encodeURIComponent(id)}/close`),
  exceptionHistory: (id: string) =>
    request<SettlementException[]>('GET', `/exceptions/${encodeURIComponent(id)}/history`),

  // 에러 케이스
  errorCases: (month?: string) =>
    request<ErrorCase[]>('GET', `/error-cases${month ? `?month=${encodeURIComponent(month)}` : ''}`),
  addErrorCase: (body: Omit<ErrorCase, 'case_no' | 'created_by'>) =>
    request<ErrorCase>('POST', '/error-cases', body),

  // 확정·리포트
  finalize: (month: string, acknowledge: boolean, note = '') =>
    request<Approval>('POST', `${m(month)}/finalize`, { acknowledge, note }),
  report: (month: string, kind: 'monthly' | 'unresolved' = 'monthly') =>
    request<Report>('GET', `${m(month)}/report?kind=${kind}`),
};
