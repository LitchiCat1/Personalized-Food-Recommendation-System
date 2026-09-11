/**
 * 新帳號的起始健康檔案。
 *
 * 先前這組值來自 constants/mock-data.ts 的 USER_PROFILE——也就是示範用的
 * 「王小明」。「我的」頁在後端回 404（帳號還沒有檔案）時，會直接把那份
 * 資料 POST 上去建檔，於是每個新帳號一開好就帶著：
 *
 *   175cm / 72kg / 28 歲 / 男性 / 高血壓 / 對花生與蝦蟹過敏 / 目標體重 70kg
 *
 * 身高體重填錯只是不準；**憑空多一個高血壓診斷與兩項過敏原**是另一回事：
 * 整個 App 的每日熱量目標、單餐鈉上限、店家排序與掃描風險提示都吃這兩欄。
 * 使用者會看到一份「依高血壓的臨床指引計算」的目標，而他從來沒說過自己
 * 有高血壓。反過來也一樣糟——沒被問過的人以為 App 已經知道他對什麼過敏。
 *
 * 所以這裡的規則是：**疾病與過敏原永遠是空的，只能由使用者自己勾**。
 * 身體數值仍然需要一個起始值（BMR/TDEE 的公式要有輸入），但檔案會帶著
 * profileComplete: false，畫面據此要求使用者先確認，不把它當成真實資料。
 */

export const NEW_USER_PROFILE = {
  gender: 'female' as 'male' | 'female',
  height: 165,
  weight: 60,
  age: 30,
  activityLevel: '中等活動（每週 3-5 天）',
  activityMultiplier: 1.55,
  /** 由使用者填寫；未設定時畫面顯示「未設定」而不是一個猜出來的數字。 */
  targetWeight: 0,
  dietType: '葷食',
  /** 醫療欄位不給預設值。 */
  healthConditions: [] as string[],
  allergens: [] as string[],
};

/**
 * 身體數值的合理範圍，與後端 profile_service.PROFILE_LIMITS 同一組。
 *
 * 後端會透過 /medical-metadata 的 profile_limits 送下來，這裡只是拿不到
 * metadata 時的退路。要擋的是打錯字與單位搞錯（170 公尺、50 公克），
 * 不是替使用者判斷胖瘦。
 */
export type ProfileLimit = { min: number; max: number; unit: string; label_zh: string };

export const PROFILE_LIMITS: Record<string, ProfileLimit> = {
  height: { min: 80, max: 250, unit: 'cm', label_zh: '身高' },
  weight: { min: 20, max: 400, unit: 'kg', label_zh: '體重' },
  age: { min: 13, max: 120, unit: '歲', label_zh: '年齡' },
  target_weight: { min: 20, max: 400, unit: 'kg', label_zh: '目標體重' },
  daily_calorie_target: { min: 800, max: 6000, unit: 'kcal', label_zh: '每日熱量基準' },
};

export function isWithinLimit(limit: ProfileLimit | undefined, raw: string): boolean {
  if (!limit) return raw.trim().length > 0 && Number(raw) > 0;
  const value = Number(raw);
  return raw.trim().length > 0 && Number.isFinite(value) && value >= limit.min && value <= limit.max;
}

export function describeLimit(limit: ProfileLimit): string {
  // 拉丁字母的單位（cm / kg / kcal）前後要留空白，中文單位（歲）不要——
  // 先前一律加空白，「年齡要在 13~120 歲 之間」中間會斷開。
  const unit = /^[A-Za-z]/.test(limit.unit) ? ` ${limit.unit} ` : `${limit.unit}`;
  return `${limit.label_zh}要在 ${limit.min}~${limit.max}${unit}之間`;
}
