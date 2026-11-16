import type { NutrientKey, NutritionCoverage, NutritionValues } from './nutrition-contract';
import { NUTRIENT_KEYS, sumNutritionNumbers } from './nutrition-calculation';
import {
  NutritionReadError, parseNutritionDate, projectNutritionNutrient, readNutritionRecord,
} from './nutrition-read-model';
import type { NutritionNutrientRead, NutritionRecordReadModel } from './nutrition-read-model';
import { assertNutritionCoverage } from './nutrition-response-validation';

export type NutritionReadScope = {
  user_id: string;
  start_date: string;
  end_date: string;
  completeness: 'complete' | 'page';
};

export type NutritionDayRead = {
  date: string;
  record_count: number;
  state: 'recorded' | 'no_records' | 'not_loaded';
  coverage: NutritionCoverage;
  nutrients: Record<NutrientKey, NutritionNutrientRead>;
};

export type NutritionReadSummary = {
  schema_version: 'NutritionReadSummaryV1';
  scope: NutritionReadScope;
  daily: NutritionDayRead[];
  summary: {
    recorded_days: number;
    calendar_days: number;
    total_records: number;
    coverage: NutritionCoverage;
    nutrients: Record<NutrientKey, NutritionNutrientRead>;
    avg_known_sum: NutritionValues;
    avg_known_value: NutritionValues;
    avg_reported_value: NutritionValues;
    avg_value: NutritionValues;
    aggregation_scope: 'recorded_days_in_requested_range';
  };
};

function invalid(message: string): never {
  throw new NutritionReadError('invalid_scope', message);
}

function countSum(values: number[]): number {
  const total = values.reduce((sum, value) => sum + value, 0);
  if (!Number.isSafeInteger(total) || total < 0) invalid('Nutrition item counts exceed the supported range');
  return total;
}

/** Scope aggregates intentionally do not combine item IDs from different meals. */
export function aggregateReadCoverage(
  coverages: readonly NutritionCoverage[], requireEveryScopeEligible = false,
): NutritionCoverage {
  if (!Array.isArray(coverages) || coverages.length > 100_000) invalid('Expected a bounded coverage list');
  coverages.forEach((coverage) => assertNutritionCoverage(coverage, { allowIncompleteScope: true }));
  return {
    schema_version: 'NutritionCoverageV1',
    nutrients: Object.fromEntries(NUTRIENT_KEYS.map((key) => {
      const rows = coverages.map((coverage) => coverage.nutrients[key]);
      const known = countSum(rows.map((row) => row.known_items));
      const eligible = countSum(rows.map((row) => row.eligible_items));
      const bounded = countSum(rows.map((row) => row.bounded_items));
      const legacy = countSum(rows.map((row) => row.legacy_items ?? 0));
      if (known > eligible || bounded + legacy > eligible - known) invalid('Contradictory nutrition coverage counts');
      const knownSum = sumNutritionNumbers(rows.map((row) => row.known_sum));
      const boundsSum = sumNutritionNumbers(rows.map((row) => row.known_bounds_sum));
      const everyScopeEligible = !requireEveryScopeEligible || rows.every((row) => row.eligible_items > 0);
      const complete = eligible > 0 && known === eligible && everyScopeEligible &&
        rows.every((row) => row.eligible_items === 0 || row.status === 'complete');
      const hasBound = bounded > 0 && known + bounded === eligible && legacy === 0 && everyScopeEligible &&
        rows.every((row) => row.eligible_items === 0 || row.status === 'complete' || row.total_upper_bound !== null);
      return [key, {
        known_sum: knownSum, known_items: known, eligible_items: eligible,
        unresolved_items: eligible - known, bounded_items: bounded,
        known_bounds_sum: boundsSum, legacy_items: legacy,
        total_upper_bound: hasBound ? sumNutritionNumbers([knownSum, boundsSum]) : null,
        upper_bound_comparison: hasBound ? 'less_than' : null,
        status: legacy > 0 ? 'legacy_unknown' : complete ? 'complete' : known || bounded ? 'partial' : 'unknown',
      }];
    })) as NutritionCoverage['nutrients'],
  };
}

function sumPresent(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length ? sumNutritionNumbers(present) : null;
}

function projectRecords(
  records: readonly NutritionRecordReadModel[], coverage: NutritionCoverage, scopeComplete: boolean,
): Record<NutrientKey, NutritionNutrientRead> {
  return Object.fromEntries(NUTRIENT_KEYS.map((key) => {
    const reported = sumPresent(records.map((record) => record.nutrients[key].reported_value));
    const projected = projectNutritionNutrient(coverage.nutrients[key], reported, scopeComplete);
    // A mixed legacy known_sum also contains historical totals; retain only
    // validated observations in known_value, separately from reported_value.
    projected.known_value = sumPresent(records.map((record) => record.nutrients[key].known_value));
    return [key, projected];
  })) as Record<NutrientKey, NutritionNutrientRead>;
}

