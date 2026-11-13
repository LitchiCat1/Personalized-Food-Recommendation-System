import type { HistoryDay, HistoryResponse } from '@/lib/api';

/**
 * 「每日熱量追蹤」的達標區間：目標的 85%–115%。
 *
 * 之前「近期重點」另外用 75% 判斷「接近個人目標」，同一頁會出現
 * 1,240 / 1,648 kcal（75.2%）在重點裡算「接近目標」、在熱量追蹤裡卻
 * 不算達標的矛盾。兩邊都要用這裡的常數。
 */
export const CALORIE_GOAL_LOWER_RATIO = 0.85;
export const CALORIE_GOAL_UPPER_RATIO = 1.15;

export type CalorieStatus = 'low' | 'on-target' | 'high';

export function classifyCalories(calories: number, target: number): CalorieStatus {
  if (calories < target * CALORIE_GOAL_LOWER_RATIO) return 'low';
  if (calories > target * CALORIE_GOAL_UPPER_RATIO) return 'high';
  return 'on-target';
}

/** 鈉超過每日上限的日子；頁面上的「鈉超標」天數和重點文字共用這個判斷。 */
export function findSodiumOverDays(daily: HistoryDay[], sodiumTarget: number): HistoryDay[] {
  return daily.filter((day) => day.sodium > sodiumTarget);
}

export function buildTrendInsights(
  summary: HistoryResponse['summary'],
  daily: HistoryDay[],
  calorieTarget: number,
  sodiumTarget: number
): string[] {
  if (daily.length === 0) {
    return ['尚無歷史紀錄，先從掃描或手動加入餐點開始建立趨勢。'];
  }

  const avgCalories = summary.avg_calories || 0;
  return [
    `近 ${daily.length} 天平均熱量 ${avgCalories} kcal/日。`,
    buildSodiumInsight(daily, sodiumTarget),
    buildLatestCalorieInsight(daily[daily.length - 1], calorieTarget),
  ];
}

function buildSodiumInsight(daily: HistoryDay[], sodiumTarget: number): string {
  const overDays = findSodiumOverDays(daily, sodiumTarget);
  if (overDays.length === 0) {
    return '近期鈉攝取沒有明顯超標日，維持目前記錄習慣。';
  }

  const worst = overDays.reduce((max, day) => (day.sodium > max.sodium ? day : max));
  const worstText = `${shortDate(worst.date)} 的 ${formatNumber(worst.sodium)} mg`;
  const prefix = `近 ${daily.length} 天有 ${overDays.length} 天鈉超過每日上限 ${formatNumber(sodiumTarget)} mg`;
  const detail = overDays.length === 1 ? `，是 ${worstText}` : `，最高是 ${worstText}`;
  return `${prefix}${detail}，建議檢查加工食品與外食比例。`;
}

function buildLatestCalorieInsight(latest: HistoryDay, calorieTarget: number): string {
  switch (classifyCalories(latest.calories, calorieTarget)) {
    case 'low':
      return `最近一天熱量偏低，距離目標仍差 ${formatNumber(calorieTarget - latest.calories)} kcal。`;
    case 'high':
      return `最近一天熱量偏高，超過目標 ${formatNumber(latest.calories - calorieTarget)} kcal，可留意份量與油炸、含糖食物。`;
    default:
      return '最近一天的熱量接近個人目標，可觀察蛋白質與纖維是否同步達標。';
  }
}

/** YYYY-MM-DD → MM-DD，跟熱量長條圖下方的日期標籤一樣。 */
function shortDate(date: string): string {
  return date.slice(5);
}

// 固定用 en-US 分位號，不跟著裝置語系變成 2.730 之類的寫法。
const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

function formatNumber(value: number): string {
  return numberFormat.format(Math.round(value));
}
