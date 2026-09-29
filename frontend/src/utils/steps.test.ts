import { describe, expect, it } from 'vitest';
import { progress, stepDone, stepStates, type StepFacts } from './steps';

const base: StepFacts = { loaded: false, hasRun: false, automatable: 0, unresolved: 0, locked: false };

describe('steps', () => {
  it('처음에는 현재 단계만 진행중, 나머지 대기', () => {
    const s = stepStates('load', base);
    expect(s).toEqual({ load: 'current', exceptions: 'todo', reconcile: 'todo', review: 'todo', report: 'todo' });
    expect(progress(base)).toBe(0);
  });

  it('불러오기 후 1단계 완료', () => {
    expect(stepDone('load', { ...base, loaded: true })).toBe(true);
    expect(stepStates('reconcile', { ...base, loaded: true }).load).toBe('done');
  });

  it('자동화 대상이 남으면 3자 대조는 미완료', () => {
    const f = { ...base, loaded: true, hasRun: true, automatable: 2, unresolved: 3 };
    expect(stepDone('reconcile', f)).toBe(false);
    expect(stepDone('review', f)).toBe(false);
    expect(stepDone('exceptions', f)).toBe(true);
  });

  it('미해결 0 이면 확인 대상 완료, 확정 전 리포트는 미완료', () => {
    const f = { ...base, loaded: true, hasRun: true };
    expect(stepDone('review', f)).toBe(true);
    expect(stepDone('report', f)).toBe(false);
    expect(progress(f)).toBeCloseTo(0.8);
  });

  it('확정되면 모두 완료 (현재 단계 포함)', () => {
    const f = { ...base, hasRun: true, unresolved: 3, locked: true };
    expect(Object.values(stepStates('review', f))).toEqual(['done', 'done', 'done', 'done', 'done']);
    expect(progress(f)).toBe(1);
  });
});
