// ①~⑤ 전 흐름 기능 점검. 한 페이지로 순서대로 진행한다(상태 누적).
// light 프로젝트 = 2026-08, dark 프로젝트 = 2026-07 (서로 다른 정산월이라 확정 잠금이 섞이지 않음)
import { expect, test, type Page } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

let page: Page;
let month: string;
const consoleErrors: string[] = [];

const step = (title: string) => page.locator('.step-nav .step', { hasText: title });
const btn = (text: string) => page.locator('button.q-btn', { hasText: text });
const card = (label: string) => page.locator('.hover-lift', { hasText: label });

async function goStep(title: string) {
  await step(title).click();
  await expect(step(title)).toHaveClass(/router-link-exact-active/);
}

test.beforeAll(async ({ browser }, testInfo) => {
  const dark = testInfo.project.name === 'dark';
  month = dark ? '2026-07' : '2026-08';
  const use = testInfo.project.use;
  const ctx = await browser.newContext({
    baseURL: use.baseURL ?? 'http://127.0.0.1:9765',
    viewport: { width: 1440, height: 900 },
    locale: 'ko-KR',
    colorScheme: dark ? 'dark' : 'light',
    reducedMotion: 'reduce',
  });
  page = await ctx.newPage();
  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
  page.on('pageerror', (e) => consoleErrors.push(String(e)));
  await page.goto('/settlement/load');
  await expect(page.locator('.brand__title')).toHaveText('AX 정산 오케스트레이터');
  const monthInput = page.getByLabel('정산월');
  await monthInput.fill(month);
  await monthInput.press('Enter');
  await expect(page.getByText(`정산월 ${month}`)).toBeVisible();
});

test.afterAll(async () => {
  await page.context().close();
});

test('헤더: 이메일 미표기 · 테마(OS 설정 추종) · 단계 진행중 표시', async ({}, testInfo) => {
  const header = page.locator('.app-header');
  await expect(header).not.toContainText('@');
  const expectDark = testInfo.project.name === 'dark';
  await expect(page.locator('body')).toHaveClass(expectDark ? /body--dark/ : /body--light/);
  await expect(step('데이터 불러오기')).toHaveClass(/step--current/);
  await expect(step('데이터 불러오기')).toContainText('진행중');
  await expect(step('3자 대조')).toContainText('대기');
});

test('테마 전환 버튼은 색을 반전하고 새로고침 후에도 유지', async ({}, testInfo) => {
  const wasDark = testInfo.project.name === 'dark';
  await page.getByRole('button', { name: '테마 전환' }).click();
  await expect(page.locator('body')).toHaveClass(wasDark ? /body--light/ : /body--dark/);
  await page.reload();
  await expect(page.locator('body')).toHaveClass(wasDark ? /body--light/ : /body--dark/);
  // 원래 테마로 복귀
  await page.getByRole('button', { name: '테마 전환' }).click();
  await expect(page.locator('body')).toHaveClass(wasDark ? /body--dark/ : /body--light/);
  const monthInput = page.getByLabel('정산월');
  await monthInput.fill(month);
  await monthInput.press('Enter');
});

test('① 데이터 불러오기: 건수 표기 후 1단계 완료', async () => {
  await page.getByRole('button', { name: '데이터 불러오기' }).click();
  await expect(page.getByText('13건')).toBeVisible();
  await expect(page.getByText('12건')).toBeVisible();
  await expect(page.getByText('16건')).toBeVisible();
  await goStep('예외 관리');
  await expect(step('데이터 불러오기')).toContainText('완료');
});

test('② 예외 관리: 필수값 즉시 검증 · 등록 · 이력', async () => {
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await page.getByRole('button', { name: '예외 등록' }).click();
  const dialog = page.locator('.q-dialog--modal');
  await dialog.getByRole('button', { name: '등록' }).click();
  await expect(dialog.getByText('발전소를 선택하세요')).toBeVisible();
  await expect(dialog.getByText('필수 입력입니다').first()).toBeVisible();

  // 유형 '기타' → 비고만 필수
  await dialog.getByLabel('예외 유형 *').click();
  await page.getByRole('option', { name: '기타' }).click();
  await dialog.getByLabel('발전소 * (마스터 검색)').fill('P001');
  await page.getByRole('option', { name: /P001/ }).click();
  await dialog.getByLabel('비고 *').fill('E2E 메모');
  await dialog.getByRole('button', { name: '등록' }).click();
  await expect(page.locator('.q-notification', { hasText: '저장됨' })).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(3);

  await page.locator('tbody tr', { hasText: 'E2E 메모' }).getByRole('button').first().click(); // 이력
  await expect(page.locator('.q-dialog--modal')).toContainText('변경 이력');
  await expect(page.locator('.q-dialog--modal')).toContainText('v1');
  await expect(page.locator('.q-dialog--modal')).not.toContainText('@');
  await page.keyboard.press('Escape');
});

