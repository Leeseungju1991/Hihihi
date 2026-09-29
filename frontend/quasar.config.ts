// 회사 Quasar 프로젝트에 합칠 때는 이 파일 대신 src/ 아래 pages·components·api·stores 만 옮기고
// routes 에 settlementRoutes 를 추가한다 (INTEGRATION.md §4).
import { defineConfig } from '#q-app/wrappers';

export default defineConfig(() => ({
  boot: [],
  css: ['app.css'],
  extras: ['material-icons'],
  build: {
    target: { browser: ['es2022', 'firefox115', 'chrome115', 'safari14'], node: 'node20' },
    typescript: { strict: true, vueShim: true },
    vueRouterMode: 'history',
  },
  devServer: {
    open: false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  framework: {
    lang: 'ko-KR',
    config: {},
    plugins: ['Dialog', 'Notify', 'Loading'],
  },
}));
