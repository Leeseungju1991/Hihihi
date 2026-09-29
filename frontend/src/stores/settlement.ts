import { defineStore } from 'pinia';
import { api, ApiError } from '../api/client';
import type { Category, Meta, MonthStatus, PlantResult, ReconcileRun } from '../api/types';
import { defaultMonth } from '../utils/format';
import type { StepFacts } from '../utils/steps';

interface State {
  month: string;
  meta: Meta | null;
  status: MonthStatus | null;
  counts: ReconcileRun['counts'] | null;
  run: ReconcileRun | null;
}

export const useSettlementStore = defineStore('settlement', {
  state: (): State => ({
    month: defaultMonth(),
    meta: null,
    status: null,
    counts: null,
    run: null,
  }),

  getters: {
    locked: (s) => s.status?.locked ?? false,
    byCategory:
      (s) =>
      (c: Category): PlantResult[] =>
        s.run?.results.filter((r) => r.category === c) ?? [],
    categoryLabel: (s) => (c: Category) => s.meta?.categories[c] ?? c,
    stepFacts: (s): StepFacts => {
      const c = s.run?.category_counts;
      return {
        loaded: s.counts !== null,
        hasRun: s.run !== null,
        automatable: c?.AUTOMATABLE ?? 0,
        unresolved: (c?.REVIEW ?? 0) + (c?.ERROR ?? 0),
        locked: s.status?.locked ?? false,
      };
    },
  },

  actions: {
    async init() {
      if (!this.meta) this.meta = await api.meta();
      await this.selectMonth(this.month);
    },

    async selectMonth(month: string) {
      this.month = month;
      this.counts = null;
      this.run = null;
      this.status = await api.status(month);
      if (this.status.latest_run_id) {
        this.run = await api.latestRun(month);
        this.counts = this.run.counts;
      }
    },

    async load() {
      const res = await api.load(this.month);
      this.counts = res.counts;
      return res;
    },

    async reconcile() {
      this.run = await api.run(this.month);
      this.counts = this.run.counts;
      this.status = await api.status(this.month);
      return this.run;
    },

    async refreshRun() {
      try {
        this.run = await api.latestRun(this.month);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) throw e;
      }
      this.status = await api.status(this.month);
    },
  },
});
