<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h6 col">④ 확인 대상</div>
      <q-btn-toggle
        v-model="filter"
        unelevated
        toggle-color="primary"
        :options="[
          { label: `확인 대상 ${n('REVIEW')}`, value: 'REVIEW' },
          { label: `에러 ${n('ERROR')}`, value: 'ERROR' },
          { label: `보류 ${n('HOLD')}`, value: 'HOLD' },
          { label: '전체 미해결', value: 'ALL' },
        ]"
      />
      <q-select
        v-model="tagFilter"
        dense
        outlined
        clearable
        emit-value
        map-options
        label="유형 태그"
        style="min-width: 160px"
        :options="tagOptions"
      />
    </div>

    <div v-if="!store.run" class="text-grey-7 q-pa-lg text-center">③ 3자 대조를 먼저 실행하세요.</div>

    <ResultTable v-else :rows="rows" @open="act.openDetail">
      <template v-if="!store.locked" #actions="{ row }">
        <div class="text-no-wrap">
          <q-btn dense flat size="sm" icon="add_circle" @click="act.registerException(row)"><q-tooltip>예외 등록</q-tooltip></q-btn>
          <q-btn dense flat size="sm" icon="report" color="negative" @click="act.addErrorCase(row)"><q-tooltip>에러 케이스 추가</q-tooltip></q-btn>
          <q-btn dense flat size="sm" icon="refresh" color="primary" @click="act.recheck(row)"><q-tooltip>재검증</q-tooltip></q-btn>
          <q-btn v-if="row.category === 'HOLD'" dense flat size="sm" icon="undo" @click="act.release(row)"><q-tooltip>보류 해제 · 재검증</q-tooltip></q-btn>
          <q-btn v-else dense flat size="sm" icon="pause_circle" color="grey-8" @click="act.hold(row)"><q-tooltip>보류</q-tooltip></q-btn>
        </div>
      </template>
    </ResultTable>
    <div class="text-caption text-grey-7 q-mt-sm">행을 누르면 원천값 · 근거 · 실패 원인 · 추천 조치 · 재검증 이력을 봅니다.</div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Category, IssueTag } from '../api/types';
import ResultTable from '../components/ResultTable.vue';
import { useResultActions } from '../components/useResultActions';
import { useSettlementStore } from '../stores/settlement';

const store = useSettlementStore();
const act = useResultActions();
const filter = ref<Category | 'ALL'>('REVIEW');
const tagFilter = ref<IssueTag | null>(null);

const n = (c: Category) => store.run?.category_counts[c] ?? 0;
const tagOptions = computed(() =>
  Object.entries(store.meta?.tags ?? {}).map(([value, label]) => ({ value, label })),
);
const rows = computed(() => {
  const unresolved: Category[] = ['REVIEW', 'ERROR', 'HOLD', 'AUTOMATABLE'];
  return (store.run?.results ?? [])
    .filter((r) => (filter.value === 'ALL' ? unresolved.includes(r.category) : r.category === filter.value))
    .filter((r) => !tagFilter.value || r.tags.includes(tagFilter.value));
});
</script>
