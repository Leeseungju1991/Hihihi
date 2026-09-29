// 상단 단계 표시 — 완료/진행중/대기 판정 (순수 함수, 단위 테스트 대상)
export type StepKey = 'load' | 'exceptions' | 'reconcile' | 'review' | 'report';
export type StepState = 'done' | 'current' | 'todo';

export interface StepFacts {
  loaded: boolean; // 데이터 건수를 불러왔는가
  hasRun: boolean; // 3자 대조를 실행했는가
  automatable: number; // 자동화 대상 남은 건수
  unresolved: number; // 확인 대상 + 에러 남은 건수 (보류는 처리된 것으로 본다)
  locked: boolean; // 최종 확정됨
}

export const STEPS: { key: StepKey; no: number; title: string; route: string }[] = [
  { key: 'load', no: 1, title: '데이터 불러오기', route: 'settlement-load' },
  { key: 'exceptions', no: 2, title: '예외 관리', route: 'settlement-exceptions' },
  { key: 'reconcile', no: 3, title: '3자 대조', route: 'settlement-reconcile' },
  { key: 'review', no: 4, title: '확인 대상', route: 'settlement-review' },
  { key: 'report', no: 5, title: '리포트 · 확정', route: 'settlement-report' },
];

export function stepDone(key: StepKey, f: StepFacts): boolean {
  if (f.locked) return true;
  switch (key) {
    case 'load':
      return f.loaded || f.hasRun;
    case 'exceptions':
      // 예외는 선택 단계 — 등록된 예외가 대조에 반영(대조 실행)되면 완료로 본다
      return f.hasRun;
    case 'reconcile':
      return f.hasRun && f.automatable === 0;
    case 'review':
      return f.hasRun && f.automatable === 0 && f.unresolved === 0;
    case 'report':
      return false;
  }
}

/** 현재 보고 있는 단계는 '진행중', 나머지는 완료/대기. 확정 후에는 모두 완료. */
export function stepStates(current: StepKey | null, f: StepFacts): Record<StepKey, StepState> {
  const out = {} as Record<StepKey, StepState>;
  for (const s of STEPS) {
    if (f.locked) out[s.key] = 'done';
    else if (s.key === current) out[s.key] = 'current';
    else out[s.key] = stepDone(s.key, f) ? 'done' : 'todo';
  }
  return out;
}

/** 전체 진행률 0~1 */
export function progress(f: StepFacts): number {
  const done = STEPS.filter((s) => stepDone(s.key, f)).length;
  return done / STEPS.length;
}
