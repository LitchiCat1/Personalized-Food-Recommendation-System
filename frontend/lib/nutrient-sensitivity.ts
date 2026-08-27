import type { MedicalConditionRule } from '@/lib/api';

export type TrackedNutrientKey = 'protein' | 'carbs' | 'fat' | 'sodium' | 'fiber' | 'calcium' | 'iron';

export type NutrientSensitivityMap = Record<TrackedNutrientKey, string[]>;

type SensitivityRule = Pick<MedicalConditionRule, 'id' | 'condition' | 'label_zh' | 'aliases' | 'risk_nutrients'>;

const TRACKED_NUTRIENTS = new Set<TrackedNutrientKey>(['protein', 'carbs', 'fat', 'sodium', 'fiber', 'calcium', 'iron']);

export type DailyNutritionTargets = {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
  fiber: number;
  calcium: number;
  iron: number;
};

export const BASE_DAILY_TARGETS: DailyNutritionTargets = {
  calories: 2100,
  protein: 130,
  carbs: 250,
  fat: 70,
  sodium: 2000,
  fiber: 25,
  calcium: 1000,
  iron: 15,
};

export function getDiseaseAdjustedTargets(
  healthConditions: string[],
  baseCalorieTarget: number = 2100
): DailyNutritionTargets {
  const targets = { ...BASE_DAILY_TARGETS, calories: baseCalorieTarget };
  const normalized = healthConditions.map((c) => c.toLowerCase().trim());

  if (normalized.some((c) => c.includes('hypertension') || c.includes('高血壓'))) {
    targets.sodium = Math.min(targets.sodium, 1800);
  }
  if (normalized.some((c) => c.includes('diabetes') || c.includes('糖尿病'))) {
    targets.carbs = Math.min(targets.carbs, 180);
    targets.fiber = Math.max(targets.fiber, 30);
  }
  if (normalized.some((c) => c.includes('kidney') || c.includes('腎臟病'))) {
    targets.protein = Math.min(targets.protein, 50);
    targets.sodium = Math.min(targets.sodium, 1500);
  }
  if (normalized.some((c) => c.includes('hyperlipidemia') || c.includes('高血脂'))) {
    targets.fat = Math.min(targets.fat, 45);
  }
  if (normalized.some((c) => c.includes('gout') || c.includes('痛風'))) {
    targets.sodium = Math.min(targets.sodium, 1800);
  }
  if (normalized.some((c) => c.includes('osteoporosis') || c.includes('骨質疏鬆'))) {
    targets.calcium = Math.max(targets.calcium, 1200);
  }
  if (normalized.some((c) => c.includes('anemia') || c.includes('貧血'))) {
    targets.iron = Math.max(targets.iron, 20);
  }

  return targets;
}

const FALLBACK_RULES: SensitivityRule[] = [
  {
    id: 'diabetes',
    condition: 'diabetes',
    label_zh: '糖尿病',
    aliases: ['糖尿病', '血糖管理', 'diabetes'],
    risk_nutrients: { carbs: { label_zh: '碳水化合物' }, fiber: { label_zh: '膳食纖維' } },
  },
  {
    id: 'hypertension',
    condition: 'hypertension',
    label_zh: '高血壓',
    aliases: ['高血壓', '鈉控制', 'hypertension'],
    risk_nutrients: { sodium: { label_zh: '鈉' } },
  },
  {
    id: 'kidney_disease',
    condition: 'kidney_disease',
    label_zh: '慢性腎臟病',
    aliases: ['慢性腎臟病', '腎臟病', '腎臟照護', 'kidney', 'ckd'],
    risk_nutrients: {
      sodium: { label_zh: '鈉' },
      protein: { label_zh: '蛋白質' },
    },
  },
  {
    id: 'gout',
    condition: 'gout',
    label_zh: '痛風',
    aliases: ['痛風', '高尿酸', '尿酸管理', 'gout'],
    risk_nutrients: { sugar: { label_zh: '糖' } },
  },
  {
    id: 'hyperlipidemia',
    condition: 'hyperlipidemia',
    label_zh: '高血脂',
    aliases: ['高血脂', '膽固醇', '脂質管理', 'hyperlipidemia'],
    risk_nutrients: { fat: { label_zh: '脂肪' } },
  },
  {
    id: 'osteoporosis',
    condition: 'osteoporosis',
    label_zh: '骨質疏鬆',
    aliases: ['骨質疏鬆', '骨骼健康', 'osteoporosis'],
    risk_nutrients: { calcium: { label_zh: '鈣' } },
  },
  {
    id: 'anemia',
    condition: 'anemia',
    label_zh: '貧血',
    aliases: ['貧血', '缺鐵', 'anemia'],
    risk_nutrients: { iron: { label_zh: '鐵' } },
  },
];

function normalizeCondition(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function matchesCondition(rule: SensitivityRule, condition: string): boolean {
  const normalized = normalizeCondition(condition);
  return [rule.id, rule.condition, rule.label_zh, ...rule.aliases]
    .map(normalizeCondition)
    .includes(normalized);
}

function getConditionLabel(rule: SensitivityRule): string {
  return rule.label_zh.split('/')[0].trim();
}

export function buildNutrientSensitivityMap(
  healthConditions: string[],
  medicalRules: MedicalConditionRule[] = []
): NutrientSensitivityMap {
  const result: NutrientSensitivityMap = {
    protein: [],
    carbs: [],
    fat: [],
    sodium: [],
    fiber: [],
    calcium: [],
    iron: [],
  };
  const rules: SensitivityRule[] = [
    ...medicalRules,
    ...FALLBACK_RULES.filter((fallback) => !medicalRules.some((rule) => rule.id === fallback.id)),
  ];

  healthConditions.forEach((condition) => {
    const rule = rules.find((candidate) => matchesCondition(candidate, condition));
    if (!rule) return;

    const conditionLabel = getConditionLabel(rule);
    Object.keys(rule.risk_nutrients).forEach((nutrient) => {
      if (!TRACKED_NUTRIENTS.has(nutrient as TrackedNutrientKey)) return;

      const nutrientKey = nutrient as TrackedNutrientKey;
      if (!result[nutrientKey].includes(conditionLabel)) {
        result[nutrientKey].push(conditionLabel);
      }
    });
  });

  return result;
}
