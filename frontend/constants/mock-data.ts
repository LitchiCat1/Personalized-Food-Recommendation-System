/**
 * Mock Data for NutriLens App
 * Aligned with PRD requirements
 */

// ─── Dashboard ──────────────────────────────────────────────
export const DAILY_NUTRITION = {
  calories: { current: 1450, target: 2100, unit: 'kcal' },
  protein: { current: 85, target: 130, unit: 'g', color: '#60A5FA', label: '蛋白質' },
  carbs: { current: 160, target: 250, unit: 'g', color: '#FB923C', label: '碳水化合物' },
  fat: { current: 42, target: 70, unit: 'g', color: '#A78BFA', label: '脂肪' },
  // PRD: 鈉含量、纖維素追蹤 (高血壓/腎臟病患者需要)
  sodium: { current: 1800, target: 2000, unit: 'mg', color: '#F472B6', label: '鈉' },
  fiber: { current: 18, target: 25, unit: 'g', color: '#4ADE80', label: '膳食纖維' },
};

export type MealEntry = {
  id: string;
  name: string;
  calories: number;
  time: string;
  mealType: '早餐' | '午餐' | '晚餐' | '點心';
  emoji: string;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
  fiber: number;
  // PRD: 疾病禁忌標記
  warnings?: string[];
};

export const TODAY_MEALS: MealEntry[] = [
  {
    id: '1',
    name: '燕麥優格碗',
    calories: 380,
    time: '08:15',
    mealType: '早餐',
    emoji: '🥣',
    protein: 15,
    carbs: 52,
    fat: 12,
    sodium: 180,
    fiber: 6,
  },
  {
    id: '2',
    name: '雞胸肉沙拉',
    calories: 420,
    time: '12:30',
    mealType: '午餐',
    emoji: '🥗',
    protein: 38,
    carbs: 28,
    fat: 14,
    sodium: 520,
    fiber: 5,
  },
  {
    id: '3',
    name: '香蕉蛋白奶昔',
    calories: 280,
    time: '15:00',
    mealType: '點心',
    emoji: '🥤',
    protein: 22,
    carbs: 35,
    fat: 6,
    sodium: 120,
    fiber: 3,
  },
  {
    id: '4',
    name: '鮭魚飯糰套餐',
    calories: 520,
    time: '18:45',
    mealType: '晚餐',
    emoji: '🍱',
    protein: 32,
    carbs: 58,
    fat: 16,
    sodium: 980,
    fiber: 4,
    warnings: ['高鈉'],
  },
];

// PRD: 預警機制 — 超量攝取/禁忌食物即時警示
export type HealthAlert = {
  id: string;
  type: 'warning' | 'danger' | 'info';
  title: string;
  message: string;
  icon: string;
};

export const HEALTH_ALERTS: HealthAlert[] = [
  {
    id: '1',
    type: 'warning',
    title: '鈉含量接近上限',
    message: '今日鈉攝取已達 1,800mg（上限 2,000mg），建議晚餐選擇低鈉餐點。',
    icon: '⚠️',
  },
  {
    id: '2',
    type: 'info',
    title: '蛋白質攝取良好',
    message: '已達每日目標的 65%，繼續保持均衡攝取。',
    icon: '💪',
  },
];

// ─── Scanner ────────────────────────────────────────────────
export const SCANNER_PLACEHOLDER_RESULT = {
  foodName: '等待辨識...',
  confidence: 0,
  nutrition: {
    calories: '--' as string | number,
    protein: '--' as string | number,
    carbs: '--' as string | number,
    fat: '--' as string | number,
    sodium: '--' as string | number,
    fiber: '--' as string | number,
  },
};

// PRD: 多目標偵測 — 支援 Bounding Box 多食物同時辨識
export type DetectedFood = {
  id: string;
  foodName: string;
  confidence: number;
  boundingBox: { x: number; y: number; w: number; h: number };
  estimatedWeight: number; // grams
  nutrition: {
    calories: number;
    protein: number;
    carbs: number;
    fat: number;
    sodium: number;
    fiber: number;
  };
  // PRD: 硬性排除規則 — GI 指數、過敏原
  gi: 'low' | 'medium' | 'high';
  allergens: string[];
  warnings: string[];
};

