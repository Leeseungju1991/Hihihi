import { describe, expect, it } from 'vitest';
import { defaultMonth, kwh, mismatch, price, signed, who, won } from './format';

describe('format', () => {
  it('금액·kWh·단가 표기', () => {
    expect(won('1307425')).toBe('1,307,425원');
    expect(won(null)).toBe('-');
    expect(kwh('10850.4')).toBe('10,850kWh');
    expect(price('120.5000')).toBe('120.5원/kWh');
  });

  it('부호 표기', () => {
    expect(signed('10원', '10')).toBe('+10원');
    expect(signed('-10원', '-10')).toBe('-10원');
    expect(signed('0원', '0')).toBe('0원');
  });

  it('불일치 판정 (허용 오차)', () => {
    expect(mismatch('100', '105')).toBe(false);
    expect(mismatch('100', '111')).toBe(true);
    expect(mismatch(null, '1')).toBe(false);
  });

  it('기본 정산월은 지난달', () => {
    expect(defaultMonth(new Date(2026, 0, 15))).toBe('2025-12');
    expect(defaultMonth(new Date(2026, 8, 29))).toBe('2026-08');
  });

  it('처리자는 이메일 대신 계정명만 표기', () => {
    expect(who('fin@corp.com')).toBe('fin');
    expect(who('accounts.google.com:fin@corp.com')).toBe('fin');
    expect(who('')).toBe('-');
  });
});
