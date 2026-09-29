<template>
  <q-dialog ref="dialogRef" persistent @hide="onDialogHide">
    <q-card style="width: 560px; max-width: 95vw">
      <q-card-section class="text-h6">{{ editing ? `예외 수정 · ${editing.exception_id}` : '예외 등록' }}</q-card-section>
      <q-card-section class="q-gutter-sm">
        <div class="row q-col-gutter-sm">
          <q-input v-model="form.month" class="col-4" dense outlined mask="####-##" label="정산월 *" :error="!!errors.month" :error-message="errors.month" />
          <q-select
            v-model="form.plant_id"
            class="col-8"
            dense
            outlined
            use-input
            emit-value
            map-options
            input-debounce="200"
            label="발전소 * (마스터 검색)"
            :options="plantOptions"
            :error="!!errors.plant_id"
            :error-message="errors.plant_id"
            @filter="filterPlants"
          />
        </div>
        <q-select
          v-model="form.type"
          dense
          outlined
          emit-value
          map-options
          label="예외 유형 *"
          :options="typeOptions"
        />
        <div v-if="need('base_date')" class="row q-col-gutter-sm">
          <q-input v-model="form.base_date" class="col-4" dense outlined type="date" label="기준일 *" stack-label :error="!!errors.base_date" :error-message="errors.base_date" />
          <q-input v-model="form.partner_before" class="col-4" dense outlined label="변경 전 조합 *" :error="!!errors.partner_before" :error-message="errors.partner_before" />
          <q-input v-model="form.partner_after" class="col-4" dense outlined label="변경 후 조합 *" :error="!!errors.partner_after" :error-message="errors.partner_after" />
        </div>
        <div v-if="need('manual_kwh')" class="row q-col-gutter-sm">
          <q-input v-model="form.manual_kwh" class="col-6" dense outlined inputmode="decimal" label="수기 발행 발전량(kWh) *" :error="!!errors.manual_kwh" :error-message="errors.manual_kwh" />
          <q-input v-model="form.partner_after" class="col-6" dense outlined label="발행 조합 *" :error="!!errors.partner_after" :error-message="errors.partner_after" />
        </div>
        <q-input
          v-model="form.note"
          dense
          outlined
          autogrow
          :label="need('note') ? '비고 *' : '비고'"
          :error="!!errors.note"
          :error-message="errors.note"
        />
        <div v-if="editing" class="text-caption text-grey-7">
          상태 {{ statusLabel }} · v{{ editing.version }} · {{ editing.updated_by }}
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="취소" @click="onDialogCancel" />
        <q-btn color="primary" unelevated :loading="saving" :label="editing ? '저장' : '등록'" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useDialogPluginComponent, useQuasar } from 'quasar';
import { api, ApiError } from '../api/client';
import type { ExceptionInput, ExceptionType, SettlementException } from '../api/types';
import { useSettlementStore } from '../stores/settlement';

const props = defineProps<{
  editing?: SettlementException | null;
  preset?: Partial<ExceptionInput>;
}>();
defineEmits([...useDialogPluginComponent.emits]);

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent();
const $q = useQuasar();
const store = useSettlementStore();
const saving = ref(false);
const errors = reactive<Record<string, string>>({});

const form = reactive<ExceptionInput>({
  month: props.editing?.month ?? props.preset?.month ?? store.month,
  plant_id: props.editing?.plant_id ?? props.preset?.plant_id ?? '',
  type: props.editing?.type ?? props.preset?.type ?? 'TRANSFER',
  base_date: props.editing?.base_date ?? null,
  partner_before: props.editing?.partner_before ?? '',
  partner_after: props.editing?.partner_after ?? '',
  manual_kwh: props.editing?.manual_kwh ?? null,
  note: props.editing?.note ?? '',
});

const typeOptions = computed(() => store.meta?.exception_types.map((t) => ({ value: t.value, label: t.label })) ?? []);
const required = computed(() => store.meta?.exception_types.find((t) => t.value === form.type)?.required ?? []);
const need = (field: string) => required.value.includes(field) || (field === 'base_date' && isSplit(form.type));
const isSplit = (t: ExceptionType) => t === 'TRANSFER' || t === 'PARTNER_CHANGE' || t === 'PPA_DELAY';
const statusLabel = computed(() => (props.editing ? store.meta?.exception_statuses[props.editing.status] : ''));

const plantOptions = ref<{ value: string; label: string }[]>(
  form.plant_id ? [{ value: form.plant_id, label: form.plant_id }] : [],
);
function filterPlants(val: string, update: (fn: () => void) => void) {
  void api.plants(val).then((list) =>
    update(() => {
      plantOptions.value = list.map((p) => ({ value: p.plant_id, label: `${p.plant_id} · ${p.name}` }));
    }),
  );
}

// 즉시 검증 — 서버 규칙(REQUIRED_FIELDS)과 동일한 목록을 meta 로 받아 쓴다
function validate(): boolean {
  Object.keys(errors).forEach((k) => delete errors[k]);
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(form.month)) errors.month = 'YYYY-MM 형식';
  if (!form.plant_id) errors.plant_id = '발전소를 선택하세요';
  for (const f of required.value) {
    const v = form[f as keyof ExceptionInput];
    if (v === null || v === undefined || String(v).trim() === '') errors[f] = '필수 입력입니다';
  }
  if (form.base_date && isSplit(form.type) && !form.base_date.startsWith(form.month)) {
    errors.base_date = '기준일은 정산월 안의 날짜여야 합니다';
  }
  if (form.manual_kwh && !(Number(form.manual_kwh) > 0)) errors.manual_kwh = '0보다 큰 숫자';
  return Object.keys(errors).length === 0;
}
watch(() => ({ ...form }), () => Object.keys(errors).length && validate());

async function save() {
  if (!validate()) return;
  saving.value = true;
  const body: ExceptionInput = {
    ...form,
    base_date: isSplit(form.type) ? form.base_date : null,
    manual_kwh: form.type === 'MANUAL_ISSUE' ? form.manual_kwh : null,
    partner_before: isSplit(form.type) ? form.partner_before : '',
  };
  try {
    const saved = props.editing
      ? await api.updateException(props.editing.exception_id, body)
      : await api.createException(body);
    $q.notify({ type: 'positive', message: `예외 ${saved.exception_id} 저장됨` });
    onDialogOK(saved);
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) Object.assign(errors, e.fieldErrors);
    else $q.notify({ type: 'negative', message: (e as Error).message });
  } finally {
    saving.value = false;
  }
}
</script>
