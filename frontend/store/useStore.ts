/**
 * NutriLens Global State — Zustand Store
 * Manages user profile, dietary records, scan results, and app settings
 */

import { create } from 'zustand';
import { MEALS_PER_DAY, getAutoMealType, normalizeMealType } from '@/lib/meal';
import { toggleSelection } from '@/lib/safety-selection';
import type { DetectedFood, MealEntry, HealthAlert } from '@/constants/mock-data';
import { EMPTY_DAILY_NUTRITION } from '@/constants/nutrition-display';
import { NEW_USER_PROFILE } from '@/constants/profile-defaults';
import { resolveApiBaseUrl } from '@/lib/network';
import type { DietaryRecord, NutritionGoalTypes, NutritionTargetBasis, NutritionTargets } from '@/lib/api';

// ─── Types ──────────────────────────────────────────────────
export interface UserProfile {
  userId: string;
  name: string;
  email: string;
  gender: 'male' | 'female';
  height: number;
  weight: number;
  age: number;
  bmi: number;
  activityLevel: string;
  activityMultiplier: number;
  bmr: number;
  tdee: number;
  healthConditions: string[];
  allergens: string[];
  streak: number;
  totalMeals: number;
  dailyCalorieTarget: number;
  targetWeight: number;
  dietType: string;
  /**
   * 這份檔案的數字是使用者自己填過的嗎？
   *
   * 新帳號第一次進「我的」頁時會先建一份空白檔案（否則其他 API 全部 404），
   * 裡面的身高體重是起始預設值，不是任何人填的。沒有這個旗標，畫面就沒辦法
   * 分辨「他填了 165cm」跟「我們猜他 165cm」。
   */
  profileComplete: boolean;
}

export interface ScanResult {
  isScanning: boolean;
  detections: DetectedFood[];
  timestamp: string | null;
}

export interface NutriLensState {
  // User
  user: UserProfile;
  accessToken: string | null;
  authReady: boolean;
  isAuthenticated: boolean;
  setAuthSession: (session: { userId: string; email?: string | null; accessToken: string | null } | null) => void;
  setAuthReady: (ready: boolean) => void;
  updateUserField: <K extends keyof UserProfile>(key: K, value: UserProfile[K]) => void;
  replaceUser: (user: UserProfile) => void;
  /** aliases 傳入該項目的中文標籤，才能一併清掉舊格式的資料。 */
  toggleCondition: (condition: string, aliases?: string[]) => void;
  toggleAllergen: (allergen: string, aliases?: string[]) => void;
  recalculateBMR: () => void;

  // Dashboard
  dailyNutrition: typeof EMPTY_DAILY_NUTRITION;
  /**
   * 後端的今日紀錄與目標回來了沒。
   *
   * 沒有這個旗標，畫面就分不出「0 kcal 是他今天真的還沒吃」跟「0 kcal 是
   * 我們還不知道」——而這兩件事在首頁上長得一模一樣。
   */
  dashboardReady: boolean;
  /**
   * 每日目標值本身回來了沒——比 dashboardReady 弱的條件。
   *
   * 「我的」頁只抓目標（applyNutritionTargets），不抓今日已攝取量，所以它
   * 不能等 dashboardReady：那個旗標只有首頁的 replaceDashboardFromRecords
   * 會設，直接開「我的」頁會永遠停在「讀取中…」。
   *
   * 反過來也不能共用一個：首頁顯示的是「已攝取 / 目標」，只有目標到手時把
   * 已攝取的 0 當成真的，就是這次要修掉的那個問題。
   */
  nutritionTargetsReady: boolean;
  todayMeals: MealEntry[];
  healthAlerts: HealthAlert[];
  dietaryRecordsRevision: number;
  /** 每個營養素的目標是上限還是下限，由後端依疾病決定。 */
  nutritionGoalTypes: NutritionGoalTypes;
  /** 目前生效的每日熱量目標是怎麼來的，用來在畫面上解釋為什麼不是使用者填的那個數字。 */
  nutritionTargetBasis: NutritionTargetBasis | null;
  invalidateDietaryRecords: () => void;
  addMealFromScan: (detections: DetectedFood[]) => void;
  replaceDashboardFromRecords: (
    records: DietaryRecord[],
    targets?: NutritionTargets,
    goalTypes?: NutritionGoalTypes,
    basis?: NutritionTargetBasis,
  ) => void;
  /** 由實際紀錄算出的連續天數與累積餐數。 */
  setActivityStats: (stats: { streak: number; totalMeals: number }) => void;
  /**
   * 只更新每日目標，不動已攝取量與餐點清單。
   *
   * 給「不是首頁、但也需要顯示正確目標」的畫面用——直接開「我的」頁時，
   * 先前顯示的是 store 的預設 2100 kcal，跟首頁的數字對不起來。
   */
  applyNutritionTargets: (
    targets?: NutritionTargets,
    goalTypes?: NutritionGoalTypes,
    basis?: NutritionTargetBasis,
  ) => void;
  resetDashboard: () => void;