test('③ 3자 대조 → 자동화 안내창 → 실행 → 자동 재검증', async () => {
  await goStep('3자 대조');
  await expect(step('3자 대조')).toHaveClass(/step--current/);
  await btn('3자 대조').click();
  await expect(card('통과')).toContainText('4');
  await expect(card('자동화 대상')).toContainText('4');
  await expect(card('확인 대상')).toContainText('3');
  await expect(card('에러')).toContainText('1');
  await expect(step('3자 대조')).toContainText('진행중');

  await btn('자동화 시작').click();
  const dialog = page.locator('.q-dialog--modal');
  await expect(dialog).toContainText('대상 4건');
  await expect(dialog).toContainText('통과 예상');
  await expect(dialog).toContainText('미통과 예상');
  await dialog.getByRole('button', { name: '확인 · 실행' }).click();

  await expect(page.getByText('자동화 결과 · 자동 재검증')).toBeVisible();
  await expect(card('통과')).toContainText('7');
  await expect(card('자동화 대상')).toContainText('0');
  const failRow = page.locator('tr', { hasText: '햇살12호' }).filter({ hasText: '미통과' });
  await expect(failRow).toContainText('부족');
});

test('④ 확인 대상: 상세 · 보류(사유 필수) · 해제 · 에러 케이스', async () => {
  await goStep('확인 대상');
  await expect(page.locator('.q-table tbody tr')).toHaveCount(4);

  await page.locator('.q-table tbody tr', { hasText: '햇살12호' }).click();
  const detail = page.locator('.q-dialog--modal');
  await expect(detail).toContainText('실패 원인');
  await expect(detail).toContainText('근거 데이터');
  await expect(detail).toContainText('재검증 이력');
  await expect(detail).not.toContainText('@');

  await detail.getByRole('button', { name: '보류' }).click();
  const prompt = page.locator('.q-dialog--modal').last();
  await expect(prompt.getByRole('button', { name: '보류' })).toBeDisabled(); // 사유 없으면 불가
  await prompt.locator('textarea').fill('E2E 보류 사유');
  await prompt.getByRole('button', { name: '보류' }).click();
  await expect(detail.getByText('보류 이력')).toBeVisible();
  await page.keyboard.press('Escape');

  await page.getByRole('button', { name: /보류 1/ }).click();
  await expect(page.locator('.q-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.q-table tbody tr')).toContainText('E2E 보류 사유');
  await page.locator('.q-table tbody tr').getByRole('button').last().click(); // 보류 해제
  await expect(page.getByRole('button', { name: /보류 0/ })).toBeVisible();

  await page.getByRole('button', { name: /확인 대상/ }).first().click();
  await page.locator('.q-table tbody tr', { hasText: '산마루9호' }).getByRole('button').nth(1).click(); // 에러 케이스
  const ec = page.locator('.q-dialog--modal');
  await ec.getByRole('button', { name: '추가' }).click();
  await expect(page.locator('.q-notification', { hasText: 'ERR-' })).toBeVisible();

  // 필터: 유형 태그
  await page.getByLabel('유형 태그').click();
  await page.getByRole('option', { name: '이중계상 의심' }).click();
  await expect(page.locator('.q-table tbody tr')).toHaveCount(1);
});

test('⑤ 리포트 → 최종 확정 경고 → 확정 후 잠금', async () => {
  await goStep('리포트 · 확정');
  await expect(page.locator('.report')).toContainText('발전매출 정산 종합 리포트');
  await expect(page.locator('.report')).toContainText('요약');
  await expect(page.locator('.report')).toContainText('되돌림');
  await expect(page.locator('.report')).toContainText('에러 케이스');
  await expect(page.locator('.report')).not.toContainText('@');

  await btn('최종 확정').click();
  const warn = page.locator('.q-dialog--modal', { hasText: '확정 경고' });
  await expect(warn).toContainText('미해결');
  await warn.getByRole('button', { name: '경고 확인 후 확정' }).click();

  await expect(page.locator('.app-header')).toContainText('확정됨');
  await expect(page.locator('.app-header')).not.toContainText('@');
  for (const t of ['데이터 불러오기', '예외 관리', '3자 대조', '확인 대상', '리포트 · 확정']) {
    await expect(step(t)).toContainText('완료');
  }
  await goStep('3자 대조');
  await expect(btn('3자 대조')).toBeDisabled();
  await goStep('예외 관리');
  await expect(page.getByRole('button', { name: '예외 등록' })).toBeDisabled();
});

test('콘솔 에러 없음', async () => {
  expect(consoleErrors).toEqual([]);
});
