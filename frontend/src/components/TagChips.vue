<template>
  <span>
    <q-chip
      v-for="t in tags"
      :key="t"
      dense
      square
      text-color="white"
      :color="TAG_COLOR[t]"
      class="q-ml-none q-mr-xs"
    >
      {{ store.meta?.tags[t] ?? t }}
    </q-chip>
  </span>
</template>

<script setup lang="ts">
import type { IssueTag } from '../api/types';
import { useSettlementStore } from '../stores/settlement';
import { TAG_COLOR } from '../utils/format';

defineProps<{ tags: IssueTag[] }>();
const store = useSettlementStore();
</script>
