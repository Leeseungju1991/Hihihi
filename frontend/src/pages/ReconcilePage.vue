<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h6 col">③ 3자 대조</div>
      <div v-if="store.run" class="text-caption text-muted">
        최근 대조 {{ dateTime(store.run.created_at) }}
      </div>
      <q-btn color="primary" unelevated icon="compare_arrows" label="3자 대조" :loading="running" :disable="store.locked" @click="reconcile" />
      <q-btn
        color="primary"
        outline
        icon="auto_fix_high"
        label="자동화 시작"
        :disable="!store.run || !counts.AUTOMATABLE || store.locked"
        :loading="automating"
        @click="startAutomation"
      />
    </div>

    <div v-if="!store.run" class="text-muted q-pa-lg text-center">
      [3자 대조]를 눌러 분개 · 송장 · 세금계산서를 발전소 단위로 대조합니다.
    </div>

    <template v-else>
      <!-- 5개 구분 -->
      <div class="row q-col-gutter-sm q-mb-md">
        <div v-for="c in CATEGORIES" :key="c" class="col">
          <q-card
            flat
            bordered
            class="cursor-pointer hover-lift"
            :class="selected === c ? `bg-${CATEGORY_COLOR[c]} text-white` : ''"
            role="button"
            :aria-pressed="selected === c"
            @click="selected = c"
          >
            <q-card-section class="q-py-sm">
              <div class="text-caption">{{ store.categoryLabel(c) }}</div>
              <div class="text-h5 text-weight-bold">{{ counts[c] }}</div>
              <div class="text-caption" :class="selected === c ? 'text-white' : 'text-muted'" :style="selected === c ? 'opacity: .85' : ''">{{ HINT[c] }}</div>
            </q-card-section>
          </q-card>
        </div>
      </div>

      <!-- 자동화 결과 -->
      <transition name="fade-up" appear>
      <q-card v-if="executed.length" flat bordered class="q-mb-md">
        <q-card-section class="text-subtitle1">자동화 결과 · 자동 재검증</q-card-section>
        <q-markup-table flat dense separator="horizontal">
          <thead>
            <tr>
              <th class="text-left">발전소</th>
              <th class="text-left">자동화 내용</th>
              <th class="text-left">재검증 결과</th>
              <th class="text-left">실패 원인 (LLM)</th>
              <th class="text-left">동작</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="x in executed" :key="x.rc.plant_id">
              <td class="text-no-wrap">{{ nameOf(x.rc.plant_id) }}</td>
              <td>{{ x.kinds.map((k) => KIND_LABEL[k]).join(', ') }}</td>
              <td>
                <q-badge :color="x.rc.passed ? 'positive' : 'warning'">{{ x.rc.passed ? '통과' : '미통과' }}</q-badge>
              </td>
              <td style="white-space: normal; max-width: 420px">{{ x.rc.cause || '-' }}</td>
              <td class="text-no-wrap">
                <template v-if="!x.rc.passed && !store.locked && resultOf(x.rc.plant_id)">
                  <q-btn dense flat size="sm" label="예외 등록" @click="act.registerException(resultOf(x.rc.plant_id)!)" />
                  <q-btn dense flat size="sm" color="primary" label="재검증" @click="recheckRow(x.rc.plant_id)" />
                  <q-btn dense flat size="sm" label="보류" @click="act.hold(resultOf(x.rc.plant_id)!)" />
                </template>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card>
      </transition>

      <!-- 목록 -->
      <ResultTable :rows="store.byCategory(selected)" @open="act.openDetail" />
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useQuasar } from 'quasar';
import { api } from '../api/client';
import type { AdjustmentKind, Category, RecheckRecord } from '../api/types';
import AutomationDialog from '../components/AutomationDialog.vue';
import ResultTable from '../components/ResultTable.vue';
import { useResultActions } from '../components/useResultActions';
import { useSettlementStore } from '../stores/settlement';
import { CATEGORY_COLOR, dateTime, KIND_LABEL } from '../utils/format';

const CATEGORIES: Category[] = ['PASS', 'AUTOMATABLE', 'REVIEW', 'HOLD', 'ERROR'];
const HINT: Record<Category, string> = {
  PASS: '사용자 동작 없음',
  AUTOMATABLE: '자동화 시작',
  REVIEW: '검토 후 예외 등록',
  HOLD: '추후 재검증',
  ERROR: '재수집 · 에러 케이스',
};

const $q = useQuasar();
const store = useSettlementStore();
const act = useResultActions();
const running = ref(false);
const automating = ref(false);
const selected = ref<Category>('AUTOMATABLE');
const executed = ref<{ rc: RecheckRecord; kinds: AdjustmentKind[] }[]>([]);

const counts = computed(
  () => store.run?.category_counts ?? { PASS: 0, AUTOMATABLE: 0, REVIEW: 0, HOLD: 0, ERROR: 0 },
);
const resultOf = (pid: string) => store.run?.results.find((r) => r.plant_id === pid);
const nameOf = (pid: string) => resultOf(pid)?.plant_name ?? pid;

async function reconcile() {
  running.value = true;
  try {
    await store.reconcile();
    executed.value = [];
    selected.value = counts.value.AUTOMATABLE ? 'AUTOMATABLE' : counts.value.REVIEW ? 'REVIEW' : 'PASS';
  } catch (e) {
    $q.notify({ type: 'negative', message: (e as Error).message });
  } finally {
    running.value = false;
  }
}

async function startAutomation() {
  if (!store.run) return;
  const runId = store.run.run_id;
  automating.value = true;
  try {
    const preview = await api.previewAutomation(runId);
    automating.value = false;
    $q.dialog({ component: AutomationDialog, componentProps: { preview } }).onOk(async () => {
      automating.value = true;
      try {
        const kinds = new Map(preview.items.map((i) => [i.plant_id, [...new Set(i.adjustments.map((a) => a.kind))]]));
        const res = await api.executeAutomation(runId);
        store.run = res.run;
        executed.value = res.rechecks.map((rc) => ({ rc, kinds: kinds.get(rc.plant_id) ?? [] }));
        const passed = res.rechecks.filter((r) => r.passed).length;
        $q.notify({
          type: passed === res.rechecks.length ? 'positive' : 'warning',
          message: `자동화 ${res.rechecks.length}건 실행 · 재검증 통과 ${passed}건 · 미통과 ${res.rechecks.length - passed}건`,
        });
      } catch (e) {
        $q.notify({ type: 'negative', message: (e as Error).message });
      } finally {
        automating.value = false;
      }
    });
  } catch (e) {
    automating.value = false;
    $q.notify({ type: 'negative', message: (e as Error).message });
  }
}

async function recheckRow(pid: string) {
  const r = resultOf(pid);
  if (!r) return;
  const rc = await act.recheck(r);
  if (rc) executed.value = executed.value.map((x) => (x.rc.plant_id === pid ? { ...x, rc } : x));
}
</script>
