<template>
  <q-table
    flat
    bordered
    dense
    row-key="plant_id"
    :rows="rows"
    :columns="columns"
    :pagination="{ rowsPerPage: 50, sortBy: 'priority' }"
    no-data-label="해당 건 없음"
    @row-click="(_evt: Event, row: PlantResult) => emit('open', row)"
  >
    <template #body-cell-plant="p">
      <q-td :props="p">
        <div class="text-weight-medium">{{ p.row.plant_name }}</div>
        <div class="text-caption text-muted">{{ p.row.plant_id }}</div>
      </q-td>
    </template>
    <template #body-cell-journal="p">
      <q-td :props="p" class="num">{{ won(p.row.journal_amount) }}</q-td>
    </template>
    <template #body-cell-invoice="p">
      <q-td :props="p" class="num" :class="{ mismatch: invoiceOff(p.row) }">
        {{ kwh(p.row.invoice_kwh) }}
        <div class="text-caption">{{ won(p.row.invoice_amount) }}</div>
      </q-td>
    </template>
    <template #body-cell-tax="p">
      <q-td :props="p" class="num" :class="{ mismatch: mismatch(p.row.tax_amount, p.row.journal_amount) }">
        {{ won(p.row.tax_amount) }}
      </q-td>
    </template>
    <template #body-cell-diff="p">
      <q-td :props="p" class="num">
        <div v-if="mismatch(p.row.tax_amount, p.row.journal_amount)" class="mismatch">
          {{ signed(won(p.row.amount_diff), p.row.amount_diff) }}
        </div>
        <div v-if="invoiceOff(p.row) && p.row.kwh_diff" class="mismatch">{{ signed(kwh(p.row.kwh_diff), p.row.kwh_diff) }}</div>
      </q-td>
    </template>
    <template #body-cell-summary="p">
      <q-td :props="p" style="white-space: normal; min-width: 240px">
        <TagChips :tags="p.row.tags" />
        <div>{{ p.row.summary }}</div>
      </q-td>
    </template>
    <template #body-cell-priority="p">
      <q-td :props="p">
        <q-badge :color="p.row.priority === 'HIGH' ? 'negative' : p.row.priority === 'MEDIUM' ? 'warning' : 'grey-5'">
          {{ PRIORITY_LABEL[p.row.priority as Priority] }}
        </q-badge>
      </q-td>
    </template>
    <template v-if="$slots.actions" #body-cell-actions="p">
      <q-td :props="p" @click.stop>
        <slot name="actions" :row="p.row" />
      </q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import { computed, useSlots } from 'vue';
import type { QTableColumn } from 'quasar';
import type { PlantResult, Priority } from '../api/types';
import { useSettlementStore } from '../stores/settlement';
import { kwh, mismatch, PRIORITY_LABEL, signed, won } from '../utils/format';
import TagChips from './TagChips.vue';

defineProps<{ rows: PlantResult[] }>();
const emit = defineEmits<{ open: [row: PlantResult] }>();
const slots = useSlots();
const store = useSettlementStore();

const PRIORITY_ORDER: Record<Priority, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

function invoiceOff(r: PlantResult): boolean {
  if (!r.implied_price || !r.unit_price) return Number(r.invoice_kwh) === 0 && Number(r.journal_amount) !== 0;
  return Math.abs(Number(r.implied_price) - Number(r.unit_price)) > Number(store.meta?.rules.smp_tolerance ?? 0.5);
}

const columns = computed<QTableColumn<PlantResult>[]>(() => [
  { name: 'plant', label: '발전소', field: 'plant_name', align: 'left', sortable: true },
  { name: 'month', label: '정산월', field: 'month', align: 'left' },
  { name: 'journal', label: '분개', field: 'journal_amount', align: 'right' },
  { name: 'invoice', label: '송장', field: 'invoice_kwh', align: 'right' },
  { name: 'tax', label: '세금계산서', field: 'tax_amount', align: 'right' },
  { name: 'diff', label: '차이', field: 'amount_diff', align: 'right' },
  { name: 'summary', label: '문제', field: 'summary', align: 'left' },
  {
    name: 'priority',
    label: '우선순위',
    field: 'priority',
    align: 'left',
    sortable: true,
    sort: (a: Priority, b: Priority) => PRIORITY_ORDER[a] - PRIORITY_ORDER[b],
  },
  ...(slots.actions ? [{ name: 'actions', label: '', field: 'plant_id' as const, align: 'right' as const }] : []),
]);
</script>
