<template>
  <q-page padding class="print-page">
    <div class="row items-center q-mb-md q-gutter-sm no-print">
      <div class="text-h6 col">⑤ 리포트</div>
      <q-btn-toggle
        v-model="kind"
        unelevated
        toggle-color="primary"
        :options="[
          { label: '정산월 종합', value: 'monthly' },
          { label: '미결 건 즉시', value: 'unresolved' },
        ]"
        @update:model-value="load"
      />
      <q-btn :color="$q.dark.isActive ? 'grey-2' : 'dark'" :text-color="$q.dark.isActive ? 'dark' : 'white'" unelevated no-caps icon="picture_as_pdf" label="PDF 저장" :disable="!rep" @click="print" />
    </div>

    <div v-if="error" class="text-muted q-pa-lg text-center">{{ error }}</div>
    <div v-else-if="!rep" class="flex flex-center q-pa-xl"><q-spinner size="lg" /></div>

    <article v-else class="report" style="max-width: 1000px">
      <header class="q-mb-md">
        <div class="text-h5 text-weight-bold">
          발전매출 정산 {{ rep.kind === 'monthly' ? '종합' : '미결' }} 리포트 · {{ rep.month }}
        </div>
        <div class="text-caption text-muted">
          대조 {{ rep.generated_from_run }} · {{ dateTime(rep.run_at) }} · 출력 {{ dateTime(new Date().toISOString()) }}
        </div>
      </header>

      <q-banner dense class="callout q-mb-md">
        <template #avatar>
          <q-badge :color="rep.summary_source === 'LLM' ? 'purple' : 'grey-7'">{{ rep.summary_source === 'LLM' ? 'LLM 요약' : '요약' }}</q-badge>
        </template>
        {{ rep.summary }}
      </q-banner>

      <section>
        <h3>개요</h3>
        <q-markup-table flat bordered dense>
          <tbody>
            <tr>
              <th class="text-left">로드 건수</th>
              <td>분개(412) {{ rep.load_counts.journal }}건 · 송장 {{ rep.load_counts.invoice }}건 · 세금계산서 {{ rep.load_counts.tax_invoice }}건</td>
            </tr>
            <tr>
              <th class="text-left">분류별 건수</th>
              <td>
                <span v-for="(v, k) in rep.category_counts" :key="k" class="q-mr-md">{{ store.categoryLabel(k) }} {{ v }}</span>
              </td>
            </tr>
            <tr>
              <th class="text-left">적용 예외</th>
              <td>{{ rep.applied_exception_ids.join(', ') || '없음' }}</td>
            </tr>
            <tr>
              <th class="text-left">추정 보정</th>
              <td>{{ rep.estimated_count }}건 <span class="text-caption text-muted">(인근 발전소 기반, 실측 아님)</span></td>
            </tr>
            <tr>
              <th class="text-left">승인</th>
              <td>
                <template v-if="rep.approval">
                  {{ who(rep.approval.actor) }} · {{ dateTime(rep.approval.at) }}
                  <span v-if="rep.approval.open_holds.length" class="text-negative"> · 보류 {{ rep.approval.open_holds.length }}건 포함 확정</span>
                </template>
                <span v-else class="text-muted">미확정</span>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </section>

      <section v-if="rep.holds.length">
        <h3>보류 건 <q-badge color="negative">{{ rep.holds.length }}</q-badge></h3>
        <q-markup-table flat bordered dense>
          <thead><tr><th class="text-left">발전소</th><th class="text-left">사유</th><th class="text-left">처리자</th><th class="text-left">일시</th></tr></thead>
          <tbody>
            <tr v-for="h in rep.holds" :key="h.plant_id">
              <td>{{ h.plant_id }}</td><td>{{ h.reason }}</td><td>{{ who(h.actor) }}</td><td>{{ dateTime(h.at) }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </section>

      <section>
        <h3>자동화 전·후</h3>
        <div v-if="!rep.automation.length" class="text-muted">자동화 없음</div>
        <q-markup-table v-else flat bordered dense>
          <thead>
            <tr>
              <th class="text-left">발전소</th><th class="text-left">내용</th><th class="text-left">구분</th>
              <th class="text-right">보정 전</th><th class="text-right">보정 후</th><th class="text-left">공식 · 근거</th><th class="text-left">적용</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(a, i) in rep.automation" :key="i" :class="{ 'text-subtle': a.reverted }">
              <td>{{ a.plant_id }}</td>
              <td>{{ KIND_LABEL[a.kind] }}<div class="text-caption">{{ a.partner_id }}</div></td>
              <td>
                <q-badge :color="a.basis === 'ESTIMATED' ? 'orange' : 'teal'">{{ a.basis_label }}</q-badge>
                <q-badge v-if="a.reverted" color="grey-6" class="q-ml-xs">되돌림</q-badge>
              </td>
              <td class="num">{{ kwh(a.kwh_before) }}</td>
              <td class="num">{{ kwh(a.kwh_after) }}</td>
              <td class="text-caption" style="white-space: normal">{{ a.formula }}</td>
              <td class="text-caption">{{ who(a.applied_by) }}<br />{{ dateTime(a.applied_at) }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </section>

      <section>
        <h3>재검증 결과</h3>
        <div v-if="!rep.rechecks.length" class="text-muted">재검증 없음</div>
        <q-markup-table v-else flat bordered dense>
          <thead><tr><th class="text-left">발전소</th><th class="text-right">횟수</th><th class="text-left">최종</th><th class="text-left">실패 원인 · 추천 조치</th></tr></thead>
          <tbody>
            <tr v-for="r in rep.rechecks" :key="r.plant_id">
              <td>{{ r.plant_id }}</td>
              <td class="num">{{ r.attempts }}</td>
              <td><q-badge :color="r.passed ? 'positive' : 'warning'">{{ r.passed ? '통과' : '미통과' }}</q-badge></td>
              <td style="white-space: normal">
                <template v-if="!r.passed">
                  {{ r.last_cause }}<div class="text-caption">→ {{ r.last_action }}</div>
                  <div class="text-caption text-muted">근거: {{ r.evidence.map((e) => `${e.label} ${e.value}`).join(' · ') }}</div>
                </template>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </section>

      <section>
        <h3>미해결 · 확인 대상</h3>
        <div v-if="!rep.items.length" class="text-muted">없음</div>
        <q-markup-table v-else flat bordered dense>
          <thead>
            <tr><th class="text-left">발전소</th><th class="text-left">분류</th><th class="text-right">분개</th><th class="text-right">송장</th><th class="text-right">세금계산서</th><th class="text-left">문제</th></tr>
          </thead>
          <tbody>
            <tr v-for="it in rep.items" :key="it.plant_id">
              <td>{{ it.plant_name }}<div class="text-caption">{{ it.plant_id }}</div></td>
              <td>{{ store.categoryLabel(it.category) }}</td>
              <td class="num">{{ won(it.journal_amount) }}</td>
              <td class="num">{{ kwh(it.invoice_kwh) }}</td>
              <td class="num">{{ won(it.tax_amount) }}</td>
              <td style="white-space: normal">{{ it.tags.join(', ') }}<div class="text-caption">{{ it.summary }}</div></td>
            </tr>
          </tbody>
        </q-markup-table>
      </section>

      <section v-if="rep.error_cases.length">
        <h3>에러 케이스</h3>
        <q-markup-table flat bordered dense>
          <thead><tr><th class="text-left">번호</th><th class="text-left">발생일</th><th class="text-left">발전소</th><th class="text-left">증상</th></tr></thead>
          <tbody>
            <tr v-for="c in rep.error_cases" :key="c.case_no">
              <td>{{ c.case_no }}</td><td>{{ c.occurred_on }}</td><td>{{ c.plant_id }}</td><td>{{ c.symptom }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </section>
    </article>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api, ApiError } from '../api/client';
import type { Report } from '../api/types';
import { useSettlementStore } from '../stores/settlement';
import { useQuasar } from 'quasar';
import { dateTime, KIND_LABEL, kwh, who, won } from '../utils/format';

const $q = useQuasar();
const store = useSettlementStore();
const kind = ref<'monthly' | 'unresolved'>('monthly');
const rep = ref<Report | null>(null);
const error = ref('');

async function load() {
  rep.value = null;
  error.value = '';
  try {
    rep.value = await api.report(store.month, kind.value);
  } catch (e) {
    error.value = e instanceof ApiError && e.status === 404 ? '③ 3자 대조를 먼저 실행하세요.' : (e as Error).message;
  }
}
onMounted(load);

// 브라우저 인쇄 → "PDF로 저장". 서버 PDF 가 필요하면 같은 Report JSON 으로 렌더링하면 된다.
function print() {
  window.print();
}
</script>

<style scoped>
.report {
  counter-reset: sec;
}
.report h3::before {
  counter-increment: sec;
  content: counter(sec) '. ';
}
.report h3 {
  font-size: 1.05rem;
  font-weight: 700;
  margin: 1.5rem 0 0.5rem;
  line-height: 1.4;
}
.report section {
  break-inside: avoid-page;
}
</style>