  // Scanner
  scanResult: ScanResult;
  setScanResult: (detections: DetectedFood[]) => void;
  updateScanFoodWeight: (foodId: string, nextWeight: number) => void;
  clearScan: () => void;
  setScanning: (v: boolean) => void;

  // Camera active flag (hides tab bar)
  isCameraActive: boolean;
  setCameraActive: (v: boolean) => void;

  // Backend API base URL
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
}

// ─── BMR/TDEE computation ───────────────────────────────────
function computeBMR(gender: string, weight: number, height: number, age: number): number {
  if (gender === 'male') return Math.round(10 * weight + 6.25 * height - 5 * age + 5);
  return Math.round(10 * weight + 6.25 * height - 5 * age - 161);
}

function computeBMI(weight: number, height: number): number {
  return Math.round((weight / (height / 100) ** 2) * 10) / 10;
}

// ─── Store ──────────────────────────────────────────────────
export const useStore = create<NutriLensState>((set, get) => ({
  // ── User Profile ──
  // 先前這裡整份抄 constants/mock-data.ts 的 USER_PROFILE（示範用的「王小明」），
  // 而「我的」頁會把它 POST 上去當成新帳號的健康檔案——包含一個沒人說過的
  // 高血壓診斷與兩項過敏原。疾病與過敏原現在一律留空，只能由使用者自己勾。
  // 詳見 constants/profile-defaults.ts。
  user: {
    userId: 'demo_user',
    name: '',
    email: '',
    gender: NEW_USER_PROFILE.gender,
    height: NEW_USER_PROFILE.height,
    weight: NEW_USER_PROFILE.weight,
    age: NEW_USER_PROFILE.age,
    bmi: computeBMI(NEW_USER_PROFILE.weight, NEW_USER_PROFILE.height),
    activityLevel: NEW_USER_PROFILE.activityLevel,
    activityMultiplier: NEW_USER_PROFILE.activityMultiplier,
    bmr: computeBMR(NEW_USER_PROFILE.gender, NEW_USER_PROFILE.weight, NEW_USER_PROFILE.height, NEW_USER_PROFILE.age),
    tdee: Math.round(
      computeBMR(NEW_USER_PROFILE.gender, NEW_USER_PROFILE.weight, NEW_USER_PROFILE.height, NEW_USER_PROFILE.age)
        * NEW_USER_PROFILE.activityMultiplier,
    ),
    healthConditions: [...NEW_USER_PROFILE.healthConditions],
    allergens: [...NEW_USER_PROFILE.allergens],
    // 真實數字由 setActivityStats 依實際紀錄算出來；在那之前是 0，不是假的 14 天。
    streak: 0,
    totalMeals: 0,
    dailyCalorieTarget: Math.round(
      computeBMR(NEW_USER_PROFILE.gender, NEW_USER_PROFILE.weight, NEW_USER_PROFILE.height, NEW_USER_PROFILE.age)
        * NEW_USER_PROFILE.activityMultiplier,
    ),
    targetWeight: NEW_USER_PROFILE.targetWeight,
    dietType: NEW_USER_PROFILE.dietType,
    profileComplete: false,
  },

  accessToken: null,
  authReady: false,
  isAuthenticated: false,

  setAuthReady: (ready) => set({ authReady: ready }),

  setAuthSession: (session) =>
    set((state) => {
      if (!session) {
        return { accessToken: null, isAuthenticated: false };
      }
      return {
        accessToken: session.accessToken,
        isAuthenticated: true,
        user: {
          ...state.user,
          userId: session.userId,
          email: session.email || state.user.email,
        },
      };
    }),

  updateUserField: (key, value) =>
    set((state) => ({ user: { ...state.user, [key]: value } })),

  replaceUser: (user) => set({ user }),

  toggleCondition: (condition, aliases) =>
    set((state) => ({
      user: { ...state.user, healthConditions: toggleSelection(state.user.healthConditions, condition, aliases) },
    })),

  toggleAllergen: (allergen, aliases) =>
    set((state) => ({
      user: { ...state.user, allergens: toggleSelection(state.user.allergens, allergen, aliases) },
    })),

  recalculateBMR: () =>
    set((state) => {
      const { gender, weight, height, age, activityMultiplier } = state.user;
      const bmr = computeBMR(gender, weight, height, age);
      const tdee = Math.round(bmr * activityMultiplier);
      const bmi = Math.round((weight / ((height / 100) ** 2)) * 10) / 10;
      return { user: { ...state.user, bmr, tdee, bmi } };
    }),

  // ── Dashboard ──
  //
  // 初始值先前是 constants/mock-data.ts 的 DAILY_NUTRITION / TODAY_MEALS /
  // HEALTH_ALERTS——也就是 1450 kcal、1800 mg 鈉、四筆假餐點與一則假的
  // 「鈉含量接近上限」警示。那些在後端紀錄回來之前會直接顯示給使用者看。
  dailyNutrition: { ...EMPTY_DAILY_NUTRITION },
  todayMeals: [],
  healthAlerts: [],
  dashboardReady: false,
  nutritionTargetsReady: false,
  dietaryRecordsRevision: 0,
  nutritionGoalTypes: {},
  nutritionTargetBasis: null,
  invalidateDietaryRecords: () => set((state) => ({ dietaryRecordsRevision: state.dietaryRecordsRevision + 1 })),

  resetDashboard: () =>
    set((state) => ({
      todayMeals: [],
      healthAlerts: [],
      // 清空之後在新資料回來前一樣是「還不知道」，不是「確定沒吃」。
      dashboardReady: false,
      nutritionTargetsReady: false,
      dailyNutrition: {
        ...state.dailyNutrition,
        calories: { ...state.dailyNutrition.calories, current: 0, target: state.user.dailyCalorieTarget },
        protein: { ...state.dailyNutrition.protein, current: 0 },
        carbs: { ...state.dailyNutrition.carbs, current: 0 },
        sugar: { ...state.dailyNutrition.sugar, current: 0 },
        fat: { ...state.dailyNutrition.fat, current: 0 },
        saturated_fat: { ...state.dailyNutrition.saturated_fat, current: 0 },
        trans_fat: { ...state.dailyNutrition.trans_fat, current: 0 },
        sodium: { ...state.dailyNutrition.sodium, current: 0 },
        fiber: { ...state.dailyNutrition.fiber, current: 0 },
      },
      user: { ...state.user, totalMeals: 0 },
    })),

  addMealFromScan: (detections) =>
    set((state) => {
      const newMeals: MealEntry[] = detections.map((d, i) => ({
        id: `scan_${Date.now()}_${i}`,
        name: d.foodName,
        calories: d.nutrition.calories,
        time: new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }),
        mealType: getAutoMealType(),
        emoji: '📸',
        protein: d.nutrition.protein,
        carbs: d.nutrition.carbs,
        fat: d.nutrition.fat,
        sodium: d.nutrition.sodium,
        fiber: d.nutrition.fiber,
        sugar: d.nutrition.sugar,
        saturated_fat: d.nutrition.saturated_fat,
        trans_fat: d.nutrition.trans_fat,
        is_fried: d.nutrition.is_fried,
        warnings: d.warnings,
      }));

      const updatedMeals = [...state.todayMeals, ...newMeals];
      const totalCal = Math.round(updatedMeals.reduce((s, m) => s + m.calories, 0));
      const totalProtein = Math.round(updatedMeals.reduce((s, m) => s + m.protein, 0));
      const totalCarbs = Math.round(updatedMeals.reduce((s, m) => s + m.carbs, 0));
      const totalFat = Math.round(updatedMeals.reduce((s, m) => s + m.fat, 0));
      const totalSodium = Math.round(updatedMeals.reduce((s, m) => s + m.sodium, 0));
      const totalFiber = Math.round(updatedMeals.reduce((s, m) => s + m.fiber, 0));
      const totalSugar = Math.round(updatedMeals.reduce((s, m) => s + (m.sugar || 0), 0) * 10) / 10;
      const totalSaturatedFat = Math.round(updatedMeals.reduce((s, m) => s + (m.saturated_fat || 0), 0) * 10) / 10;
      const totalTransFat = Math.round(updatedMeals.reduce((s, m) => s + (m.trans_fat || 0), 0) * 10) / 10;

      return {
        todayMeals: updatedMeals,
        dailyNutrition: {
          ...state.dailyNutrition,
          calories: { ...state.dailyNutrition.calories, current: totalCal },
          protein: { ...state.dailyNutrition.protein, current: totalProtein },
          carbs: { ...state.dailyNutrition.carbs, current: totalCarbs },
          sugar: { ...state.dailyNutrition.sugar, current: totalSugar },
          fat: { ...state.dailyNutrition.fat, current: totalFat },
          saturated_fat: { ...state.dailyNutrition.saturated_fat, current: totalSaturatedFat },
          trans_fat: { ...state.dailyNutrition.trans_fat, current: totalTransFat },
          sodium: { ...state.dailyNutrition.sodium, current: totalSodium },
          fiber: { ...state.dailyNutrition.fiber, current: totalFiber },
        },
        user: { ...state.user, totalMeals: state.user.totalMeals + newMeals.length },
      };
    }),

  replaceDashboardFromRecords: (records, targets, goalTypes, basis) =>
    set((state) => {
      const todayMeals = records.flatMap((record, recordIndex) => {
        const foods = record.foods && record.foods.length > 0
          ? record.foods
          : [{
              name: record.meal_type || '未命名餐點',
              calories: record.total_calories,
              protein: record.total_protein,
              carbs: record.total_carbs,
              fat: record.total_fat,
              sodium: record.total_sodium,
              fiber: record.total_fiber,
              sugar: record.total_sugar ?? record.total_refined_sugar,
              saturated_fat: record.total_saturated_fat,
              trans_fat: record.total_trans_fat,
              source: record.source,
              warnings: [],
            }];

        return foods.map((food, foodIndex) => ({
          id: `record_${record.timestamp}_${recordIndex}_${foodIndex}`,
          name: food.name || '未命名食品',
          calories: Number(food.calories || 0),
          time: formatRecordTime(record.timestamp),
          mealType: normalizeMealType(record.meal_type),
          emoji: getSourceEmoji(record.source || food.source),
          protein: Number(food.protein || 0),
          carbs: Number(food.carbs || 0),
          fat: Number(food.fat || 0),
          sodium: Number(food.sodium || 0),
          fiber: Number(food.fiber || 0),
          sugar: food.sugar !== undefined || food.refined_sugar !== undefined
            ? Number(food.sugar ?? food.refined_sugar)
            : undefined,
          saturated_fat: food.saturated_fat !== undefined ? Number(food.saturated_fat) : undefined,
          trans_fat: food.trans_fat !== undefined ? Number(food.trans_fat) : undefined,
          is_fried: food.is_fried,
          warnings: food.warnings || [],
        }));
      });

      const totals = sumMeals(todayMeals);
      const sodiumTarget = targets?.sodium ?? state.dailyNutrition.sodium.target;
      const proteinTarget = targets?.protein ?? state.dailyNutrition.protein.target;
      const calorieTarget = targets?.calories ?? state.user.dailyCalorieTarget;
      const healthAlerts = buildHealthAlerts(totals, sodiumTarget, proteinTarget, calorieTarget, todayMeals.length);

      return {
        todayMeals,
        healthAlerts,
        // 這是唯一「今日紀錄真的到手了」的地方。
        dashboardReady: true,
        nutritionTargetsReady: true,
        nutritionGoalTypes: goalTypes ?? state.nutritionGoalTypes,
        nutritionTargetBasis: basis ?? state.nutritionTargetBasis,
        dailyNutrition: {
          ...state.dailyNutrition,
          calories: { ...state.dailyNutrition.calories, current: totals.calories, target: targets?.calories ?? state.user.dailyCalorieTarget },
          protein: { ...state.dailyNutrition.protein, current: totals.protein, target: proteinTarget },
          carbs: { ...state.dailyNutrition.carbs, current: totals.carbs, target: targets?.carbs ?? state.dailyNutrition.carbs.target },
          sugar: { ...state.dailyNutrition.sugar, current: totals.sugar, target: targets?.sugar ?? state.dailyNutrition.sugar.target },
          fat: { ...state.dailyNutrition.fat, current: totals.fat, target: targets?.fat ?? state.dailyNutrition.fat.target },
          saturated_fat: { ...state.dailyNutrition.saturated_fat, current: totals.saturated_fat, target: targets?.saturated_fat ?? state.dailyNutrition.saturated_fat.target },
          trans_fat: { ...state.dailyNutrition.trans_fat, current: totals.trans_fat, target: targets?.trans_fat ?? state.dailyNutrition.trans_fat.target },
          sodium: { ...state.dailyNutrition.sodium, current: totals.sodium, target: sodiumTarget },
          fiber: { ...state.dailyNutrition.fiber, current: totals.fiber, target: targets?.fiber ?? state.dailyNutrition.fiber.target },
        },
      };
    }),

  setActivityStats: ({ streak, totalMeals }) =>
    set((state) => ({ user: { ...state.user, streak, totalMeals } })),

  applyNutritionTargets: (targets, goalTypes, basis) =>
    set((state) => {
      if (!targets && !goalTypes && !basis) return state;
      const withTarget = <T extends { target: number }>(entry: T, next?: number): T =>
        next === undefined ? entry : { ...entry, target: next };
      const daily = state.dailyNutrition;
      return {
        nutritionTargetsReady: true,
        nutritionGoalTypes: goalTypes ?? state.nutritionGoalTypes,
        nutritionTargetBasis: basis ?? state.nutritionTargetBasis,
        dailyNutrition: {
          ...daily,
          calories: withTarget(daily.calories, targets?.calories),
          protein: withTarget(daily.protein, targets?.protein),
          carbs: withTarget(daily.carbs, targets?.carbs),
          sugar: withTarget(daily.sugar, targets?.sugar),
          fat: withTarget(daily.fat, targets?.fat),
          saturated_fat: withTarget(daily.saturated_fat, targets?.saturated_fat),
          trans_fat: withTarget(daily.trans_fat, targets?.trans_fat),
          sodium: withTarget(daily.sodium, targets?.sodium),
          fiber: withTarget(daily.fiber, targets?.fiber),
        },
      };
    }),

  // ── Scanner ──
  scanResult: { isScanning: false, detections: [], timestamp: null },

  setScanResult: (detections) =>
    set({
      scanResult: {
        isScanning: false,
        detections: detections.map(ensureOriginalPortion),
        timestamp: new Date().toISOString(),
      },
    }),

  updateScanFoodWeight: (foodId, nextWeight) =>
    set((state) => ({
      scanResult: {
        ...state.scanResult,
        detections: state.scanResult.detections.map((food) => {
          if (food.id !== foodId) return food;
          const originalWeight = food.originalEstimatedWeight || food.estimatedWeight || 1;
          const originalNutrition = food.originalNutrition || food.nutrition;
          const safeWeight = Math.max(1, Math.round(nextWeight));
          const scale = safeWeight / originalWeight;
          return {
            ...food,
            estimatedWeight: safeWeight,
            originalEstimatedWeight: originalWeight,
            originalNutrition,
            portionRange: { minG: safeWeight, maxG: safeWeight, uncertaintyPercent: 0 },
            portionAdjusted: true,
            nutrition: scaleNutrition(originalNutrition, scale),
          };
        }),
      },
    })),

  clearScan: () =>
    set({ scanResult: { isScanning: false, detections: [], timestamp: null } }),

  setScanning: (v) =>
    set((state) => ({ scanResult: { ...state.scanResult, isScanning: v } })),

  // ── Camera active flag ──
  isCameraActive: false,
  setCameraActive: (v) => set({ isCameraActive: v }),

  // ── API ──
  apiBaseUrl: resolveApiBaseUrl(),
  setApiBaseUrl: (url) => set({ apiBaseUrl: url }),
}));

