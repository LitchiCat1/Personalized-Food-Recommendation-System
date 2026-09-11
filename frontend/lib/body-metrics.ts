/**
 * BMI 分級與「目標體重 vs 每日目標熱量」的一致性檢查。
 *
 * 兩件事的共同點：畫面上先前都只有一個裸數字，讀者要自己去查表或自己
 * 心算，而算錯的方向剛好是最糟的那個。
 */

export type BmiCategory = {
  label: string;
  /** 'normal' 用綠色，'caution' 橘色，'alert' 紅色。 */
  tone: 'normal' | 'caution' | 'alert';
};

/**
 * 依衛福部國健署的成人 BMI 建議範圍分級。
 *
 * 先前 BMI 那張卡片的顏色是寫死的 `Palette.accent.orange`：BMI 20.3
 * （標準範圍）跟 BMI 35 長得一模一樣，都是警示橘，還就擺在兩張綠色卡片
 * 旁邊。一個「你的數值正常」的畫面不該用警示色講。
 */
export function bmiCategory(bmi: number): BmiCategory {
  if (!Number.isFinite(bmi) || bmi <= 0) return { label: '未設定', tone: 'caution' };
  if (bmi < 18.5) return { label: '過輕', tone: 'caution' };
  if (bmi < 24) return { label: '正常範圍', tone: 'normal' };
  if (bmi < 27) return { label: '過重', tone: 'caution' };
  if (bmi < 30) return { label: '輕度肥胖', tone: 'alert' };
  if (bmi < 35) return { label: '中度肥胖', tone: 'alert' };
  return { label: '重度肥胖', tone: 'alert' };
}

export type WeightGoalReading = {
  /** 想往哪個方向走。 */
  direction: 'gain' | 'lose' | 'maintain';
  /** 距離目標還有幾公斤（絕對值，一位小數）。 */
  gapKg: number;
  /** 一句話描述目標，永遠會有。 */
  summary: string;
  /**
   * 目標體重的方向與現在生效的每日熱量目標互相矛盾時的說明，否則是 null。
   *
   * 先前「飲食目標」分頁同時顯示「目標體重 70kg／目前體重 50kg／每日目標
   * 1,898 kcal」，而 TDEE 是 2,133——想增重 20 公斤，拿到的卻是一個赤字
   * 235 kcal 的目標，畫面上一個字都沒提。target_weight 整條後端也只是存進去
   * 再讀出來，沒有任何計算用到它。它至少要說出自己跟熱量目標對不上。
   */
  conflict: string | null;
};

/** 低於這個差距就當成「維持體重」，不要為了 0.3 公斤報一個矛盾。 */
const MAINTAIN_TOLERANCE_KG = 1;
/** 每日目標與 TDEE 差距小於這個值就當成打平。 */
const ENERGY_TOLERANCE_KCAL = 100;

export function readWeightGoal(
  currentWeight: number,
  targetWeight: number,
  dailyTarget: number,
  tdee: number,
): WeightGoalReading | null {
  if (!targetWeight || !Number.isFinite(targetWeight) || targetWeight <= 0) return null;
  if (!currentWeight || !Number.isFinite(currentWeight)) return null;

  const delta = targetWeight - currentWeight;
  const gapKg = Math.round(Math.abs(delta) * 10) / 10;
  const direction: WeightGoalReading['direction'] =
    Math.abs(delta) < MAINTAIN_TOLERANCE_KG ? 'maintain' : delta > 0 ? 'gain' : 'lose';

  const summary =
    direction === 'maintain'
      ? `維持目前的 ${currentWeight} kg。`
      : `距離目標體重還有 ${gapKg} kg（${direction === 'gain' ? '增重' : '減重'}）。`;

  let conflict: string | null = null;
  if (Number.isFinite(dailyTarget) && Number.isFinite(tdee) && tdee > 0) {
    const balance = dailyTarget - tdee;
    if (direction === 'gain' && balance < -ENERGY_TOLERANCE_KCAL) {
      conflict =
        `每日目標 ${Math.round(dailyTarget).toLocaleString()} kcal 比你的 TDEE 少 ` +
        `${Math.abs(Math.round(balance)).toLocaleString()} kcal，照這個吃是會往下掉的，` +
        `跟「增重 ${gapKg} kg」的目標相反。`;
    } else if (direction === 'lose' && balance > ENERGY_TOLERANCE_KCAL) {
      conflict =
        `每日目標 ${Math.round(dailyTarget).toLocaleString()} kcal 比你的 TDEE 多 ` +
        `${Math.round(balance).toLocaleString()} kcal，跟「減重 ${gapKg} kg」的目標相反。`;
    }
  }

  return { direction, gapKg, summary, conflict };
}
