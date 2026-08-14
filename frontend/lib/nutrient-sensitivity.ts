import type { MedicalConditionRule } from '@/lib/api';

export type TrackedNutrientKey = 'protein' | 'carbs' | 'sugar' | 'fat' | 'saturated_fat' | 'trans_fat' | 'sodium' | 'fiber' | 'calcium' | 'iron';

export type NutrientSensitivityMap = Record<TrackedNutrientKey, string[]>;

type SensitivityRule = Pick<MedicalConditionRule, 'id' | 'condition' | 'label_zh' | 'aliases' | 'risk_nutrients'>;

const TRACKED_NUTRIENTS = new Set<TrackedNutrientKey>(['protein', 'carbs', 'sugar', 'fat', 'saturated_fat', 'trans_fat', 'sodium', 'fiber', 'calcium', 'iron']);

const FALLBACK_RULES: SensitivityRule[] = [
  {
    id: 'diabetes',
    condition: 'diabetes',
    label_zh: '糖尿病',
    aliases: ['糖尿病', '血糖管理', 'diabetes'],
    risk_nutrients: {
      carbs: { label_zh: '碳水化合物' },
      sugar: { label_zh: '精緻糖' },
    },
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
      calcium: { label_zh: '鈣' },
    },
  },
  {
    id: 'gout',
    condition: 'gout',
    label_zh: '痛風',
    aliases: ['痛風', '高尿酸', '尿酸管理', 'gout'],
    risk_nutrients: { sugar: { label_zh: '精緻糖' } },
  },
  {
    id: 'hyperlipidemia',
    condition: 'hyperlipidemia',
    label_zh: '高血脂',
    aliases: ['高血脂', '膽固醇', '脂質管理', 'hyperlipidemia'],
    risk_nutrients: {
      fat: { label_zh: '脂肪' },
      saturated_fat: { label_zh: '飽和脂肪' },
      trans_fat: { label_zh: '反式脂肪' },
    },
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
    sugar: [],
    fat: [],
    saturated_fat: [],
    trans_fat: [],
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
      const normalizedNutrient = nutrient === 'refined_sugar' ? 'sugar' : nutrient;
      if (!TRACKED_NUTRIENTS.has(normalizedNutrient as TrackedNutrientKey)) return;

      const nutrientKey = normalizedNutrient as TrackedNutrientKey;
      if (!result[nutrientKey].includes(conditionLabel)) {
        result[nutrientKey].push(conditionLabel);
      }
    });
  });

  return result;
}
