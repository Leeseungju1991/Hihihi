import type { Category, IssueTag, Priority } from '../api/types';

const toNum = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? null : Number(v));

export function won(v: string | number | null | undefined): string {
  const n = toNum(v);
  return n === null ? '-' : `${Math.round(n).toLocaleString('ko-KR')}원`;
}

export function kwh(v: string | number | null | undefined): string {
  const n = toNum(v);
  return n === null ? '-' : `${Math.round(n).toLocaleString('ko-KR')}kWh`;
}

export function price(v: string | number | null | undefined): string {
  const n = toNum(v);
  return n === null ? '-' : `${n.toLocaleString('ko-KR', { maximumFractionDigits: 4 })}원/kWh`;
}

export function signed(text: string, v: string | number | null | undefined): string {
  const n = toNum(v);
  if (n === null) return '-';
  return (n > 0 ? '+' : '') + text;
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return '-';
  return new Date(v).toLocaleString('ko-KR', { hour12: false });
}

export const CATEGORY_COLOR: Record<Category, string> = {
  PASS: 'positive',
  AUTOMATABLE: 'primary',
  REVIEW: 'warning',
  HOLD: 'grey-7',
  ERROR: 'negative',
};

export const TAG_COLOR: Record<IssueTag, string> = {
  METER_SHORTAGE: 'orange-8',
  DOUBLE_COUNT: 'deep-purple-6',
  PARTNER_MISMATCH: 'blue-8',
  HOURS_EXCEEDED: 'red-7',
  INVALID_TAX_INVOICE: 'brown-6',
};

export const PRIORITY_LABEL: Record<Priority, string> = { HIGH: '높음', MEDIUM: '보통', LOW: '낮음' };

export const KIND_LABEL: Record<string, string> = {
  MANUAL_INVOICE: '수기 송장 결합',
  PRORATION: '일할 안분',
  METER_CORRECTION: '검침량 보정',
};

/** YYYY-MM, 기본값 = 지난달 */
export function defaultMonth(now = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** 서로 다른 값인지 — 표에서 어긋난 값 강조용 (허용 오차 원) */
export function mismatch(a: string | null, b: string | null, tolerance = 10): boolean {
  const x = toNum(a);
  const y = toNum(b);
  if (x === null || y === null) return false;
  return Math.abs(x - y) > tolerance;
}