// ─── Helpers ────────────────────────────────────────────────
function ensureOriginalPortion(food: DetectedFood): DetectedFood {
  return {
    ...food,
    originalEstimatedWeight: food.originalEstimatedWeight || food.estimatedWeight,
    originalNutrition: food.originalNutrition || food.nutrition,
  };
}

function scaleNutrition(nutrition: DetectedFood['nutrition'], scale: number): DetectedFood['nutrition'] {
  return {
    calories: Math.round(nutrition.calories * scale),
    protein: Math.round(nutrition.protein * scale * 10) / 10,
    carbs: Math.round(nutrition.carbs * scale * 10) / 10,
    fat: Math.round(nutrition.fat * scale * 10) / 10,
    sodium: Math.round(nutrition.sodium * scale),
    fiber: Math.round(nutrition.fiber * scale * 10) / 10,
    sugar: nutrition.sugar !== undefined ? Math.round(nutrition.sugar * scale * 10) / 10 : undefined,
    saturated_fat: nutrition.saturated_fat !== undefined ? Math.round(nutrition.saturated_fat * scale * 10) / 10 : undefined,
    trans_fat: nutrition.trans_fat !== undefined ? Math.round(nutrition.trans_fat * scale * 10) / 10 : undefined,
    is_fried: nutrition.is_fried,
  };
}

