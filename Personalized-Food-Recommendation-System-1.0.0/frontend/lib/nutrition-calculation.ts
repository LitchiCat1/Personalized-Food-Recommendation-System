import type {
  NutrientKey,
  NutritionCoverage,
  NutritionPortion,
  NutritionProfile,
  PortionSource,
} from './nutrition-contract';

export const NUTRIENT_KEYS = [
  'calories', 'protein', 'carbs', 'sugar', 'fat',
  'saturated_fat', 'trans_fat', 'fiber', 'sodium',
] as const satisfies readonly NutrientKey[];

const PORTION_SOURCES = new Set<PortionSource>([
  'unknown', 'vision_estimate', 'user_adjusted', 'user_weighed', 'label_weight', 'assumed',
]);
const ZERO = BigInt(0);
const ONE = BigInt(1);
const TWO = BigInt(2);
const TEN = BigInt(10);
type Fraction = { numerator: bigint; denominator: bigint };
type NullableFractions = Record<NutrientKey, Fraction | null>;
const ZERO_FRACTION: Fraction = { numerator: ZERO, denominator: ONE };

export class NutritionCalculationError extends Error {
  readonly code: 'invalid_number' | 'numeric_range' | 'invalid_profile' | 'invalid_portion' | 'invalid_items';

  constructor(code: NutritionCalculationError['code'], message: string) {
    super(message);
    this.name = 'NutritionCalculationError';
    this.code = code;
  }
}

function gcd(left: bigint, right: bigint): bigint {
  while (right !== ZERO) [left, right] = [right, left % right];
  return left;
}

function fraction(numerator: bigint, denominator = ONE): Fraction {
  if (numerator === ZERO) return ZERO_FRACTION;
  const divisor = gcd(numerator, denominator);
  return { numerator: numerator / divisor, denominator: denominator / divisor };
}

function multiply(left: Fraction, right: Fraction): Fraction {
  return fraction(left.numerator * right.numerator, left.denominator * right.denominator);
}

function divide(left: Fraction, right: Fraction): Fraction {
  return fraction(left.numerator * right.denominator, left.denominator * right.numerator);
}

function add(left: Fraction, right: Fraction): Fraction {
  const divisor = gcd(left.denominator, right.denominator);
  return fraction(
    left.numerator * (right.denominator / divisor) + right.numerator * (left.denominator / divisor),
    left.denominator * (right.denominator / divisor),
  );
}

function roundQuotient(numerator: bigint, denominator: bigint): bigint {
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  const doubled = remainder * TWO;
  return quotient + (doubled > denominator || (doubled === denominator && quotient % TWO !== ZERO) ? ONE : ZERO);
}

// Round the final rational directly to an IEEE number. Converting its numerator
// and denominator separately can overflow even when their quotient is finite.
function numeric(value: Fraction | null): number | null {
  if (value === null) return null;
  const { numerator, denominator } = value;
  if (numerator === ZERO) return 0;
  let exponent = numerator.toString(2).length - denominator.toString(2).length;
  if (exponent >= 0
    ? numerator < (denominator << BigInt(exponent))
    : (numerator << BigInt(-exponent)) < denominator) exponent -= 1;
  let result: number;
  if (exponent < -1022) {
    const mantissa = roundQuotient(numerator << BigInt(1074), denominator);
    result = Number(mantissa) * Number.MIN_VALUE;
  } else {
    const shift = 52 - exponent;
    const mantissa = shift >= 0
      ? roundQuotient(numerator << BigInt(shift), denominator)
      : roundQuotient(numerator, denominator << BigInt(-shift));
    result = Number(mantissa) * (2 ** (exponent - 52));
  }
  if (!Number.isFinite(result) || result === 0) {
    throw new NutritionCalculationError('numeric_range', 'Nutrition calculation is outside the supported numeric range');
  }
  return result;
}

