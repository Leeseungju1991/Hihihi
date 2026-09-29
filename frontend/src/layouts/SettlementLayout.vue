<template>
  <q-layout view="hHh lpR fFf">
    <q-header class="app-header">
      <q-toolbar class="q-px-md" style="min-height: 60px">
        <div class="brand row items-center no-wrap">
          <div class="brand__logo"><q-icon name="bolt" size="18px" /></div>
          <div>
            <div class="brand__title">AX 정산 오케스트레이터</div>
            <div class="brand__sub">분개 · 송장 · 세금계산서 3자 대조</div>
          </div>
        </div>
        <q-space />

        <q-input
          v-model="monthInput"
          dense
          outlined
          mask="####-##"
          label="정산월"
          style="width: 124px"
          class="q-mr-sm"
          @keyup.enter="changeMonth"
          @blur="changeMonth"
        >
          <template #prepend><q-icon name="event" size="18px" /></template>
        </q-input>

        <transition name="page" mode="out-in">
          <q-chip v-if="store.locked" key="locked" square icon="lock" class="q-mr-sm" :color="isDark ? 'grey-9' : 'grey-3'">
            확정됨 · {{ who(store.status?.approval?.actor) }}
          </q-chip>
          <q-btn
            v-else-if="store.meta?.user.is_approver"
            key="finalize"
            unelevated
            no-caps
            class="q-mr-sm q-px-md"
            icon="verified"
            label="최종 확정"
            :color="isDark ? 'grey-2' : 'dark'"
            :text-color="isDark ? 'dark' : 'white'"
            :disable="!store.run"
            @click="finalize"
          />
        </transition>

        <q-btn flat round dense :icon="isDark ? 'light_mode' : 'dark_mode'" aria-label="테마 전환" @click="toggle">
          <q-tooltip>{{ isDark ? '라이트 모드' : '다크 모드' }}</q-tooltip>
        </q-btn>
      </q-toolbar>

      <StepNav />
      <q-linear-progress :value="progressValue" size="2px" color="positive" track-color="transparent" animation-speed="400" />
    </q-header>

    <q-page-container>
      <router-view v-if="ready" v-slot="{ Component, route }">
        <transition name="page" mode="out-in">
          <component :is="Component" :key="`${String(route.name)}:${store.month}`" />
        </transition>
      </router-view>
      <div v-else class="flex flex-center q-pa-xl">
        <q-spinner-dots size="40px" color="primary" />
      </div>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { api } from '../api/client';
import type { FinalizeCheck } from '../api/types';
import StepNav from '../components/StepNav.vue';
import { useTheme } from '../composables/useTheme';
import { useSettlementStore } from '../stores/settlement';
import { who } from '../utils/format';
import { progress } from '../utils/steps';

const $q = useQuasar();
const store = useSettlementStore();
const { toggle, isDark } = useTheme();
const ready = ref(false);
const monthInput = ref(store.month);
const progressValue = computed(() => progress(store.stepFacts));

onMounted(async () => {
  try {
    await store.init();
  } catch (e) {
    $q.notify({ type: 'negative', message: (e as Error).message });
  } finally {
    ready.value = true;
  }
});

async function changeMonth() {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthInput.value) || monthInput.value === store.month) return;
  ready.value = false;
  try {
    await store.selectMonth(monthInput.value);
  } catch (e) {
    $q.notify({ type: 'negative', message: (e as Error).message });
  } finally {
    ready.value = true;
  }
}

async function doFinalize(acknowledge: boolean) {
  try {
    await api.finalize(store.month, acknowledge);
    $q.notify({ type: 'positive', message: `${store.month} 정산을 확정했습니다` });
    await store.refreshRun();
  } catch (e) {
    $q.notify({ type: 'negative', message: (e as Error).message });
  }
}

/** 사전 점검 → 경고가 있으면 경고창, 없으면 일반 확인창 */
async function finalize() {
  let check: FinalizeCheck;
  try {
    check = await api.finalizeCheck(store.month);
  } catch (e) {
    $q.notify({ type: 'negative', message: (e as Error).message });
    return;
  }
  if (check.warnings.length) {
    $q.dialog({
      title: '확정 경고',
      message:
        `${check.warnings.join('<br>')}<br><br>` +
        (check.open_holds.length ? `보류: ${check.open_holds.join(', ')}<br>` : '') +
        (check.unresolved.length ? `미해결: ${check.unresolved.join(', ')}<br>` : '') +
        '<br>그래도 확정하시겠습니까? (보류 건은 리포트에 별도 표기됩니다)',
      html: true,
      cancel: { label: '취소', flat: true },
      ok: { label: '경고 확인 후 확정', color: 'negative', unelevated: true },
      persistent: true,
    }).onOk(() => void doFinalize(true));
    return;
  }
  $q.dialog({
    title: '최종 확정',
    message: `${store.month} 정산을 확정합니다. 확정 후에는 예외·보류·자동화를 수정할 수 없습니다.`,
    cancel: { label: '취소', flat: true },
    ok: { label: '확정', color: 'primary', unelevated: true },
  }).onOk(() => void doFinalize(false));
}
</script>

<style scoped>
.brand {
  gap: 10px;
}
.brand__logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--q-primary);
  color: #fff;
}
.brand__title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
.brand__sub {
  font-size: 11px;
  color: var(--app-muted);
  line-height: 1.3;
}
</style>
