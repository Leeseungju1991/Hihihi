import type { RouteRecordRaw } from 'vue-router';

// 회사 앱의 routes 에 이 배열을 그대로 추가하면 된다 (prefix 는 필요 시 변경).
export const settlementRoutes: RouteRecordRaw[] = [
  {
    path: '/settlement',
    component: () => import('../layouts/SettlementLayout.vue'),
    children: [
      { path: '', redirect: { name: 'settlement-load' } },
      { path: 'load', name: 'settlement-load', component: () => import('../pages/LoadPage.vue'), meta: { title: '① 데이터 불러오기' } },
      { path: 'exceptions', name: 'settlement-exceptions', component: () => import('../pages/ExceptionsPage.vue'), meta: { title: '② 예외 관리' } },
      { path: 'reconcile', name: 'settlement-reconcile', component: () => import('../pages/ReconcilePage.vue'), meta: { title: '③ 3자 대조' } },
      { path: 'review', name: 'settlement-review', component: () => import('../pages/ReviewPage.vue'), meta: { title: '④ 확인 대상' } },
      { path: 'report', name: 'settlement-report', component: () => import('../pages/ReportPage.vue'), meta: { title: '⑤ 리포트' } },
    ],
  },
];

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/settlement' },
  ...settlementRoutes,
  { path: '/:catchAll(.*)*', redirect: '/settlement' },
];

export default routes;
