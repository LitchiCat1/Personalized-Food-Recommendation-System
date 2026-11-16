import type { NutrientKey, NutritionCoverage, NutritionHistoryResponseV2, NutritionValues } from './nutrition-contract';
import { NUTRIENT_KEYS, roundNutritionMean } from './nutrition-calculation';
import { aggregateReadCoverage } from './nutrition-read-aggregation';
import { NutritionReadError, parseNutritionDate, projectNutritionNutrient } from './nutrition-read-model';
import type { NutritionNutrientRead } from './nutrition-read-model';
import { assertNutritionCoverage } from './nutrition-response-validation';

function invalid(): never {
  throw new NutritionReadError('invalid_read_model', 'History does not match its declared nutrition scope');
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function sameNumber(value: unknown, expected: number | null): boolean {
  return value === expected || (typeof value === 'number' && expected !== null && Number.isFinite(value)
    && Math.abs(value - expected) <= Math.max(Math.abs(value), expected) * Number.EPSILON * 8);
}

function sameCoverage(actual: NutritionCoverage, expected: NutritionCoverage): boolean {
  return NUTRIENT_KEYS.every((key) => {
    const row = actual.nutrients[key];
    const other = expected.nutrients[key];
    return row.status === other.status && row.upper_bound_comparison === other.upper_bound_comparison
      && ['known_items', 'eligible_items', 'unresolved_items', 'bounded_items'].every((field) =>
        row[field as keyof typeof row] === other[field as keyof typeof other])
      && (row.legacy_items ?? 0) === (other.legacy_items ?? 0)
      && sameNumber(row.known_sum, other.known_sum) && sameNumber(row.known_bounds_sum, other.known_bounds_sum)
      && sameNumber(row.total_upper_bound, other.total_upper_bound);
  });
}

export function assertNutritionHistoryResponse(value: unknown): asserts value is NutritionHistoryResponseV2 {
  if (!object(value) || value.nutrition_contract_version !== 2 || typeof value.user_id !== 'string'
    || !value.user_id.trim() || !count(value.days) || value.days < 1 || value.days > 365
    || !Array.isArray(value.daily) || value.daily.length > value.days || !object(value.summary)) invalid();
  const dates = new Set<string>();
  const coverages: NutritionCoverage[] = [];
  let totalRecords = 0;
  for (const day of value.daily) {
    if (!object(day) || !count(day.record_count) || day.record_count < 1) invalid();
    const date = parseNutritionDate(day.date);
    if (dates.has(date)) invalid();
    dates.add(date);
    assertNutritionCoverage(day.nutrition_coverage);
    const dayCoverage = day.nutrition_coverage;
    if (!NUTRIENT_KEYS.every((key) => sameNumber(day[key], dayCoverage.nutrients[key].known_sum))) invalid();
    totalRecords += day.record_count;
    if (!Number.isSafeInteger(totalRecords)) invalid();
    coverages.push(day.nutrition_coverage);
  }
  if (dates.size) {
    const sorted = [...dates].sort();
    const span = (Date.parse(`${sorted.at(-1)}T00:00:00Z`) - Date.parse(`${sorted[0]}T00:00:00Z`)) / 86_400_000;
    if (span >= value.days) invalid();
  }
  const summary = value.summary;
  if (summary.aggregation_scope !== 'recorded_days_in_requested_range' || summary.recorded_days !== value.daily.length
    || summary.total_records !== totalRecords || !object(summary.avg_known_sum)) invalid();
  assertNutritionCoverage(summary.nutrition_coverage, { allowIncompleteScope: true });
  const coverage = aggregateReadCoverage(coverages, true);
  if (!sameCoverage(summary.nutrition_coverage, coverage)
    || !sameNumber(summary.avg_records_per_day, value.daily.length ? roundNutritionMean(totalRecords, value.daily.length) : 0)) invalid();
  for (const key of NUTRIENT_KEYS) {
    const average = value.daily.length ? roundNutritionMean(coverage.nutrients[key].known_sum, value.daily.length) : null;
    if (!sameNumber(summary.avg_known_sum[key], average)) invalid();
    // Legacy averages depend on Python's float summation implementation. They
    // are schema-checked only and never consumed by this read model.
    const compatibilityAverage = summary[`avg_${key}`];
    if (value.daily.length && (typeof compatibilityAverage !== 'number'
      || !Number.isFinite(compatibilityAverage) || compatibilityAverage < 0)) invalid();
    if (!value.daily.length && summary[`avg_${key}`] !== undefined) invalid();
  }
}

export type NutritionHistoryReadModel = {
  schema_version: 'NutritionHistoryReadModelV1';
  user_id: string;
  days: number;
  aggregation_scope: 'recorded_days_in_requested_range';
  daily: {
    date: string;
    record_count: number;
    coverage: NutritionCoverage;
    nutrients: Record<NutrientKey, NutritionNutrientRead>;
  }[];
  summary: {
    recorded_days: number;
    total_records: number;
    coverage: NutritionCoverage;
    nutrients: Record<NutrientKey, NutritionNutrientRead>;
    avg_known_sum: NutritionValues;
    avg_value: NutritionValues;
  };
};

function projectCoverage(coverage: NutritionCoverage): Record<NutrientKey, NutritionNutrientRead> {
  return Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, projectNutritionNutrient(coverage.nutrients[key])])) as Record<NutrientKey, NutritionNutrientRead>;
}

export function readNutritionHistory(value: unknown): NutritionHistoryReadModel {
  assertNutritionHistoryResponse(value);
  const history = JSON.parse(JSON.stringify(value)) as NutritionHistoryResponseV2;
  const coverage = history.summary.nutrition_coverage;
  return {
    schema_version: 'NutritionHistoryReadModelV1', user_id: history.user_id, days: history.days,
    aggregation_scope: history.summary.aggregation_scope,
    daily: history.daily.map((day) => ({
      date: day.date, record_count: day.record_count!, coverage: day.nutrition_coverage,
      nutrients: projectCoverage(day.nutrition_coverage),
    })),
    summary: {
      recorded_days: history.summary.recorded_days, total_records: history.summary.total_records,
      coverage, nutrients: projectCoverage(coverage), avg_known_sum: history.summary.avg_known_sum,
      avg_value: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key,
        coverage.nutrients[key].status === 'complete' ? history.summary.avg_known_sum[key] : null,
      ])) as NutritionValues,
    },
  };
}
