<template>
  <q-page padding>
    <div class="row items-center q-mb-sm">
      <div class="text-h6 col">② 예외 관리</div>
      <q-badge v-if="store.locked" color="grey-8" class="q-pa-sm q-mr-sm"><q-icon name="lock" class="q-mr-xs" />확정월 — 수정 잠금</q-badge>
    </div>

    <q-tabs v-model="tab" dense align="left" class="text-grey-8 q-mb-md" active-color="primary" indicator-color="primary">
      <q-tab name="exceptions" label="예외" />
      <q-tab name="errors" label="에러 케이스" />
    </q-tabs>

    <q-tab-panels v-model="tab" animated>
      <!-- 예외 -->
      <q-tab-panel name="exceptions" class="q-pa-none">
        <div class="row q-gutter-sm q-mb-sm items-center">
          <q-btn color="primary" unelevated icon="add" label="예외 등록" :disable="store.locked" @click="create" />
          <q-toggle v-model="showClosed" label="종료 포함" />
          <q-space />
          <q-input v-model="search" dense outlined clearable placeholder="발전소·번호 검색" style="width: 220px" />
        </div>
        <q-table
          flat
          bordered
          dense
          row-key="exception_id"
          :rows="filtered"
          :columns="columns"
          :loading="loading"
          :pagination="{ rowsPerPage: 50 }"
          no-data-label="등록된 예외 없음"
        >
          <template #body-cell-type="p">
            <q-td :props="p">{{ typeLabel(p.row.type) }}</q-td>
          </template>
          <template #body-cell-change="p">
            <q-td :props="p">
              <span v-if="p.row.partner_before">{{ p.row.partner_before }} → </span>{{ p.row.partner_after || '-' }}
            </q-td>
          </template>
          <template #body-cell-status="p">
            <q-td :props="p">
              <q-badge :color="STATUS_COLOR[(p.row as SettlementException).status]">{{ store.meta?.exception_statuses[(p.row as SettlementException).status] }}</q-badge>
            </q-td>
          </template>
          <template #body-cell-audit="p">
            <q-td :props="p" class="text-caption">v{{ p.row.version }} · {{ p.row.updated_by }}<br />{{ dateTime(p.row.updated_at) }}</q-td>
          </template>
          <template #body-cell-actions="p">
            <q-td :props="p" class="text-no-wrap">
              <q-btn dense flat size="sm" icon="history" @click="showHistory(p.row)"><q-tooltip>이력</q-tooltip></q-btn>
              <template v-if="!store.locked && p.row.status !== 'CLOSED'">
                <q-btn dense flat size="sm" icon="edit" @click="edit(p.row)"><q-tooltip>수정</q-tooltip></q-btn>
                <q-btn dense flat size="sm" icon="block" color="negative" @click="close(p.row)"><q-tooltip>종료</q-tooltip></q-btn>
              </template>
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <!-- 에러 케이스 -->
      <q-tab-panel name="errors" class="q-pa-none">
        <div class="q-mb-sm">
          <q-btn color="negative" unelevated icon="add" label="에러 케이스 추가" @click="addError" />
        </div>
        <q-table
          flat
          bordered
          dense
          row-key="case_no"
          :rows="errorCases"
          :columns="errorColumns"
          :pagination="{ rowsPerPage: 50 }"
          no-data-label="에러 케이스 없음"
        />
      </q-tab-panel>
    </q-tab-panels>

    <q-dialog v-model="historyOpen">
      <q-card style="width: 720px; max-width: 96vw">
        <q-card-section class="text-h6">변경 이력 · {{ historyRows[0]?.exception_id }}</q-card-section>
        <q-markup-table flat dense>
          <thead>
            <tr><th>버전</th><th>상태</th><th>유형</th><th>기준일</th><th>조합</th><th>수기 kWh</th><th>비고</th><th>작성자</th><th>일시</th></tr>
          </thead>
          <tbody>
            <tr v-for="h in historyRows" :key="h.version">
              <td>v{{ h.version }}</td>
              <td>{{ store.meta?.exception_statuses[h.status] }}</td>
              <td>{{ typeLabel(h.type) }}</td>
              <td>{{ h.base_date ?? '-' }}</td>
              <td>{{ h.partner_before }}{{ h.partner_before ? ' → ' : '' }}{{ h.partner_after }}</td>
              <td class="num">{{ h.manual_kwh ?? '-' }}</td>
              <td>{{ h.note }}</td>
              <td>{{ h.updated_by }}</td>
              <td class="text-no-wrap">{{ dateTime(h.updated_at) }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { api } from '../api/client';
import type { ErrorCase, ExceptionStatus, ExceptionType, SettlementException } from '../api/types';
import ErrorCaseDialog from '../components/ErrorCaseDialog.vue';
import ExceptionFormDialog from '../components/ExceptionFormDialog.vue';
import { useSettlementStore } from '../stores/settlement';
import { dateTime, kwh } from '../utils/format';

const $q = useQuasar();
const store = useSettlementStore();
const tab = ref<'exceptions' | 'errors'>('exceptions');
const loading = ref(false);
const items = ref<SettlementException[]>([]);
const errorCases = ref<ErrorCase[]>([]);
const showClosed = ref(false);
const search = ref<string | null>('');
const historyOpen = ref(false);
const historyRows = ref<SettlementException[]>([]);

const STATUS_COLOR: Record<ExceptionStatus, string> = { REGISTERED: 'blue-6', ACTIVE: 'positive', CLOSED: 'grey-6' };
const typeLabel = (t: ExceptionType) => store.meta?.exception_types.find((x) => x.value === t)?.label ?? t;

const filtered = computed(() => {
  const q = (search.value ?? '').toLowerCase();
  return items.value
    .filter((e) => showClosed.value || e.status !== 'CLOSED')
    .filter((e) => !q || e.plant_id.toLowerCase().includes(q) || e.exception_id.toLowerCase().includes(q));
});

const columns: QTableColumn<SettlementException>[] = [
  { name: 'id', label: '번호', field: 'exception_id', align: 'left', sortable: true },
  { name: 'month', label: '정산월', field: 'month', align: 'left' },
  { name: 'plant', label: '발전소', field: 'plant_id', align: 'left', sortable: true },
  { name: 'type', label: '유형', field: 'type', align: 'left' },
  { name: 'base_date', label: '기준일', field: 'base_date', align: 'left', format: (v: string | null) => v ?? '-' },
  { name: 'change', label: '변경 전 → 후', field: 'partner_after', align: 'left' },
  { name: 'manual', label: '수기 발행량', field: 'manual_kwh', align: 'right', format: (v: string | null) => (v ? kwh(v) : '-') },
  { name: 'note', label: '비고', field: 'note', align: 'left', style: 'white-space: normal; max-width: 240px' },
  { name: 'status', label: '상태', field: 'status', align: 'left' },
  { name: 'audit', label: '작성', field: 'updated_by', align: 'left' },
  { name: 'actions', label: '', field: 'exception_id', align: 'right' },
];

const errorColumns: QTableColumn<ErrorCase>[] = [
  { name: 'no', label: '번호', field: 'case_no', align: 'left', sortable: true },
  { name: 'occurred', label: '발생일', field: 'occurred_on', align: 'left', sortable: true },
  { name: 'month', label: '정산월', field: 'month', align: 'left' },
  { name: 'plant', label: '발전소', field: 'plant_id', align: 'left' },
  { name: 'symptom', label: '증상', field: 'symptom', align: 'left', style: 'white-space: normal' },
  { name: 'by', label: '등록자', field: 'created_by', align: 'left' },
];

async function reload() {
  loading.value = true;
  try {
    [items.value, errorCases.value] = await Promise.all([api.exceptions(store.month), api.errorCases(store.month)]);
  } finally {
    loading.value = false;
  }
}
onMounted(reload);

function create() {
  $q.dialog({ component: ExceptionFormDialog }).onOk(reload);
}
function edit(row: SettlementException) {
  $q.dialog({ component: ExceptionFormDialog, componentProps: { editing: row } }).onOk(reload);
}
function close(row: SettlementException) {
  $q.dialog({
    title: '예외 종료',
    message: `${row.exception_id} 를 종료합니다. 종료된 예외는 이후 대조에 반영되지 않습니다.`,
    cancel: { label: '취소', flat: true },
    ok: { label: '종료', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.closeException(row.exception_id);
      await reload();
    } catch (e) {
      $q.notify({ type: 'negative', message: (e as Error).message });
    }
  });
}
async function showHistory(row: SettlementException) {
  historyRows.value = await api.exceptionHistory(row.exception_id);
  historyOpen.value = true;
}
function addError() {
  $q.dialog({ component: ErrorCaseDialog, componentProps: { month: store.month } }).onOk(reload);
}
</script>
