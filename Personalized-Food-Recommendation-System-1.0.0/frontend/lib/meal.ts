/**
 * 一天怎麼切成「餐」——餐別判定與單餐額度。
 *
 * 這些規則原本散在三個地方各寫一份：store 依時間判早餐/午餐/晚餐、
 * scanner 送給後端時寫死「點心」、掃描結果用寫死的 800/1200mg 判鈉。
 * 同一筆紀錄因此會在不同畫面得到不同的餐別與不同的鈉標準。
 */

export type MealType = '早餐' | '午餐' | '晚餐' | '點心';

/** 疾病規則檔的 personalized_limits 也是用 meals_per_day: 3 推單餐上限。 */
export const MEALS_PER_DAY = 3;

/**
 * 依用餐時間判餐別。
 *
 * 一定要帶「這筆紀錄發生的時間」，不能用送出的時間：離線佇列可能在
 * 晚上才補送早上那筆，用當下時間會把早餐標成晚餐。
 */
export function getAutoMealType(at: Date = new Date()): MealType {
  const h = at.getHours();
  if (h < 10) return '早餐';
  if (h < 14) return '午餐';
  if (h < 17) return '點心';
  return '晚餐';
}

export function normalizeMealType(mealType?: string): MealType {
  if (mealType === '早餐' || mealType === '午餐' || mealType === '晚餐' || mealType === '點心') {
    return mealType;
  }
  return '點心';
}

/**
 * 每日上限換算成單餐額度。
 *
 * 掃描頁判「這一餐鈉會不會太高」要跟使用者的每日目標連動——腎臟病的
 * 每日鈉目標是 1500mg，用寫死的 2000mg 去除會把超標的餐點顯示成正常。
 */
export function perMealBudget(dailyTarget: number | undefined | null, fallbackDaily: number): number {
  const daily = Number(dailyTarget);
  const safeDaily = Number.isFinite(daily) && daily > 0 ? daily : fallbackDaily;
  return safeDaily / MEALS_PER_DAY;
}
