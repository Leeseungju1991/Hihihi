<template>
  <q-dialog ref="dialogRef" persistent @hide="onDialogHide">
    <q-card style="width: 480px; max-width: 95vw">
      <q-card-section class="text-h6">에러 케이스 추가</q-card-section>
      <q-card-section class="q-gutter-sm">
        <div class="row q-col-gutter-sm">
          <q-input v-model="form.occurred_on" class="col-6" dense outlined type="date" stack-label label="발생일 *" />
          <q-input v-model="form.month" class="col-6" dense outlined mask="####-##" label="정산월 *" />
        </div>
        <q-input v-model="form.plant_id" dense outlined label="발전소 *" />
        <q-input v-model="form.symptom" dense outlined autogrow label="증상 *" :error="!!error" :error-message="error" />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="취소" @click="onDialogCancel" />
        <q-btn color="negative" unelevated label="추가" :loading="saving" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useDialogPluginComponent, useQuasar } from 'quasar';
import { api } from '../api/client';

const props = defineProps<{ month: string; plantId?: string; symptom?: string }>();
defineEmits([...useDialogPluginComponent.emits]);
const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent();
const $q = useQuasar();

const form = reactive({
  occurred_on: new Date().toISOString().slice(0, 10),
  month: props.month,
  plant_id: props.plantId ?? '',
  symptom: props.symptom ?? '',
});
const error = ref('');
const saving = ref(false);

async function save() {
  error.value = '';
  if (!form.plant_id.trim() || !form.symptom.trim() || !form.occurred_on) {
    error.value = '발생일·발전소·증상은 필수입니다';
    return;
  }
  saving.value = true;
  try {
    const c = await api.addErrorCase(form);
    $q.notify({ type: 'positive', message: `${c.case_no} 등록됨` });
    onDialogOK(c);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    saving.value = false;
  }
}
</script>
