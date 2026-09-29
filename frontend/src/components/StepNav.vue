<template>
  <nav class="step-nav" aria-label="정산 단계">
    <template v-for="(s, i) in STEPS" :key="s.key">
      <router-link
        :to="{ name: s.route }"
        class="step"
        :class="`step--${states[s.key]}`"
        :aria-current="states[s.key] === 'current' ? 'step' : undefined"
      >
        <span class="step__mark">
          <q-icon v-if="states[s.key] === 'done'" name="check" size="14px" />
          <template v-else>{{ s.no }}</template>
        </span>
        <span class="step__text">
          <span class="step__title">
            {{ s.title }}
            <q-badge v-if="badges[s.key]" :color="badges[s.key]!.color" rounded class="q-ml-xs">{{ badges[s.key]!.n }}</q-badge>
          </span>
          <span class="step__state">
            <template v-if="states[s.key] === 'current'"><span class="pulse-dot q-mr-xs" />진행중</template>
            <template v-else-if="states[s.key] === 'done'">완료</template>
            <template v-else>대기</template>
          </span>
        </span>
      </router-link>
      <span v-if="i < STEPS.length - 1" class="step__line" :class="{ 'step__line--done': states[s.key] === 'done' }" />
    </template>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { useSettlementStore } from '../stores/settlement';
import { STEPS, stepStates, type StepKey } from '../utils/steps';

const route = useRoute();
const store = useSettlementStore();

const current = computed<StepKey | null>(() => STEPS.find((s) => s.route === route.name)?.key ?? null);
const states = computed(() => stepStates(current.value, store.stepFacts));
const badges = computed<Partial<Record<StepKey, { n: number; color: string }>>>(() => {
  const c = store.run?.category_counts;
  if (!c || store.locked) return {};
  const out: Partial<Record<StepKey, { n: number; color: string }>> = {};
  if (c.AUTOMATABLE) out.reconcile = { n: c.AUTOMATABLE, color: 'primary' };
  if (c.REVIEW + c.ERROR) out.review = { n: c.REVIEW + c.ERROR, color: 'warning' };
  return out;
});
</script>

<style scoped>
.step-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 16px 10px;
  overflow-x: auto;
  scrollbar-width: none;
}
.step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px 6px 8px;
  border-radius: 10px;
  color: var(--app-muted);
  text-decoration: none;
  white-space: nowrap;
  transition:
    background-color 0.18s ease,
    color 0.18s ease;
}
.step:hover {
  background: var(--app-surface-2);
}
.step__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  border: 1.5px solid var(--step-line);
  color: var(--app-muted);
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}
.step__text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}
.step__title {
  font-size: 13px;
  font-weight: 600;
}
.step__state {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  color: var(--app-subtle);
}
.step__line {
  flex: 0 0 24px;
  height: 1.5px;
  background: var(--step-line);
  transition: background-color 0.3s ease;
}
.step__line--done {
  background: var(--q-positive);
}

/* 진행중 */
.step--current {
  color: var(--app-text);
  background: color-mix(in srgb, var(--q-primary) 8%, transparent);
}
.step--current .step__mark {
  background: var(--q-primary);
  border-color: var(--q-primary);
  color: #fff;
}
.step--current .step__state {
  color: var(--q-primary);
  font-weight: 600;
}
/* 확정 후 등, 진행중이 아닌 상태에서 지금 보고 있는 단계 */
.step.router-link-exact-active:not(.step--current) {
  background: var(--app-surface-2);
  box-shadow: inset 0 -2px 0 var(--q-positive);
}
/* 완료 */
.step--done {
  color: var(--app-text);
}
.step--done .step__mark {
  background: var(--q-positive);
  border-color: var(--q-positive);
  color: #fff;
}
.step--done .step__state {
  color: var(--q-positive);
}
</style>