export const SCANNER_DEMO_RESULTS: DetectedFood[] = [
  {
    id: '1',
    foodName: '白飯',
    confidence: 96.2,
    boundingBox: { x: 0.1, y: 0.2, w: 0.35, h: 0.3 },
    estimatedWeight: 200,
    nutrition: { calories: 260, protein: 5, carbs: 57, fat: 0.6, sodium: 2, fiber: 0.6 },
    gi: 'high',
    allergens: ['麩質'],
    warnings: ['高 GI 食物 — 糖尿病患者請注意'],
  },
  {
    id: '2',
    foodName: '滷肉',
    confidence: 91.8,
    boundingBox: { x: 0.5, y: 0.15, w: 0.3, h: 0.25 },
    estimatedWeight: 80,
    nutrition: { calories: 225, protein: 18, carbs: 5, fat: 15, sodium: 680, fiber: 0 },
    gi: 'low',
    allergens: ['大豆'],
    warnings: ['高鈉 — 高血壓患者請注意'],
  },
  {
    id: '3',
    foodName: '燙青菜',
    confidence: 88.5,
    boundingBox: { x: 0.15, y: 0.55, w: 0.25, h: 0.2 },
    estimatedWeight: 120,
    nutrition: { calories: 35, protein: 3, carbs: 4, fat: 0.5, sodium: 15, fiber: 3.2 },
    gi: 'low',
    allergens: [],
    warnings: [],
  },
];

// ─── Profile ────────────────────────────────────────────────
// PRD: 性別欄位 (BMR 計算需要)、疾病標籤、過敏原
export const USER_PROFILE = {
  name: '王小明',
  avatar: null,
  email: 'xiaoming@example.com',
  joinDate: '2026-01-15',
  gender: 'male' as 'male' | 'female',
  stats: {
    height: 175,
    weight: 72,
    bmi: 23.5,
    age: 28,
    activityLevel: '中等活動量',
    activityMultiplier: 1.55,
  },
  // PRD: BMR/TDEE 動態計算
  computed: {
    bmr: 1737, // Mifflin-St Jeor: 10*72 + 6.25*175 - 5*28 - 5
    tdee: 2692, // BMR * 1.55
  },
  // PRD: 疾病標籤 — 硬性排除規則基準
  healthConditions: ['高血壓'] as string[],
  // PRD: 過敏原管理
  allergens: ['花生', '蝦蟹'] as string[],
  goals: {
    dailyCalories: 2100,
    targetWeight: 70,
    dietType: '均衡飲食',
    mealPlan: '每日三餐 + 一次點心',
  },
  streak: 14,
  totalMeals: 187,
};

// PRD: 可選的疾病標籤列表
export const AVAILABLE_CONDITIONS = [
  { id: 'diabetes', label: '糖尿病', icon: '🩸', color: '#F87171', description: '限制高 GI、控醣' },
  { id: 'hypertension', label: '高血壓', icon: '❤️‍🩹', color: '#FB923C', description: '限制鈉攝取 < 2000mg' },
  { id: 'kidney', label: '慢性腎臟病', icon: '🫘', color: '#FBBF24', description: '限制蛋白質、磷、鉀' },
  { id: 'gout', label: '痛風', icon: '🦴', color: '#A78BFA', description: '限制高普林食物' },
  { id: 'hyperlipidemia', label: '高血脂', icon: '🫀', color: '#F472B6', description: '限制飽和脂肪、膽固醇' },
];

// PRD: 可選的過敏原列表
export const AVAILABLE_ALLERGENS = [
  '花生', '堅果', '蝦蟹', '貝類', '魚', '蛋', '牛奶', '大豆', '麩質', '芝麻',
];

export const DIET_GOALS = [
  { id: '1', icon: '🔥', label: '每日目標熱量', value: '2,100 kcal', color: '#FB923C' },
  { id: '2', icon: '🎯', label: '目標體重', value: '70 kg', color: '#4ADE80' },
  { id: '3', icon: '🥗', label: '飲食計畫', value: '均衡飲食', color: '#60A5FA' },
  { id: '4', icon: '🍽️', label: '用餐頻率', value: '每日 4 餐', color: '#A78BFA' },
  { id: '5', icon: '💧', label: '每日飲水', value: '2,000 ml', color: '#22D3EE' },
  { id: '6', icon: '⏰', label: '斷食計畫', value: '16:8 間歇性', color: '#F472B6' },
];

