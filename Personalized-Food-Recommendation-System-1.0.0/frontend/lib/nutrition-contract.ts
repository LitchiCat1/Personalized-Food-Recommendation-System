import type {
  DietaryRecord, HistoryDay, MealNutrientLimits, NutritionGoalTypes,
  NutritionTargetBasis, NutritionTargets,
} from './api';

export type NutrientKey = keyof NutritionTargets;
export type NutritionValues = Record<NutrientKey, number | null>;
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };
export type PortionSource = 'unknown' | 'vision_estimate' | 'user_adjusted' | 'user_weighed' | 'label_weight' | 'assumed';
export type NutritionUnit = 'kcal' | 'kJ' | 'g' | 'mg' | 'ug';
export type NutritionBasis = 'per_100g' | 'per_serving' | 'per_100ml';

export type NutritionMeasurement = {
  value: string;
  unit: NutritionUnit;
  comparison: 'exact' | 'less_than';
  label_rounding: boolean | null;
  evidence?: JsonObject;
};

// These snapshots describe server output, never authority granted to a client.
export type NutritionProfile = {
  schema_version: 'NutritionProfileV1';
  basis: NutritionBasis;
  basis_weight_g: number;
  basis_volume_ml: number | null;
  source_basis: { basis: NutritionBasis; weight_g: string; volume_ml: string | null };
  source_nutrients: Record<NutrientKey, NutritionMeasurement | null>;
  source_details: JsonObject;
  units: Record<NutrientKey, 'kcal' | 'g' | 'mg'>;
  per_100g: NutritionValues;
  upper_bounds_per_100g: NutritionValues;
  bound_comparison: 'less_than';
  missing_nutrition_fields: NutrientKey[];
  bounded_nutrition_fields: NutrientKey[];
  has_required_point_values: boolean;
  nutrition_status: 'complete' | 'partial' | 'unknown';
  validation_warnings: string[];
};

export type NutritionPortion = {
  weight_g: number | null;
  portion_source: PortionSource;
  values: NutritionValues;
  upper_bounds: NutritionValues;
  bound_comparison: 'less_than';
  missing_nutrition_fields: NutrientKey[];
};

export type NutrientCoverage = {
  known_sum: number;
  known_items: number;
  eligible_items: number;
  unresolved_items: number;
  bounded_items: number;
  known_bounds_sum: number;
  total_upper_bound: number | null;
  upper_bound_comparison: 'less_than' | null;
  status: 'complete' | 'partial' | 'unknown' | 'legacy_unknown';
  legacy_items?: number;
};

export type NutritionCoverage = {
  schema_version: 'NutritionCoverageV1';
  nutrients: Record<NutrientKey, NutrientCoverage>;
  included_item_ids?: string[];
  excluded_item_ids?: string[];
};

export type NutritionContextInput = { scan_id?: string; recognition_context?: JsonObject };
export type NutritionContext = NutritionContextInput & {
  contract_version: 2;
  revision: number;
  coverage: NutritionCoverage;
  unresolved_item_ids: string[];
  visual_completeness: 'not_verified';
  recognition_context_authority: 'client_supplied';
  medical_risk?: JsonObject & {
    is_safe?: boolean | null;
    assessment_scope?: 'reference_nutrition_only';
    assessment_status?: 'known_excess' | 'known_risk' | 'unknown' | 'within_reference_limits';
  };
};

type FoodInclusion = { included?: true; exclusion_reason?: null } |
  { included: false; exclusion_reason: 'not_consumed' };
type NutritionFoodIdentity = {
  item_id: string;
  name: string;
  weight_g: number | null;
  portion_source: PortionSource;
};
export type ManualNutritionMeasurement = Omit<NutritionMeasurement, 'value' | 'label_rounding'> & {
  value: number | string;
  label_rounding?: boolean | null;
};
export type ManualNutritionValues = Record<NutrientKey, number | ManualNutritionMeasurement | null>;

// Existing items reuse server snapshots by ID; requests never upload snapshots.
export type NutritionFoodInputV2 = NutritionFoodIdentity & FoodInclusion & {
  nutrition_profile?: never;
  source?: never;
} & (
  { food_key: string; user_entered_nutrients?: never } |
  { food_key?: never; user_entered_nutrients: ManualNutritionValues; is_fried?: boolean } |
  { food_key?: never; user_entered_nutrients?: never }
);

export type NutritionFoodSnapshotV2 = NutritionFoodIdentity & NutritionValues & {
  included: boolean;
  exclusion_reason: 'not_consumed' | null;
  nutrition_profile: NutritionProfile | null;
  original_nutrition_profile?: NutritionProfile | null;
  original_food_identity?: JsonObject;
  food_key?: string;
  nutrition_intake: NutritionPortion;
  missing_nutrition_fields: NutrientKey[];
  source: string;
  is_fried: boolean;
  allergens: string[];
  gi: string | null;
};

export type NutritionRecordCreateV2 = {
  nutrition_contract_version: 2;
  user_id: string;
  client_record_id?: string;
  timestamp?: string;
  meal_type?: string;
  source?: 'camera' | 'manual' | 'nutrition-label';
  foods: NutritionFoodInputV2[];
  nutrition_context?: NutritionContextInput;
};
export type NutritionRecordPatchV2 = {
  nutrition_contract_version: 2;
  base_revision: number;
  foods: NutritionFoodInputV2[];
};
export type NutritionRecordPreviewV2 = NutritionRecordCreateV2 & { base_revision?: number };
export type NutritionRecordCanonicalV2 = {
  nutrition_contract_version: 2;
  foods: NutritionFoodSnapshotV2[];
  nutrition_context: NutritionContext;
  contains_fried_food: boolean;
} & { [K in NutrientKey as `total_${K}`]: number };
export type NutritionRecordV2 = NutritionRecordCanonicalV2 & {
  user_id: string;
  client_record_id: string;
  timestamp: string;
  meal_type?: string;
  source?: string;
};
export type LegacyNutritionRecord = DietaryRecord & {
  nutrition_contract_version?: 1;
  nutrition_context?: { status: 'legacy_unknown' };
};
export type VersionedNutritionRecord = LegacyNutritionRecord | NutritionRecordV2;
export type NutritionRecordsResponseV2 = {
  records: VersionedNutritionRecord[];
  count: number;
  nutrition_targets?: NutritionTargets;
  nutrition_goal_types?: NutritionGoalTypes;
  nutrition_target_basis?: NutritionTargetBasis;
  meal_nutrient_limits?: MealNutrientLimits;
};
export type NutritionHistoryResponseV2 = {
  nutrition_contract_version: 2;
  user_id: string;
  days: number;
  daily: (HistoryDay & { nutrition_coverage: NutritionCoverage })[];
  summary: {
    nutrition_coverage: NutritionCoverage;
    avg_known_sum: NutritionValues;
    aggregation_scope: 'recorded_days_in_requested_range';
    recorded_days: number;
    total_records: number;
    avg_records_per_day: number;
  } & Partial<{ [K in NutrientKey as `avg_${K}`]: number }>;
};