function formatRecordTime(timestamp?: string): string {
  if (!timestamp) return '--:--';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    const match = timestamp.match(/T(\d{2}:\d{2})/);
    return match?.[1] || '--:--';
  }
  return date.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function getSourceEmoji(source?: string): string {
  const key = String(source || '').toLowerCase();
  if (key === 'nutrition-label') return '🏷️';
  // 手動搜尋，以及資料直接來自食品資料庫的紀錄，都不是拍照來的
  if (key === 'manual' || key === 'tfda' || key === 'custom') return '🔎';
  return '📸';
}

function sumMeals(meals: MealEntry[]) {
  return {
    calories: Math.round(meals.reduce((s, m) => s + m.calories, 0)),
    protein: Math.round(meals.reduce((s, m) => s + m.protein, 0) * 10) / 10,
    carbs: Math.round(meals.reduce((s, m) => s + m.carbs, 0) * 10) / 10,
    fat: Math.round(meals.reduce((s, m) => s + m.fat, 0) * 10) / 10,
    sodium: Math.round(meals.reduce((s, m) => s + m.sodium, 0)),
    fiber: Math.round(meals.reduce((s, m) => s + m.fiber, 0) * 10) / 10,
    sugar: Math.round(meals.reduce((s, m) => s + (m.sugar || 0), 0) * 10) / 10,
    saturated_fat: Math.round(meals.reduce((s, m) => s + (m.saturated_fat || 0), 0) * 10) / 10,
    trans_fat: Math.round(meals.reduce((s, m) => s + (m.trans_fat || 0), 0) * 10) / 10,
  };
}

