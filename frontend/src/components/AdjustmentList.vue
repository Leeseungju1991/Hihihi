<template>
  <q-list bordered separator dense class="rounded-borders">
    <q-item v-for="a in items" :key="a.adjustment_id">
      <q-item-section>
        <q-item-label>
          <q-badge :color="a.basis === 'ESTIMATED' ? 'orange' : 'teal'" class="q-mr-xs">
            {{ a.basis === 'ESTIMATED' ? '추정' : '실제' }}
          </q-badge>
          {{ KIND_LABEL[a.kind] }} · {{ a.partner_id }} {{ kwh(a.kwh_before) }} → <b>{{ kwh(a.kwh_after) }}</b>
        </q-item-label>
        <q-item-label caption>{{ a.formula }}</q-item-label>
        <q-item-label v-if="showApplied" caption>{{ a.applied_by }} · {{ dateTime(a.applied_at) }}</q-item-label>
      </q-item-section>
    </q-item>
  </q-list>
</template>

<script setup lang="ts">
import type { Adjustment } from '../api/types';
import { dateTime, KIND_LABEL, kwh } from '../utils/format';

defineProps<{ items: Adjustment[]; showApplied?: boolean }>();
</script>
