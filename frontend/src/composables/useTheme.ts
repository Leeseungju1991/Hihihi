// 라이트/다크 전환. 저장된 선택이 없으면 OS 설정을 따른다.
import { computed } from 'vue';
import { useQuasar } from 'quasar';

const KEY = 'ax-settlement-theme';

function readSaved(): 'light' | 'dark' | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;
  }
}

export function useTheme() {
  const $q = useQuasar();

  function init() {
    const saved = readSaved();
    $q.dark.set(saved === null ? 'auto' : saved === 'dark');
  }

  function toggle() {
    const next = $q.dark.isActive ? 'light' : 'dark';
    $q.dark.set(next === 'dark');
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* 저장 불가(시크릿 모드 등) — 이번 세션에만 적용 */
    }
  }

  const isDark = computed(() => $q.dark.isActive);
  return { init, toggle, isDark };
}
