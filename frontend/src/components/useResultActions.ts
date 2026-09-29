// [예외 등록] [에러 케이스 추가] [재검증] [보류] — ③·④ 화면 공용 동작
import { useQuasar } from 'quasar';
import { api } from '../api/client';
import type { PlantResult, RecheckRecord } from '../api/types';
import { useSettlementStore } from '../stores/settlement';
import ErrorCaseDialog from './ErrorCaseDialog.vue';
import ExceptionFormDialog from './ExceptionFormDialog.vue';
import PlantDetailDialog from './PlantDetailDialog.vue';

export function useResultActions() {
  const $q = useQuasar();
  const store = useSettlementStore();

  const fail = (e: unknown) => $q.notify({ type: 'negative', message: (e as Error).message });

  function notifyRecheck(rc: RecheckRecord) {
    if (rc.passed) {
      $q.notify({ type: 'positive', message: `${rc.plant_id} 재검증 통과`, timeout: 2500 });
    } else if (rc.category === 'AUTOMATABLE') {
      $q.notify({
        type: 'info',
        message: `${rc.plant_id} 자동화 대상으로 전환`,
        caption: '③ 3자 대조에서 [자동화 시작]으로 보정을 적용하세요',
        timeout: 6000,
      });
    } else {
      $q.notify({
        type: 'warning',
        message: `${rc.plant_id} 재검증 미통과 (${rc.attempt}회차)`,
        caption: rc.cause,
        timeout: 6000,
      });
    }
  }

  function registerException(r: PlantResult) {
    $q.dialog({
      component: ExceptionFormDialog,
      componentProps: { preset: { month: r.month, plant_id: r.plant_id } },
    }).onOk(() => {
      $q.dialog({
        title: '예외 등록됨',
        message: '지금 재검증하시겠습니까? 예외로 해소 가능하면 자동화 대상으로 전환됩니다.',
        cancel: { label: '나중에', flat: true },
        ok: { label: '재검증', color: 'primary' },
      }).onOk(() => void recheck(r));
    });
  }

  function addErrorCase(r: PlantResult) {
    $q.dialog({
      component: ErrorCaseDialog,
      componentProps: { month: r.month, plantId: r.plant_id, symptom: r.summary },
    });
  }

  async function recheck(r: PlantResult) {
    try {
      const rc = await api.recheck(r.month, r.plant_id);
      notifyRecheck(rc);
      await store.refreshRun();
      return rc;
    } catch (e) {
      fail(e);
    }
  }

  function hold(r: PlantResult) {
    $q.dialog({
      title: `보류 · ${r.plant_name}`,
      message: '미해결 상태로 두고 다음 단계로 진행합니다. 사유는 필수이며 리포트에 표기됩니다.',
      prompt: { model: '', type: 'textarea', isValid: (v: string) => v.trim().length > 0, label: '보류 사유 *' },
      cancel: { label: '취소', flat: true },
      ok: { label: '보류', color: 'grey-8' },
    }).onOk(async (reason: string) => {
      try {
        await api.hold(r.month, r.plant_id, reason);
        await store.refreshRun();
      } catch (e) {
        fail(e);
      }
    });
  }

  async function release(r: PlantResult) {
    try {
      notifyRecheck(await api.releaseHold(r.month, r.plant_id));
      await store.refreshRun();
    } catch (e) {
      fail(e);
    }
  }

  function openDetail(r: PlantResult) {
    $q.dialog({ component: PlantDetailDialog, componentProps: { month: r.month, plantId: r.plant_id } });
  }

  return { registerException, addErrorCase, recheck, hold, release, openDetail, notifyRecheck };
}
