<template>
  <q-dialog ref="dialogRef" position="right" full-height @hide="onDialogHide">
    <q-card style="width: 640px; max-width: 100vw" class="column no-wrap">
      <q-card-section class="row items-center">
        <div class="col">
          <div class="text-h6">{{ d?.result.plant_name ?? plantId }}</div>
          <div class="text-caption text-grey-7">{{ plantId }} · {{ month }}</div>
        </div>
        <CategoryBadge v-if="d" :category="d.result.category" />
        <q-btn flat round icon="close" class="q-ml-sm" @click="onDialogCancel" />
      </q-card-section>
      <q-separator />

      <q-card-section v-if="!d" class="flex flex-center col"><q-spinner size="lg" /></q-card-section>

      <q-card-section v-else class="col scroll q-gutter-y-md">
        <!-- 원천값 -->
        <div>
          <div class="text-subtitle2 q-mb-xs">원천값</div>
          <q-markup-table flat bordered dense>
            <tbody>
              <tr><td>분개(412)</td><td class="num">{{ won(r.journal_amount) }}</td></tr>
              <tr><td>송장 검침량 × 확정 단가</td><td class="num">{{ kwh(r.invoice_kwh) }} × {{ price(r.unit_price) }} = {{ won(r.invoice_amount) }}</td></tr>
              <tr>
                <td>세금계산서(유효)</td>
                <td class="num" :class="{ mismatch: mismatch(r.tax_amount, r.journal_amount) }">
                  {{ won(r.tax_amount) }}
                  <span v-if="mismatch(r.tax_amount, r.journal_amount)"> ({{ signed(won(r.amount_diff), r.amount_diff) }})</span>
                </td>
              </tr>
              <tr>
                <td>역산 단가 (분개 ÷ 검침량)</td>
                <td class="num" :class="{ mismatch: priceOff }">{{ price(r.implied_price) }}</td>
              </tr>
              <tr>
                <td>역산 검침량 (분개 ÷ 단가)</td>
                <td class="num">
                  {{ kwh(r.implied_kwh) }}
                  <span v-if="r.kwh_diff && priceOff" class="mismatch"> (송장 {{ signed(kwh(r.kwh_diff), r.kwh_diff) }})</span>
                </td>
              </tr>
              <tr><td>일 평균 발전시간</td><td class="num">{{ r.daily_hours ?? '-' }}h</td></tr>
            </tbody>
          </q-markup-table>
        </div>

        <!-- 실패 원인 -->
        <div v-if="d.explanation">
          <div class="text-subtitle2 q-mb-xs">
            실패 원인
            <q-badge :color="d.explanation.source === 'LLM' ? 'purple' : 'grey-7'" class="q-ml-xs">
              {{ d.explanation.source === 'LLM' ? 'LLM 분석' : '규칙 기반' }}
            </q-badge>
          </div>
          <q-banner dense class="bg-orange-1 rounded-borders">
            {{ d.explanation.cause }}
            <div class="q-mt-xs text-weight-medium">추천 조치: {{ d.explanation.recommended_action }}</div>
            <div v-if="d.explanation.rejected_reason" class="text-caption text-grey-7 q-mt-xs">
              (LLM 응답이 근거 검증을 통과하지 못해 규칙 기반 설명으로 대체: {{ d.explanation.rejected_reason }})
            </div>
          </q-banner>
          <div class="text-caption text-grey-7 q-mt-sm">근거 데이터</div>
          <q-markup-table flat dense>
            <tbody>
              <tr v-for="e in d.explanation.evidence" :key="e.key">
                <td class="text-grey-8">{{ e.label }}</td>
                <td class="num">{{ e.value }}</td>
              </tr>
            </tbody>
          </q-markup-table>
        </div>

        <!-- 자동화 후보 / 적용된 보정 -->
        <div v-if="r.candidate_adjustments.length">
          <div class="text-subtitle2 q-mb-xs">
            {{ r.category === 'AUTOMATABLE' ? '자동화 가능 보정' : '보정 제안 (이미 자동화했으나 재검증 미통과 — 되돌림)' }}
          </div>
          <AdjustmentList :items="r.candidate_adjustments" />
        </div>
        <div v-if="d.adjustments.length">
          <div class="text-subtitle2 q-mb-xs">적용된 보정</div>
          <AdjustmentList :items="d.adjustments" show-applied />
        </div>

        <!-- 재검증 이력 -->
        <div>
          <div class="text-subtitle2 q-mb-xs">재검증 이력</div>
          <div v-if="!d.rechecks.length" class="text-caption text-grey-7">없음</div>
          <q-timeline v-else dense color="grey-6">
            <q-timeline-entry
              v-for="rc in [...d.rechecks].reverse()"
              :key="rc.attempt"
              :color="rc.passed ? 'positive' : 'warning'"
              :title="`${rc.attempt}회차 · ${rc.passed ? '통과' : '미통과'} · ${rc.trigger === 'AUTOMATION' ? '자동화' : '수동'}`"
              :subtitle="`${dateTime(rc.at)} · ${rc.actor}`"
            >
              <div v-if="rc.cause" class="text-body2">{{ rc.cause }}</div>
            </q-timeline-entry>
          </q-timeline>
        </div>

        <!-- 보류·예외 -->
        <div v-if="d.holds.length">
          <div class="text-subtitle2 q-mb-xs">보류 이력</div>
          <div v-for="(h, i) in d.holds" :key="i" class="text-body2">
            {{ h.released ? `해제 · ${h.released_by} · ${dateTime(h.released_at)}` : `보류 · ${h.actor} · ${dateTime(h.at)}` }}
            — {{ h.reason }}
          </div>
        </div>
        <div v-if="d.exceptions.length">
          <div class="text-subtitle2 q-mb-xs">등록된 예외</div>
          <div v-for="e in d.exceptions" :key="e.exception_id" class="text-body2">
            {{ e.exception_id }} · {{ typeLabel(e.type) }} · {{ store.meta?.exception_statuses[e.status] }} (v{{ e.version }})
          </div>
        </div>
      </q-card-section>

      <q-separator />
      <q-card-actions v-if="d && !store.locked" align="right">
        <q-btn flat icon="add_circle" label="예외 등록" @click="act.registerException(r)" />
        <q-btn flat color="negative" icon="report" label="에러 케이스" @click="act.addErrorCase(r)" />
        <q-btn flat color="primary" icon="refresh" label="재검증" @click="recheck" />
        <q-btn v-if="r.category === 'HOLD'" flat icon="undo" label="보류 해제" @click="release" />
        <q-btn v-else-if="r.category !== 'PASS'" flat icon="pause_circle" label="보류" @click="hold" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useDialogPluginComponent } from 'quasar';
