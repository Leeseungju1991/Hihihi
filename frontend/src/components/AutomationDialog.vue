<template>
  <!-- 자동화 안내창: 적용 공식, 대상 건수, 보정 전·후 미리보기 → [확인] -->
  <q-dialog ref="dialogRef" persistent @hide="onDialogHide">
    <q-card style="width: 1100px; max-width: 96vw">
      <q-card-section>
        <div class="text-h6">자동화 시작</div>
        <div class="text-body2 q-mt-xs">
          대상 <b>{{ preview.target_count }}건</b> · 적용 공식
          <q-chip v-for="f in preview.formulas" :key="f" dense color="blue-1" text-color="primary">{{ KIND_LABEL[f] }}</q-chip>
        </div>
        <div class="text-caption text-grey-7">
          검침량·일 평균 발전시간만 보정하며 금액은 수정하지 않습니다. 보정값은 별도 테이블에 저장되고 실행 직후 자동 재검증합니다.
          재검증을 통과하지 못한 발전소의 보정은 되돌리고 실패 원인을 표시합니다.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section style="max-height: 60vh" class="scroll">
        <q-markup-table flat dense separator="horizontal">
          <thead>
            <tr>
              <th class="text-left">발전소</th>
              <th class="text-left">보정 내용</th>
              <th class="text-right">보정 전</th>
              <th class="text-right">보정 후</th>
              <th class="text-left">예상</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in preview.items" :key="it.plant_id">
              <td class="text-no-wrap">{{ it.plant_name }}<div class="text-caption text-grey-7">{{ it.plant_id }}</div></td>
              <td style="white-space: normal">
                <div v-for="a in it.adjustments" :key="a.adjustment_id" class="q-mb-xs">
                  <q-badge :color="a.basis === 'ESTIMATED' ? 'orange' : 'teal'" class="q-mr-xs">
                    {{ a.basis === 'ESTIMATED' ? '추정' : '실제' }}
                  </q-badge>
                  <span class="text-weight-medium">{{ KIND_LABEL[a.kind] }}</span>
                  <span class="text-caption"> · {{ a.partner_id }} {{ kwh(a.kwh_before) }} → {{ kwh(a.kwh_after) }}</span>
                  <div class="text-caption text-grey-7" style="white-space: normal">{{ a.formula }}</div>
                </div>
              </td>
              <td class="num">{{ kwh(it.kwh_before) }}</td>
              <td class="num text-weight-bold">{{ kwh(it.kwh_after) }}</td>
              <td style="white-space: normal; min-width: 160px">
                <q-badge v-if="it.predicted_pass" color="positive">통과 예상</q-badge>
                <template v-else>
                  <q-badge color="warning">미통과 예상</q-badge>
                  <div v-for="m in it.remaining_issues" :key="m" class="text-caption text-grey-8">{{ m }}</div>
                </template>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="취소" @click="onDialogCancel" />
        <q-btn color="primary" unelevated icon="play_arrow" label="확인 · 실행" @click="onDialogOK(true)" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { useDialogPluginComponent } from 'quasar';
import type { AutomationPreview } from '../api/types';
import { KIND_LABEL, kwh } from '../utils/format';

defineProps<{ preview: AutomationPreview }>();
defineEmits([...useDialogPluginComponent.emits]);
const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent();
</script>