function buildHealthAlerts(
  totals: ReturnType<typeof sumMeals>,
  sodiumTarget: number,
  proteinTarget: number,
  calorieTarget: number,
  mealCount: number,
): HealthAlert[] {
  const alerts: HealthAlert[] = [];

  // 吃太少一樣是風險。先前這裡只檢查「有沒有超過」，所以整天只吃到目標的
  // 六成也會顯示「目前沒有需要優先處理的飲食警示」。等三餐都記錄完才提醒，
  // 免得早餐剛記完就跳「熱量不足」。
  if (mealCount >= MEALS_PER_DAY && calorieTarget > 0 && totals.calories < calorieTarget * 0.8) {
    alerts.push({
      id: 'calories-short',
      type: 'warning',
      title: '今天熱量可能不夠',
      message: `三餐合計 ${Math.round(totals.calories)} kcal，離每日目標 ${Math.round(calorieTarget)} kcal 還差 ${Math.round(calorieTarget - totals.calories)} kcal。`,
      icon: '🍚',
    });
  }

  if (totals.sodium >= sodiumTarget) {
    alerts.push({
      id: 'sodium-over',
      type: 'danger',
      title: '鈉含量已超過上限',
      message: `今日鈉攝取 ${totals.sodium}mg，已超過建議上限 ${sodiumTarget}mg。`,
      icon: '⚠️',
    });
  } else if (totals.sodium >= sodiumTarget * 0.8) {
    alerts.push({
      id: 'sodium-warning',
      type: 'warning',
      title: '鈉含量接近上限',
      message: `今日鈉攝取 ${totals.sodium}mg，建議下一餐選擇低鈉餐點。`,
      icon: '⚠️',
    });
  }

  if (totals.protein >= proteinTarget * 0.6) {
    alerts.push({
      id: 'protein-good',
      type: 'info',
      title: '蛋白質攝取良好',
      message: `已攝取 ${totals.protein}g 蛋白質，接近每日目標。`,
      icon: '💪',
    });
  }

  return alerts;
}