// ─── Recommendation (NEW — PRD 雙軌推薦引擎) ────────────────
export type RecommendedMeal = {
  id: string;
  name: string;
  emoji: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
  matchScore: number; // 0-100 口味相似度
  safetyBadges: string[]; // e.g., ['低鈉', '低 GI']
  distance?: string; // 地圖 API 距離 placeholder
  restaurant?: string;
};

export const RECOMMENDED_MEALS: RecommendedMeal[] = [
  {
    id: '1',
    name: '地中海鮭魚沙拉',
    emoji: '🥗',
    calories: 380,
    protein: 32,
    carbs: 18,
    fat: 22,
    sodium: 420,
    matchScore: 94,
    safetyBadges: ['低鈉', '低 GI', '高蛋白'],
    distance: '350m',
    restaurant: '綠食堂',
  },
  {
    id: '2',
    name: '日式味噌烤雞定食',
    emoji: '🍗',
    calories: 520,
    protein: 38,
    carbs: 45,
    fat: 16,
    sodium: 680,
    matchScore: 87,
    safetyBadges: ['高蛋白', '中 GI'],
    distance: '500m',
    restaurant: '和風亭',
  },
  {
    id: '3',
    name: '藜麥酪梨碗',
    emoji: '🥑',
    calories: 420,
    protein: 15,
    carbs: 48,
    fat: 20,
    sodium: 280,
    matchScore: 82,
    safetyBadges: ['低鈉', '高纖', '低 GI'],
    distance: '800m',
    restaurant: '穀活力',
  },
  {
    id: '4',
    name: '清蒸鱸魚套餐',
    emoji: '🐟',
    calories: 340,
    protein: 35,
    carbs: 28,
    fat: 8,
    sodium: 350,
    matchScore: 78,
    safetyBadges: ['低脂', '低鈉', '高蛋白'],
    distance: '1.2km',
    restaurant: '鮮食記',
  },
];

// PRD: 「安全過濾層」排除的不安全食物
export const FILTERED_UNSAFE_MEALS = [
  { name: '麻辣燙', reason: '高鈉 (3,200mg)、不適合高血壓患者', icon: '🌶️' },
  { name: '炸雞排', reason: '高飽和脂肪、高鈉', icon: '🍗' },
  { name: '珍珠奶茶', reason: '高糖、高 GI', icon: '🧋' },
];

// ─── History / Trends (NEW — PRD 飲食趨勢回顧) ──────────────
export type DailyRecord = {
  date: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
};

export const WEEKLY_HISTORY: DailyRecord[] = [
  { date: '04/11', calories: 2050, protein: 120, carbs: 230, fat: 65, sodium: 1900 },
  { date: '04/12', calories: 1880, protein: 105, carbs: 210, fat: 58, sodium: 2100 },
  { date: '04/13', calories: 2200, protein: 130, carbs: 260, fat: 72, sodium: 1750 },
  { date: '04/14', calories: 1950, protein: 115, carbs: 225, fat: 60, sodium: 2300 },
  { date: '04/15', calories: 2100, protein: 128, carbs: 240, fat: 68, sodium: 1800 },
  { date: '04/16', calories: 1780, protein: 98, carbs: 195, fat: 55, sodium: 1650 },
  { date: '04/17', calories: 1450, protein: 85, carbs: 160, fat: 42, sodium: 1800 },
];

export const WEEKLY_SUMMARY = {
  avgCalories: 1916,
  avgProtein: 112,
  avgCarbs: 217,
  avgFat: 60,
  avgSodium: 1900,
  calorieGoalHitDays: 4,
  totalDays: 7,
  trend: 'stable' as 'improving' | 'stable' | 'declining',
  insights: [
    { icon: '✅', text: '蛋白質攝取穩定達標，均值 112g/日' },
    { icon: '⚠️', text: '鈉攝取波動大，04/14 超標至 2,300mg' },
    { icon: '📉', text: '今日熱量偏低，建議補充 650 kcal 的均衡晚餐' },
  ],
};
