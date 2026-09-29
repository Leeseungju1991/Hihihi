// 페이지 기능 E2E — 가상 데이터(메모리 백엔드)로 ①~⑤ 전 흐름을 라이트·다크 두 테마에서 점검
// 실행: npm run e2e   (백엔드 venv 필요: cd ../backend && uv venv && uv pip install -e ".[dev]")
import { defineConfig } from '@playwright/test';

const API_PORT = 8765;
const WEB_PORT = 9765;

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    viewport: { width: 1440, height: 900 },
    locale: 'ko-KR',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  projects: [
    { name: 'light', use: { colorScheme: 'light' } },
    { name: 'dark', use: { colorScheme: 'dark' } },
  ],
  webServer: [
    {
      // 메모리 백엔드 1회 기동. 테마별로 다른 정산월(2026-08 / 2026-07)을 써서 확정 잠금이 섞이지 않게 한다
      command: `cd ../backend && ${process.env.AX_PYTHON ?? '.venv/bin/python'} -m uvicorn settlement.api.app:app --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/healthz`,
      env: { AX_DEV_USER: 'fin@corp.example', AX_APPROVERS: 'fin@corp.example', AX_DEMO_MONTHS: '2026-08,2026-07' },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx quasar dev --port ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { AX_API_PROXY: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
