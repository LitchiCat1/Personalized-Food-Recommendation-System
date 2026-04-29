/**
 * NutriLens Global State — Zustand Store
 * Manages user profile, dietary records, scan results, and app settings
 */

import { create } from 'zustand';
import type { DetectedFood, MealEntry, HealthAlert } from '@/constants/mock-data';
import {
  DAILY_NUTRITION,
  TODAY_MEALS,
  HEALTH_ALERTS,
  USER_PROFILE,
} from '@/constants/mock-data';
import { resolveApiBaseUrl } from '@/lib/network';
import type { DietaryRecord } from '@/lib/api';

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
}

export interface ScanResult {
  isScanning: boolean;
  detections: DetectedFood[];
  timestamp: string | null;
}

export interface NutriLensState {
  // User
  user: UserProfile;
  updateUserField: <K extends keyof UserProfile>(key: K, value: UserProfile[K]) => void;
  replaceUser: (user: UserProfile) => void;
  toggleCondition: (condition: string) => void;
  toggleAllergen: (allergen: string) => void;
  recalculateBMR: () => void;

  // Dashboard
  dailyNutrition: typeof DAILY_NUTRITION;
  todayMeals: MealEntry[];
  healthAlerts: HealthAlert[];
  addMealFromScan: (detections: DetectedFood[]) => void;
  replaceDashboardFromRecords: (records: DietaryRecord[]) => void;

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

// ─── Store ──────────────────────────────────────────────────
export const useStore = create<NutriLensState>((set, get) => ({
  // ── User Profile ──
  user: {
    userId: 'demo_user',
    name: USER_PROFILE.name,
    email: USER_PROFILE.email,
    gender: USER_PROFILE.gender,
    height: USER_PROFILE.stats.height,
    weight: USER_PROFILE.stats.weight,
    age: USER_PROFILE.stats.age,
    bmi: USER_PROFILE.stats.bmi,
    activityLevel: USER_PROFILE.stats.activityLevel,
    activityMultiplier: USER_PROFILE.stats.activityMultiplier,
    bmr: USER_PROFILE.computed.bmr,
    tdee: USER_PROFILE.computed.tdee,
    healthConditions: [...USER_PROFILE.healthConditions],
    allergens: [...USER_PROFILE.allergens],
    streak: USER_PROFILE.streak,
    totalMeals: USER_PROFILE.totalMeals,
    dailyCalorieTarget: USER_PROFILE.goals.dailyCalories,
    targetWeight: USER_PROFILE.goals.targetWeight,
    dietType: USER_PROFILE.goals.dietType,
  },

  updateUserField: (key, value) =>
    set((state) => ({ user: { ...state.user, [key]: value } })),

  replaceUser: (user) => set({ user }),

  toggleCondition: (condition) =>
    set((state) => {
      const conditions = state.user.healthConditions.includes(condition)
        ? state.user.healthConditions.filter((c) => c !== condition)
        : [...state.user.healthConditions, condition];
      return { user: { ...state.user, healthConditions: conditions } };
    }),

  toggleAllergen: (allergen) =>
    set((state) => {
      const allergens = state.user.allergens.includes(allergen)
        ? state.user.allergens.filter((a) => a !== allergen)
        : [...state.user.allergens, allergen];
      return { user: { ...state.user, allergens } };
    }),

  recalculateBMR: () =>
    set((state) => {
      const { gender, weight, height, age, activityMultiplier } = state.user;
      const bmr = computeBMR(gender, weight, height, age);
      const tdee = Math.round(bmr * activityMultiplier);
      const bmi = Math.round((weight / ((height / 100) ** 2)) * 10) / 10;
      return { user: { ...state.user, bmr, tdee, bmi } };
    }),

  // ── Dashboard ──
  dailyNutrition: { ...DAILY_NUTRITION },
  todayMeals: [...TODAY_MEALS],
  healthAlerts: [...HEALTH_ALERTS],

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
        warnings: d.warnings,
      }));

