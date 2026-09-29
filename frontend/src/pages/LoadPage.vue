<template>
  <q-page padding>
    <div class="text-h6 q-mb-md">① 데이터 불러오기</div>
    <q-card flat bordered style="max-width: 640px">
      <q-card-section class="row items-center q-gutter-md">
        <div>정산월 <b>{{ store.month }}</b></div>
        <q-btn color="primary" unelevated icon="cloud_download" label="데이터 불러오기" :loading="loading" @click="load" />
        <q-btn
          v-if="store.counts"
          outline
          color="primary"
          icon="compare_arrows"
          label="3자 대조로"
          :to="{ name: 'settlement-reconcile' }"
        />
      </q-card-section>
      <q-separator />
      <q-list separator>
        <q-item v-for="row in rows" :key="row.key">
          <q-item-section>
            <q-item-label>{{ row.label }}</q-item-label>
            <q-item-label caption>{{ row.table }}</q-item-label>
          </q-item-section>
          <q-item-section side class="text-h6 num">
            {{ store.counts ? `${store.counts[row.key].toLocaleString('ko-KR')}건` : '-' }}
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>
    <div class="text-caption text-grey-7 q-mt-sm">운영 데이터는 읽기만 합니다. 보정값은 별도 테이블에 저장됩니다.</div>
  </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useQuasar } from 'quasar';
import { useSettlementStore } from '../stores/settlement';

const $q = useQuasar();
const store = useSettlementStore();
const loading = ref(false);

const rows = [
  { key: 'journal', label: '분개장(412)', table: 'pv_biz_bal_item' },
  { key: 'invoice', label: '송장', table: 'pv_sales_invoice' },
  { key: 'tax_invoice', label: '세금계산서', table: 'stg_nts_tax_invoice' },
] as const;

async function load() {
  loading.value = true;
  try {
    await store.load();
  } catch (e) {
    $q.notify({ type: 'negative', message: (e as Error).message });
  } finally {
    loading.value = false;
  }
}
</script>