import { api } from '../api/client';
import type { ExceptionType, PlantDetail } from '../api/types';
import { useSettlementStore } from '../stores/settlement';
import { dateTime, kwh, mismatch, price, signed, won } from '../utils/format';
import AdjustmentList from './AdjustmentList.vue';
import CategoryBadge from './CategoryBadge.vue';
import { useResultActions } from './useResultActions';

const props = defineProps<{ month: string; plantId: string }>();
defineEmits([...useDialogPluginComponent.emits]);
const { dialogRef, onDialogHide, onDialogCancel } = useDialogPluginComponent();
const store = useSettlementStore();
const act = useResultActions();
const d = ref<PlantDetail | null>(null);

const r = computed(() => d.value!.result);
const priceOff = computed(() => {
  const res = d.value?.result;
  if (!res?.implied_price || !res.unit_price) return false;
  return Math.abs(Number(res.implied_price) - Number(res.unit_price)) > Number(store.meta?.rules.smp_tolerance ?? 0.5);
});
const typeLabel = (t: ExceptionType) => store.meta?.exception_types.find((x) => x.value === t)?.label ?? t;

async function reload() {
  d.value = await api.detail(props.month, props.plantId);
}
onMounted(reload);
// 다른 곳(보류 다이얼로그 등)에서 run 이 갱신되면 상세도 갱신
watch(() => store.run, () => void reload());

async function recheck() {
  await act.recheck(r.value);
}
function hold() {
  act.hold(r.value);
}
async function release() {
  await act.release(r.value);
}
</script>
