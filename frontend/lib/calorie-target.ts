import type { NutritionTargetBasis } from '@/lib/api';
import { conditionLabels } from '@/lib/medical-labels';

/**
 * 每日熱量目標的說明文字。
 *
 * App 裡同時存在三個每日熱量：後端算的 TDEE、使用者在「編輯資料」填的
 * daily_calorie_target、以及疾病指引算出的臨床目標。先前這三個數字分散在
 * 首頁、趨勢、我的兩個分頁裡各自出現，彼此不一致又沒有任何說明——
 * 使用者改了「每日熱量」看到儲存成功，但畫面上沒有一個地方會變。
 *
 * 這裡只做一件事：把「現在生效的是哪個數字、為什麼」講成一句人話。
 */

const ACTIVITY_LABELS: [number, string][] = [
  [1.2, '久坐'],
  [1.375, '輕度活動'],
  [1.55, '中等活動'],
  [1.725, '高度活動'],
  [Number.POSITIVE_INFINITY, '極高活動'],
];

export function activityLabel(multiplier: number): string {
  const match = ACTIVITY_LABELS.find(([ceiling]) => multiplier <= ceiling);
  return match ? match[1] : '中等活動';
}

/** 主要說明：這個數字是怎麼算出來的。 */
export function describeCalorieTarget(basis: NutritionTargetBasis | null | undefined): string | null {
  if (!basis) return null;

  if (basis.source === 'user') {
    return '目前採用你在「編輯資料」填寫的每日熱量。你沒有勾選任何慢性疾病，所以不套用疾病指引的熱量上限。';
  }

  const conditions = conditionLabels(basis.conditions, '慢性疾病');
  const parts = [
    `依${conditions}的臨床指引計算：理想體重 ${basis.ideal_body_weight} kg × ${basis.kcal_per_kg} kcal（${activityLabel(basis.activity_multiplier)}${basis.is_overweight ? '，BMI 偏高再下調一級' : ''}）。`,
  ];

  if (basis.floored_at_bmr && basis.bmr) {
    parts.push(`算出來的數字低於你的基礎代謝率，已提高到 BMR ${basis.bmr.toLocaleString()} kcal。`);
  }

  return parts.join('');
}

/**
 * 次要說明：使用者自己填的那個數字現在的處境。
 *
 * 沒有這一句，「編輯資料」裡那個可以改、改了卻沒有任何效果的欄位就是個陷阱。
 */
export function describeUserTargetFallback(basis: NutritionTargetBasis | null | undefined): string | null {
  if (!basis || basis.source !== 'disease' || !basis.user_target) return null;
  return `你填的 ${basis.user_target.toLocaleString()} kcal 是沒有疾病條件時才會採用的基準值。`;
}

/** 熱量一律顯示整數：先前首頁同時出現「1,590 kcal」與「目標 1,589.5 kcal」。 */
export function formatCalories(value: number): string {
  return Math.round(value).toLocaleString();
}
