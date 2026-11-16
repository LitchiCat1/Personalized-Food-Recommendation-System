import type {
  NutrientCoverage, NutrientKey, NutritionCoverage, VersionedNutritionRecord,
} from './nutrition-contract';
import { NUTRIENT_KEYS } from './nutrition-calculation';
import { assertNutritionCoverage, assertVersionedNutritionRecord } from './nutrition-response-validation';

export class NutritionReadError extends Error {
  readonly code: 'invalid_read_model' | 'invalid_date' | 'invalid_scope' | 'duplicate_record';

  constructor(code: NutritionReadError['code'], message: string) {
    super(message);
    this.name = 'NutritionReadError';
    this.code = code;
  }
}

export type NutritionNutrientRead = {
  coverage: NutrientCoverage;
  scope_complete: boolean;
  value: number | null;
  known_value: number | null;
  reported_value: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  upper_bound_comparison: 'less_than' | null;
};

export type NutritionRecordReadModel = {
  schema_version: 'NutritionReadModelV1';
  user_id: string;
  client_record_id: string | null;
  timestamp: string;
  date: string;
  contract_version: 1 | 2;
  coverage: NutritionCoverage;
  nutrients: Record<NutrientKey, NutritionNutrientRead>;
  record: VersionedNutritionRecord;
};

export function parseNutritionDate(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000')) {
    throw new NutritionReadError('invalid_date', 'Expected a calendar date');
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new NutritionReadError('invalid_date', 'Invalid calendar date');
  }
  return value;
}

export function projectNutritionNutrient(
  row: NutrientCoverage, reportedValue: number | null = null, scopeComplete = true,
): NutritionNutrientRead {
  const legacy = row.status === 'legacy_unknown';
  const known = !legacy && row.known_items > 0 ? row.known_sum : null;
  const complete = scopeComplete && row.status === 'complete';
  return {
    coverage: { ...row }, scope_complete: scopeComplete,
    value: complete ? row.known_sum : null,
    known_value: known,
    reported_value: reportedValue,
    lower_bound: scopeComplete ? known : null,
    upper_bound: scopeComplete && !legacy ? row.total_upper_bound : null,
    upper_bound_comparison: scopeComplete && !legacy ? row.upper_bound_comparison : null,
  };
}

function legacyCoverage(record: VersionedNutritionRecord): NutritionCoverage {
  const count = Math.max(1, record.foods?.length ?? 0);
  return {
    schema_version: 'NutritionCoverageV1',
    nutrients: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, {
      known_sum: record[`total_${key}`] ?? 0,
      known_items: 0, eligible_items: count, unresolved_items: count,
      bounded_items: 0, known_bounds_sum: 0, legacy_items: count,
      total_upper_bound: null, upper_bound_comparison: null, status: 'legacy_unknown',
    }])) as NutritionCoverage['nutrients'],
  };
}

export function readNutritionRecord(value: unknown): NutritionRecordReadModel {
  assertVersionedNutritionRecord(value);
  let record: VersionedNutritionRecord;
  try {
    record = JSON.parse(JSON.stringify(value)) as VersionedNutritionRecord;
  } catch {
    throw new NutritionReadError('invalid_read_model', 'Record snapshot is not JSON');
  }
  const version = record.nutrition_contract_version === 2 ? 2 : 1;
  const coverage = record.nutrition_contract_version === 2
    ? record.nutrition_context.coverage : legacyCoverage(record);
  assertNutritionCoverage(coverage);
  return {
    schema_version: 'NutritionReadModelV1', user_id: record.user_id,
    client_record_id: record.client_record_id ?? null,
    timestamp: record.timestamp,
    // The backend files records by the stored local date prefix, not UTC day.
    date: parseNutritionDate(record.timestamp.slice(0, 10)), contract_version: version,
    coverage,
    nutrients: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key,
      projectNutritionNutrient(coverage.nutrients[key], version === 1 ? record[`total_${key}`] ?? null : null),
    ])) as NutritionRecordReadModel['nutrients'],
    record,
  };
}
