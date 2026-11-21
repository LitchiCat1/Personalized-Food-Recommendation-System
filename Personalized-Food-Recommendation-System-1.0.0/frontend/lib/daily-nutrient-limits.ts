export type DailyLimitNutrient = 'carbs' | 'sugar' | 'fat' | 'saturated_fat' | 'protein' | 'sodium';

export type DailyLimitSetting = {
  unit: 'g' | 'mg';
  min: number;
  max: number;
  step: number;
  precision: number;
  default_value: number;
  value: number;
  source: 'default' | 'custom';
  active: boolean;
  effective_value: number;
  effective_condition_ids: string[];
};

export type ConditionDailyLimits = Partial<Record<DailyLimitNutrient, DailyLimitSetting>>;
export type ConditionDailyLimitOverrides = Partial<Record<DailyLimitNutrient, number>>;
export type DailyLimitOverrides = Record<string, ConditionDailyLimitOverrides>;
export type DailyLimitSettings = Record<string, ConditionDailyLimits>;

export type DailyLimitDraft = Partial<Record<DailyLimitNutrient, string | null>>;

export function parseDailyLimitInput(raw: string, setting: DailyLimitSetting): number | null {
  const text = raw.trim();
  if (!/^\d+(?:\.\d+)?$/.test(text) || (text.split('.')[1]?.length ?? 0) > setting.precision) return null;
  const value = Number(text);
  return Number.isFinite(value) && value >= setting.min && value <= setting.max ? value : null;
}

export function stepDailyLimitValue(raw: string, direction: -1 | 1, setting: DailyLimitSetting): string | null {
  const value = parseDailyLimitInput(raw, setting);
  if (value === null) return null;
  const scale = 10 ** setting.precision;
  const units = Math.round(value * scale) + direction * Math.round(setting.step * scale);
  const next = Math.max(setting.min, Math.min(setting.max, units / scale));
  return String(next);
}

export function resolveDailyLimitDraft(draft: DailyLimitDraft, settings: ConditionDailyLimits): ConditionDailyLimitOverrides | null {
  const overrides: ConditionDailyLimitOverrides = {};
  for (const nutrient of Object.keys(settings) as DailyLimitNutrient[]) {
    const setting = settings[nutrient];
    if (!setting) continue;
    const raw = draft[nutrient];
    if (raw === null) continue;
    if (raw === undefined) {
      if (setting.source === 'custom') overrides[nutrient] = setting.value;
    } else {
      const value = parseDailyLimitInput(raw, setting);
      if (value === null) return null;
      overrides[nutrient] = value;
    }
  }
  return overrides;
}
