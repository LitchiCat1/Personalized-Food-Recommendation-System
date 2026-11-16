import type {
  NutritionCoverage, NutritionRecordCanonicalV2, NutritionRecordV2, VersionedNutritionRecord,
} from './nutrition-contract';
import { aggregateNutritionCoverage, calculateNutritionPortion, NUTRIENT_KEYS } from './nutrition-calculation';

export class NutritionApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requiredNutritionContractVersion: number | null;

  constructor(message: string, status: number, code: string, requiredVersion: number | null = null) {
    super(message);
    this.name = 'NutritionApiError';
    this.status = status;
    this.code = code;
    this.requiredNutritionContractVersion = requiredVersion;
  }
}

function incompatible(): never {
  throw new NutritionApiError('後端回傳的營養資料格式不相容', 200, 'invalid_response');
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function number(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function integer(value: unknown): value is number {
  return number(value) && Number.isSafeInteger(value);
}

function nonempty(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function timestamp(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?(?:Z|[+-](\d{2}):?(\d{2}))?)?$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, offsetHourText, offsetMinuteText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= monthDays[month - 1]
    && (hourText === undefined || (Number(hourText) < 24 && Number(minuteText) < 60 && Number(secondText ?? 0) < 60))
    && (offsetHourText === undefined || (Number(offsetHourText) < 24 && Number(offsetMinuteText) < 60));
}

function values(value: unknown): boolean {
  return object(value) && NUTRIENT_KEYS.every((key) => value[key] === null || number(value[key]));
}

function sameNumber(left: unknown, right: number | null): boolean {
  if (right === null) return left === null;
  return number(left) && (left === right || Math.abs(left - right) <= Math.max(left, right) * Number.EPSILON * 8);
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function sameList(left: unknown, right: string[]): boolean {
  return strings(left) && left.length === right.length && left.every((item, index) => item === right[index]);
}

export function assertNutritionCoverage(
  value: unknown,
  options: { allowIncompleteScope?: boolean } = {},
): asserts value is NutritionCoverage {
  if (!object(value) || value.schema_version !== 'NutritionCoverageV1' || !object(value.nutrients)) incompatible();
  let denominator: number | undefined;
  for (const key of NUTRIENT_KEYS) {
    const row = value.nutrients[key];
    if (!object(row) || !number(row.known_sum) || !number(row.known_bounds_sum) ||
        !['known_items', 'eligible_items', 'unresolved_items', 'bounded_items'].every((name) => integer(row[name])) ||
        (row.legacy_items !== undefined && !integer(row.legacy_items)) ||
        !['complete', 'partial', 'unknown', 'legacy_unknown'].includes(String(row.status)) ||
        !(row.total_upper_bound === null || number(row.total_upper_bound)) ||
        row.upper_bound_comparison !== (row.total_upper_bound === null ? null : 'less_than')) incompatible();
    if ((row.known_items as number) + (row.unresolved_items as number) !== row.eligible_items ||
        (row.bounded_items as number) + ((row.legacy_items as number | undefined) ?? 0) > (row.unresolved_items as number) ||
        (denominator !== undefined && row.eligible_items !== denominator)) incompatible();
    denominator = row.eligible_items as number;
    const hasLegacy = typeof row.legacy_items === 'number' && row.legacy_items > 0;
    const status = hasLegacy ? 'legacy_unknown' : row.eligible_items !== 0 && row.known_items === row.eligible_items
      ? 'complete' : row.known_items || row.bounded_items ? 'partial' : 'unknown';
    const hasBound = !hasLegacy && (row.bounded_items as number) > 0 &&
      (row.known_items as number) + (row.bounded_items as number) === row.eligible_items;
    const upper = hasBound ? (row.known_sum as number) + (row.known_bounds_sum as number) : null;
    // A history scope may contain recorded days whose items were all excluded.
    // Its adapter must verify the exact daily merge before using these totals.
    const conservativeStatus = options.allowIncompleteScope && status === 'complete' && row.status === 'partial';
    const conservativeBound = options.allowIncompleteScope && upper !== null && row.total_upper_bound === null;
    if ((row.status !== status && !conservativeStatus) || (!sameNumber(row.total_upper_bound, upper) && !conservativeBound) ||
        (!row.bounded_items && row.known_bounds_sum !== 0) ||
        ((row.bounded_items as number) > 0 && row.known_bounds_sum === 0) ||
        (!hasLegacy && row.known_items === 0 && row.known_sum !== 0) ||
        (row.total_upper_bound !== null && row.total_upper_bound === 0)) incompatible();
  }
  const seen = new Set<string>();
  for (const key of ['included_item_ids', 'excluded_item_ids'] as const) {
    const ids = value[key];
    if (ids === undefined) continue;
    if (!Array.isArray(ids)) incompatible();
    for (const id of ids) {
      if (!nonempty(id) || seen.has(id)) incompatible();
      seen.add(id);
    }
    if (key === 'included_item_ids' && ids.length !== denominator) incompatible();
  }
}

export function assertNutritionCanonicalV2(value: unknown): asserts value is NutritionRecordCanonicalV2 {
  if (!object(value) || value.nutrition_contract_version !== 2 || !Array.isArray(value.foods) ||
      value.foods.length === 0 || value.foods.length > 200 || typeof value.contains_fried_food !== 'boolean' ||
      !object(value.nutrition_context)) incompatible();
  const context = value.nutrition_context;
  if (context.contract_version !== 2 || !integer(context.revision) ||
      context.visual_completeness !== 'not_verified' ||
      context.recognition_context_authority !== 'client_supplied' ||
      !strings(context.unresolved_item_ids)) incompatible();
  assertNutritionCoverage(context.coverage);
  const seen = new Set<string>();
  for (const food of value.foods) {
    if (!object(food) || !nonempty(food.item_id) || seen.has(food.item_id) ||
        !nonempty(food.name) || typeof food.included !== 'boolean' ||
        (food.included === false && food.exclusion_reason !== 'not_consumed') ||
        !(food.weight_g === null || (number(food.weight_g) && food.weight_g > 0)) ||
        !['unknown', 'vision_estimate', 'user_adjusted', 'user_weighed', 'label_weight', 'assumed'].includes(String(food.portion_source)) ||
        typeof food.source !== 'string' || typeof food.is_fried !== 'boolean' || !strings(food.allergens) ||
        !(food.gi === null || typeof food.gi === 'string') || !strings(food.missing_nutrition_fields) ||
        !values(food) || !object(food.nutrition_intake) ||
        !values(food.nutrition_intake.values) || !values(food.nutrition_intake.upper_bounds) ||
        food.nutrition_intake.bound_comparison !== 'less_than' ||
        food.nutrition_intake.weight_g !== food.weight_g || food.nutrition_intake.portion_source !== food.portion_source ||
        !(food.nutrition_profile === null ||
          (object(food.nutrition_profile) && food.nutrition_profile.schema_version === 'NutritionProfileV1' &&
           object(food.nutrition_profile.source_basis) && object(food.nutrition_profile.source_nutrients)))) incompatible();
    seen.add(food.item_id);
  }
  // Original cells validate the snapshot's arithmetic, never its source authority.
  try {
    const snapshot = value as unknown as NutritionRecordCanonicalV2;
    const expected = aggregateNutritionCoverage(snapshot.foods.map((food) => ({ ...food, profile: food.nutrition_profile })));
    for (const food of snapshot.foods) {
      const portion = calculateNutritionPortion(food.nutrition_profile, food.weight_g, food.portion_source);
      for (const key of NUTRIENT_KEYS) {
        if (!sameNumber(food[key], portion.values[key]) || !sameNumber(food.nutrition_intake.values[key], portion.values[key]) ||
            !sameNumber(food.nutrition_intake.upper_bounds[key], portion.upper_bounds[key])) incompatible();
      }
      if (!sameList(food.missing_nutrition_fields, portion.missing_nutrition_fields) ||
          !sameList(food.nutrition_intake.missing_nutrition_fields, portion.missing_nutrition_fields)) incompatible();
    }
    const coverage = snapshot.nutrition_context.coverage;
    if (!sameList(coverage.included_item_ids, expected.included_item_ids ?? []) ||
        !sameList(coverage.excluded_item_ids, expected.excluded_item_ids ?? []) ||
        !sameList(context.unresolved_item_ids, snapshot.foods.filter((food) => food.included && food.missing_nutrition_fields.length > 0).map((food) => food.item_id))) incompatible();
    for (const key of NUTRIENT_KEYS) {
      const actual = coverage.nutrients[key];
      const row = expected.nutrients[key];
      if (actual.status !== row.status || actual.known_items !== row.known_items || actual.eligible_items !== row.eligible_items ||
          actual.bounded_items !== row.bounded_items || !sameNumber(actual.known_sum, row.known_sum) ||
          !sameNumber(actual.known_bounds_sum, row.known_bounds_sum) || !sameNumber(actual.total_upper_bound, row.total_upper_bound) ||
          !sameNumber(value[`total_${key}`], row.known_sum)) incompatible();
    }
  } catch { incompatible(); }
}

export function assertNutritionSavedRecordV2(value: unknown): asserts value is NutritionRecordV2 {
  assertNutritionCanonicalV2(value);
  const record = value as unknown as Record<string, unknown>;
  if (!nonempty(record.user_id) || !nonempty(record.client_record_id) || !timestamp(record.timestamp)) incompatible();
}

export function assertVersionedNutritionRecord(value: unknown): asserts value is VersionedNutritionRecord {
  if (!object(value)) incompatible();
  if (value.nutrition_contract_version === 2) {
    assertNutritionSavedRecordV2(value);
    return;
  }
  if ((value.nutrition_contract_version !== undefined && value.nutrition_contract_version !== 1) ||
      !nonempty(value.user_id) || !timestamp(value.timestamp) ||
      (value.client_record_id !== undefined && !nonempty(value.client_record_id)) ||
      (value.foods !== undefined && !Array.isArray(value.foods)) ||
      (value.nutrition_context !== undefined &&
        (!object(value.nutrition_context) || value.nutrition_context.status !== 'legacy_unknown'))) incompatible();
  for (const key of NUTRIENT_KEYS) {
    const total = value[`total_${key}`];
    if (total !== undefined && !number(total)) incompatible();
  }
  for (const food of (value.foods ?? []) as unknown[]) {
    if (!object(food)) incompatible();
    for (const key of NUTRIENT_KEYS) {
      if (food[key] !== undefined && !number(food[key])) incompatible();
    }
  }
}
