<template>
  <q-badge :color="CATEGORY_COLOR[category]" class="q-px-sm q-py-xs">{{ store.categoryLabel(category) }}</q-badge>
</template>

<script setup lang="ts">
import type { Category } from '../api/types';
import { useSettlementStore } from '../stores/settlement';
import { CATEGORY_COLOR } from '../utils/format';

defineProps<{ category: Category }>();
const store = useSettlementStore();
</script>