function dateList(scope: NutritionReadScope): string[] {
  if (!scope || typeof scope.user_id !== 'string' || !scope.user_id.trim() ||
      !['complete', 'page'].includes(scope.completeness)) invalid('A user and explicit query scope are required');
  const start = parseNutritionDate(scope.start_date);
  const end = parseNutritionDate(scope.end_date);
  const from = Date.parse(`${start}T00:00:00Z`);
  const until = Date.parse(`${end}T00:00:00Z`);
  const length = (until - from) / 86_400_000 + 1;
  if (!Number.isInteger(length) || length < 1 || length > 366) invalid('Expected an inclusive range of at most 366 days');
  return Array.from({ length }, (_, index) => new Date(from + index * 86_400_000).toISOString().slice(0, 10));
}

export function summarizeNutritionRecords(
  records: readonly NutritionRecordReadModel[], scope: NutritionReadScope,
): NutritionReadSummary {
  const dates = dateList(scope);
  if (!Array.isArray(records) || records.length > 100_000) invalid('Expected a bounded record list');
  const buckets = new Map(dates.map((date) => [date, [] as NutritionRecordReadModel[]]));
  const seen = new Set<string>();
  const snapshots = records.map((input) => {
    if (!input || input.schema_version !== 'NutritionReadModelV1') invalid('Expected versioned read models');
    const record = readNutritionRecord(input.record);
    if (record.user_id !== scope.user_id || !buckets.has(record.date)) invalid('Record is outside the requested user or date range');
    if (record.client_record_id !== null) {
      if (seen.has(record.client_record_id)) invalid('Duplicate record identity in the requested scope');
      seen.add(record.client_record_id);
    }
    buckets.get(record.date)!.push(record);
    return record;
  });
  const scopeComplete = scope.completeness === 'complete';
  const daily = dates.map((date): NutritionDayRead => {
    const items = buckets.get(date)!;
    const coverage = aggregateReadCoverage(items.map((record) => record.coverage));
    return {
      date, record_count: items.length, state: items.length ? 'recorded' : scopeComplete ? 'no_records' : 'not_loaded', coverage,
      nutrients: projectRecords(items, coverage, scopeComplete),
    };
  });
  const recorded = daily.filter((day) => day.state === 'recorded');
  const coverage = aggregateReadCoverage(recorded.map((day) => day.coverage), true);
  const nutrients = projectRecords(snapshots, coverage, scopeComplete);
  const averages = (getValue: (key: NutrientKey) => number | null): NutritionValues =>
    Object.fromEntries(NUTRIENT_KEYS.map((key) => {
      const value = getValue(key);
      const average = scopeComplete && recorded.length > 0 && value !== null ? value / recorded.length : null;
      if (average === 0 && value !== null && value > 0) invalid('Nutrition average is outside the supported numeric range');
      return [key, average];
    })) as NutritionValues;
  return {
    schema_version: 'NutritionReadSummaryV1', scope: { ...scope }, daily,
    summary: {
      recorded_days: recorded.length, calendar_days: dates.length, total_records: snapshots.length,
      coverage, nutrients,
      avg_known_sum: averages((key) => recorded.length ? coverage.nutrients[key].known_sum : null),
      avg_known_value: averages((key) => nutrients[key].known_value),
      avg_reported_value: averages((key) => nutrients[key].reported_value),
      avg_value: averages((key) => nutrients[key].value),
      aggregation_scope: 'recorded_days_in_requested_range',
    },
  };
}

export type NutritionGoalAssessment = {
  assessment: 'unknown' | 'known_excess' | 'within_limit' | 'target_met' | 'below_target';
  excess: number | null;
  remaining: number | null;
  shortfall: number | null;
};

/** Reference-nutrition comparison only; never a medical or food-safety verdict. */
export function evaluateNutritionGoal(
  row: NutritionNutrientRead, target: number, goal: 'upper_limit' | 'minimum_target',
): NutritionGoalAssessment {
  if (typeof target !== 'number' || !Number.isFinite(target) || target < 0 ||
      !['upper_limit', 'minimum_target'].includes(goal)) invalid('Expected a finite nonnegative nutrition target');
  const unknown: NutritionGoalAssessment = { assessment: 'unknown', excess: null, remaining: null, shortfall: null };
  if (!row.scope_complete || row.coverage.status === 'legacy_unknown' || row.coverage.eligible_items === 0) return unknown;
  if (goal === 'upper_limit') {
    if (row.lower_bound !== null && row.lower_bound > target) {
      return { assessment: 'known_excess', excess: row.lower_bound - target, remaining: null, shortfall: null };
    }
    if (row.value !== null) return { assessment: 'within_limit', excess: 0, remaining: target - row.value, shortfall: null };
    return unknown;
  }
  if (row.value === null) return unknown;
  return row.value >= target
    ? { assessment: 'target_met', excess: null, remaining: null, shortfall: 0 }
    : { assessment: 'below_target', excess: null, remaining: null, shortfall: target - row.value };
}
