/**
 * 每日營養追蹤的「空白」狀態：欄位齊全，但一個數字都沒有。
 *
 * 先前 store 的初始值直接用 constants/mock-data.ts 的 DAILY_NUTRITION，
 * 而那份 mock 裡寫著 `calories.current: 1450`、`sodium.current: 1800`，
 * 搭配 TODAY_MEALS 的四筆假餐點與 HEALTH_ALERTS 的假警示。結果是每一次
 * 開啟首頁，在後端紀錄回來之前（實測約 8 秒，後端冷啟動更久）畫面都會顯示：
 *
 *   今天還能吃 650 kcal ／ 已攝取 1450 kcal ／ 鈉攝取 1800 mg ／ 4 筆餐點
 *   ⚠ 鈉含量接近上限 — 今日鈉攝取已達 1,800mg（上限 2,000mg），建議晚餐選擇低鈉餐點。
 *
 * 使用者什麼都還沒吃。對一個高血壓使用者發出一則沒有根據的飲食指示，比
 * 顯示不出數字糟得多。
 *
 * 這裡只保留呈現用的欄位（標籤、單位、顏色）——那些是設計，不是資料。
 * current 與 target 一律 0，並且由 store 的 dashboardReady 告訴畫面
 * 「這些 0 是還沒載入，不是真的沒吃」。
 */
export const EMPTY_DAILY_NUTRITION = {
  calories: { current: 0, target: 0, unit: 'kcal' },
  protein: { current: 0, target: 0, unit: 'g', color: '#60A5FA', label: '蛋白質' },
  carbs: { current: 0, target: 0, unit: 'g', color: '#FB923C', label: '總碳水化合物' },
  sugar: { current: 0, target: 0, unit: 'g', color: '#F59E0B', label: '精緻糖' },
  fat: { current: 0, target: 0, unit: 'g', color: '#A78BFA', label: '總脂肪' },
  saturated_fat: { current: 0, target: 0, unit: 'g', color: '#8B5CF6', label: '飽和脂肪' },
  trans_fat: { current: 0, target: 0, unit: 'g', color: '#EF4444', label: '反式脂肪' },
  sodium: { current: 0, target: 0, unit: 'mg', color: '#F472B6', label: '鈉 (Sodium)' },
  fiber: { current: 0, target: 0, unit: 'g', color: '#4ADE80', label: '膳食纖維' },
};

export type DailyNutrition = typeof EMPTY_DAILY_NUTRITION;