function decimal(value: unknown, positive = false, allowString = true): Fraction {
  if (typeof value !== 'number' && !(allowString && typeof value === 'string')) {
    throw new NutritionCalculationError('invalid_number', 'Expected a finite nonnegative decimal');
  }
  const text = String(value);
  if (text.length > 128 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(text)) {
    throw new NutritionCalculationError('invalid_number', 'Invalid decimal representation');
  }
  const [significand, exponentText = '0'] = text.toLowerCase().split('e');
  const [whole, digits = ''] = significand.split('.');
  const numerator = BigInt(whole + digits);
  if (numerator === ZERO) {
    if (positive) throw new NutritionCalculationError('invalid_number', 'Expected a positive number');
    return ZERO_FRACTION;
  }
  const exponent = Number(exponentText) - digits.length;
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1024) {
    throw new NutritionCalculationError('numeric_range', 'Decimal exponent is outside the supported range');
  }
  const result = exponent >= 0
    ? fraction(numerator * (TEN ** BigInt(exponent)))
    : fraction(numerator, TEN ** BigInt(-exponent));
  numeric(result);
  return result;
}

function nullableFractions(): NullableFractions {
  return Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, null])) as NullableFractions;
}

function sourceMeasurements(profile: NutritionProfile): { weight: Fraction; cells: NullableFractions; bounds: NullableFractions } {
  if (!profile || typeof profile !== 'object' || profile.schema_version !== 'NutritionProfileV1'
    || !profile.source_basis || typeof profile.source_basis !== 'object'
    || !profile.source_nutrients || typeof profile.source_nutrients !== 'object' || Array.isArray(profile.source_nutrients)) {
    throw new NutritionCalculationError('invalid_profile', 'Original nutrition cells and basis are required');
  }
  const basis = profile.source_basis;
  const weight = decimal(basis.weight_g, true);
  const volume = basis.volume_ml === null ? null : decimal(basis.volume_ml, true);
  const equals100 = (value: Fraction) => value.numerator === value.denominator * BigInt(100);
  if ((basis.basis === 'per_100g' && (!equals100(weight) || volume !== null))
    || (basis.basis === 'per_100ml' && (volume === null || !equals100(volume)))
    || !['per_100g', 'per_serving', 'per_100ml'].includes(basis.basis)) {
    throw new NutritionCalculationError('invalid_profile', 'Nutrition basis lacks an evidenced weight');
  }
  if (Object.keys(profile.source_nutrients).length !== NUTRIENT_KEYS.length
    || NUTRIENT_KEYS.some((key) => !Object.hasOwn(profile.source_nutrients, key))) {
    throw new NutritionCalculationError('invalid_profile', 'All nine nullable original cells are required');
  }
  const cells = nullableFractions();
  const bounds = nullableFractions();
  for (const key of NUTRIENT_KEYS) {
    const cell = profile.source_nutrients[key];
    if (cell === null) continue;
    if (!cell || (cell.comparison !== 'exact' && cell.comparison !== 'less_than')) {
      throw new NutritionCalculationError('invalid_profile', 'Unsupported nutrient comparison');
    }
    let value = decimal(cell.value, cell.comparison === 'less_than');
    if (key === 'calories') {
      if (cell.unit === 'kJ') value = multiply(value, fraction(BigInt(1000), BigInt(4184)));
      else if (cell.unit !== 'kcal') throw new NutritionCalculationError('invalid_profile', 'Unsupported energy unit');
    } else {
      const divisor = cell.unit === 'g' ? ONE : cell.unit === 'mg' ? BigInt(1000) : cell.unit === 'ug' ? BigInt(1000000) : null;
      if (!divisor) throw new NutritionCalculationError('invalid_profile', 'Unsupported nutrient mass unit');
      value = divide(value, fraction(divisor));
      if (key === 'sodium') value = multiply(value, fraction(BigInt(1000)));
    }
    (cell.comparison === 'exact' ? cells : bounds)[key] = value;
  }
  return { weight, cells, bounds };
}

function portionFractions(profile: NutritionProfile | null, weightG: number | null, portionSource: PortionSource) {
  if (!PORTION_SOURCES.has(portionSource)) {
    throw new NutritionCalculationError('invalid_portion', 'Unsupported portion source');
  }
  const source = profile === null ? null : sourceMeasurements(profile);
  const weight = weightG === null ? null : decimal(weightG, true, false);
  const cells = nullableFractions();
  const bounds = nullableFractions();
  if (source !== null && weight !== null) {
    const factor = divide(weight, source.weight);
    for (const key of NUTRIENT_KEYS) {
      cells[key] = source.cells[key] === null ? null : multiply(source.cells[key], factor);
      bounds[key] = source.bounds[key] === null ? null : multiply(source.bounds[key], factor);
      numeric(cells[key]);
      numeric(bounds[key]);
    }
  }
  return { cells, bounds };
}