      const updatedMeals = [...state.todayMeals, ...newMeals];
      const totalCal = Math.round(updatedMeals.reduce((s, m) => s + m.calories, 0));
      const totalProtein = Math.round(updatedMeals.reduce((s, m) => s + m.protein, 0));
      const totalCarbs = Math.round(updatedMeals.reduce((s, m) => s + m.carbs, 0));
      const totalFat = Math.round(updatedMeals.reduce((s, m) => s + m.fat, 0));
      const totalSodium = Math.round(updatedMeals.reduce((s, m) => s + m.sodium, 0));
      const totalFiber = Math.round(updatedMeals.reduce((s, m) => s + m.fiber, 0));

      return {
        todayMeals: updatedMeals,
        dailyNutrition: {
          ...state.dailyNutrition,
          calories: { ...state.dailyNutrition.calories, current: totalCal },
          protein: { ...state.dailyNutrition.protein, current: totalProtein },
          carbs: { ...state.dailyNutrition.carbs, current: totalCarbs },
          fat: { ...state.dailyNutrition.fat, current: totalFat },
          sodium: { ...state.dailyNutrition.sodium, current: totalSodium },
          fiber: { ...state.dailyNutrition.fiber, current: totalFiber },
        },
        user: { ...state.user, totalMeals: state.user.totalMeals + newMeals.length },
      };
    }),

  replaceDashboardFromRecords: (records) =>
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
              source: record.source,
              warnings: [],
            }];

        return foods.map((food, foodIndex) => ({
          id: `record_${record.timestamp}_${recordIndex}_${foodIndex}`,
          name: food.name || '未命名食品',
          calories: Number(food.calories || 0),
          time: formatRecordTime(record.timestamp),
          mealType: normalizeMealType(record.meal_type),
          emoji: getSourceEmoji(food.source || record.source),
          protein: Number(food.protein || 0),
          carbs: Number(food.carbs || 0),
          fat: Number(food.fat || 0),
          sodium: Number(food.sodium || 0),
          fiber: Number(food.fiber || 0),
          warnings: food.warnings || [],
        }));
      });

      const totals = sumMeals(todayMeals);
      const healthAlerts = buildHealthAlerts(totals, state.dailyNutrition.sodium.target, state.dailyNutrition.protein.target);

      return {
        todayMeals,
        healthAlerts,
        dailyNutrition: {
          ...state.dailyNutrition,
          calories: { ...state.dailyNutrition.calories, current: totals.calories, target: state.user.dailyCalorieTarget },
          protein: { ...state.dailyNutrition.protein, current: totals.protein },
          carbs: { ...state.dailyNutrition.carbs, current: totals.carbs },
          fat: { ...state.dailyNutrition.fat, current: totals.fat },
          sodium: { ...state.dailyNutrition.sodium, current: totals.sodium },
          fiber: { ...state.dailyNutrition.fiber, current: totals.fiber },
        },
        user: { ...state.user, totalMeals: Math.max(state.user.totalMeals, todayMeals.length) },
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
function getAutoMealType(): '早餐' | '午餐' | '晚餐' | '點心' {
  const h = new Date().getHours();
  if (h < 10) return '早餐';
  if (h < 14) return '午餐';
  if (h < 17) return '點心';
  return '晚餐';
}

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
  };
}

function normalizeMealType(mealType?: string): '早餐' | '午餐' | '晚餐' | '點心' {
  if (mealType === '早餐' || mealType === '午餐' || mealType === '晚餐' || mealType === '點心') {
    return mealType;
  }
  return '點心';
}

function formatRecordTime(timestamp?: string): string {
  if (!timestamp) return '--:--';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    const match = timestamp.match(/T(\d{2}:\d{2})/);
    return match?.[1] || '--:--';
  }
  return date.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' });
}

function getSourceEmoji(source?: string): string {
  if (source === 'manual') return '🔎';
  if (source === 'nutrition-label') return '🏷️';
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
  };
}

function buildHealthAlerts(totals: ReturnType<typeof sumMeals>, sodiumTarget: number, proteinTarget: number): HealthAlert[] {
  const alerts: HealthAlert[] = [];
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
