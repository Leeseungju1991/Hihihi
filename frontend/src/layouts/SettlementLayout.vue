<template>
  <q-layout view="hHh lpR fFf">
    <q-header bordered class="bg-white text-dark">
      <q-toolbar>
        <q-toolbar-title class="text-weight-bold">AX 정산 오케스트레이터</q-toolbar-title>

        <q-input
          v-model="monthInput"
          dense
          outlined
          mask="####-##"
          label="정산월"
          style="width: 130px"
          class="q-mr-sm"
          @keyup.enter="changeMonth"
          @blur="changeMonth"
        />
        <q-badge v-if="store.locked" color="grey-8" class="q-mr-sm q-pa-sm">
          <q-icon name="lock" class="q-mr-xs" />확정됨 · {{ store.status?.approval?.actor }}
        </q-badge>
        <q-btn
          v-else-if="store.meta?.user.is_approver"
          color="dark"
          unelevated
          dense
          class="q-px-md q-mr-sm"
          icon="verified"
          label="최종 확정"
          :disable="!store.run"
          @click="finalize"
        />
        <div class="text-caption text-grey-7">{{ store.meta?.user.email }}</div>
      </q-toolbar>

      <q-tabs align="left" dense active-color="primary" indicator-color="primary" class="text-grey-8">
        <q-route-tab :to="{ name: 'settlement-load' }" label="① 데이터 불러오기" />
        <q-route-tab :to="{ name: 'settlement-exceptions' }" label="② 예외 관리" />
        <q-route-tab :to="{ name: 'settlement-reconcile' }">
          <div class="row items-center no-wrap">
            ③ 3자 대조
            <q-badge v-if="auto" color="primary" class="q-ml-xs">{{ auto }}</q-badge>
          </div>
        </q-route-tab>
        <q-route-tab :to="{ name: 'settlement-review' }">
          <div class="row items-center no-wrap">
            ④ 확인 대상
            <q-badge v-if="review" color="warning" class="q-ml-xs">{{ review }}</q-badge>
          </div>
        </q-route-tab>
        <q-route-tab :to="{ name: 'settlement-report' }" label="⑤ 리포트" />
      </q-tabs>
    </q-header>

    <q-page-container>
      <router-view v-if="ready" :key="store.month" />
      <div v-else class="flex flex-center q-pa-xl">
        <q-spinner size="lg" />
      </div>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { useSettlementStore } from '../stores/settlement';
import { api, ApiError } from '../api/client';
import type { FinalizeWarning } from '../api/types';

const $q = useQuasar();
const store = useSettlementStore();
const ready = ref(false);
const monthInput = ref(store.month);

const auto = computed(() => store.run?.category_counts.AUTOMATABLE ?? 0);
const review = computed(
  () => (store.run?.category_counts.REVIEW ?? 0) + (store.run?.category_counts.ERROR ?? 0),
);

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
    if (e instanceof ApiError && e.status === 409) {
      const w = e.body as unknown as FinalizeWarning;
      $q.dialog({
        title: '확정 경고',
        message:
          `${w.warnings.join('<br>')}<br><br>` +
          (w.open_holds.length ? `보류: ${w.open_holds.join(', ')}<br>` : '') +
          (w.unresolved.length ? `미해결: ${w.unresolved.join(', ')}<br>` : '') +
          '<br>그래도 확정하시겠습니까? (보류 건은 리포트에 별도 표기됩니다)',
        html: true,
        cancel: { label: '취소', flat: true },
        ok: { label: '경고 확인 후 확정', color: 'negative' },
        persistent: true,
      }).onOk(() => void doFinalize(true));
      return;
    }
    $q.notify({ type: 'negative', message: (e as Error).message });
  }
}

function finalize() {
  $q.dialog({
    title: '최종 확정',
    message: `${store.month} 정산을 확정합니다. 확정 후에는 예외·보류·자동화를 수정할 수 없습니다.`,
    cancel: { label: '취소', flat: true },
    ok: { label: '확정', color: 'dark' },
  }).onOk(() => void doFinalize(false));
}
</script>