/** Local preview only; the backend validates source authority and medical risk. */
export function calculateNutritionPortion(
  profile: NutritionProfile | null,
  weightG: number | null,
  portionSource: PortionSource = 'unknown',
): NutritionPortion {
  const { cells, bounds } = portionFractions(profile, weightG, portionSource);
  return {
    weight_g: weightG,
    portion_source: portionSource,
    values: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, numeric(cells[key])])) as NutritionPortion['values'],
    upper_bounds: Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, numeric(bounds[key])])) as NutritionPortion['upper_bounds'],
    bound_comparison: 'less_than',
    missing_nutrition_fields: NUTRIENT_KEYS.filter((key) => cells[key] === null),
  };
}

export type NutritionCoverageInput = {
  item_id: string;
  profile: NutritionProfile | null;
  weight_g: number | null;
  portion_source?: PortionSource;
  included?: boolean;
  exclusion_reason?: 'not_consumed' | null;
};

export function aggregateNutritionCoverage(items: NutritionCoverageInput[]): NutritionCoverage {
  if (!Array.isArray(items) || items.length > 10000) {
    throw new NutritionCalculationError('invalid_items', 'Expected a bounded item list');
  }
  const seen = new Set<string>();
  const included: NutritionCoverageInput[] = [];
  const excluded: string[] = [];
  for (const item of items) {
    if (!item || typeof item.item_id !== 'string' || !item.item_id.trim() || seen.has(item.item_id)
      || (item.included !== undefined && typeof item.included !== 'boolean')) {
      throw new NutritionCalculationError('invalid_items', 'Each item requires a unique ID and explicit inclusion state');
    }
    seen.add(item.item_id);
    if (item.included === false) {
      if (item.exclusion_reason !== 'not_consumed') {
        throw new NutritionCalculationError('invalid_items', 'Exclusion requires an explicit not_consumed decision');
      }
      excluded.push(item.item_id);
    } else included.push(item);
  }
  const totals = Object.fromEntries(NUTRIENT_KEYS.map((key) => [key, {
    sum: ZERO_FRACTION, bounds: ZERO_FRACTION, known: 0, bounded: 0,
  }])) as Record<NutrientKey, { sum: Fraction; bounds: Fraction; known: number; bounded: number }>;
  for (const item of included) {
    const portion = portionFractions(item.profile, item.weight_g, item.portion_source ?? 'unknown');
    for (const key of NUTRIENT_KEYS) {
      const row = totals[key];
      if (portion.cells[key] !== null) {
        row.sum = add(row.sum, portion.cells[key]);
        row.known += 1;
      }
      if (portion.bounds[key] !== null) {
        row.bounds = add(row.bounds, portion.bounds[key]);
        row.bounded += 1;
      }
    }
  }
  const denominator = included.length;
  const nutrients = Object.fromEntries(NUTRIENT_KEYS.map((key) => {
    const row = totals[key];
    const hasBound = row.bounded > 0 && row.known + row.bounded === denominator;
    return [key, {
      known_sum: numeric(row.sum), known_items: row.known, eligible_items: denominator,
      unresolved_items: denominator - row.known, bounded_items: row.bounded,
      known_bounds_sum: numeric(row.bounds),
      total_upper_bound: hasBound ? numeric(add(row.sum, row.bounds)) : null,
      upper_bound_comparison: hasBound ? 'less_than' : null,
      status: denominator > 0 && row.known === denominator ? 'complete' : row.known || row.bounded ? 'partial' : 'unknown',
    }];
  })) as NutritionCoverage['nutrients'];
  return {
    schema_version: 'NutritionCoverageV1', nutrients,
    included_item_ids: included.map((item) => item.item_id), excluded_item_ids: excluded,
  };
}

export function formatNutritionMeasurement(value: number | null, upperBound: number | null, unit = ''): string {
  for (const number of [value, upperBound]) {
    if (number !== null && (typeof number !== 'number' || !Number.isFinite(number) || number < 0)) {
      throw new NutritionCalculationError('invalid_number', 'Invalid display measurement');
    }
  }
  if ((value !== null && upperBound !== null) || upperBound === 0) {
    throw new NutritionCalculationError('invalid_profile', 'Point values and exclusive bounds must remain distinct');
  }
  const suffix = unit ? ` ${unit}` : '';
  if (value !== null) return `${value}${suffix}`;
  if (upperBound !== null) return `<${upperBound}${suffix}`;
  return '未知';
}
