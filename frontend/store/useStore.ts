/**
 * NutriLens Global State — Zustand Store
 * Manages user profile, dietary records, scan results, and app settings
 */

import { create } from 'zustand';
import type { DetectedFood, MealEntry, HealthAlert, DailyRecord } from '@/constants/mock-data';
import {
  DAILY_NUTRITION,
  TODAY_MEALS,
  HEALTH_ALERTS,
  USER_PROFILE,
  WEEKLY_HISTORY,
  WEEKLY_SUMMARY,
  RECOMMENDED_MEALS,
  FILTERED_UNSAFE_MEALS,
  AVAILABLE_CONDITIONS,
  AVAILABLE_ALLERGENS,
} from '@/constants/mock-data';

// ─── Types ──────────────────────────────────────────────────
export interface UserProfile {
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
  toggleCondition: (condition: string) => void;
  toggleAllergen: (allergen: string) => void;
  recalculateBMR: () => void;

  // Dashboard
  dailyNutrition: typeof DAILY_NUTRITION;
  todayMeals: MealEntry[];
  healthAlerts: HealthAlert[];
  addMealFromScan: (detections: DetectedFood[]) => void;

  // Scanner
  scanResult: ScanResult;
  setScanResult: (detections: DetectedFood[]) => void;
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

  // ── Scanner ──
  scanResult: { isScanning: false, detections: [], timestamp: null },

  setScanResult: (detections) =>
    set({
      scanResult: {
        isScanning: false,
        detections,
        timestamp: new Date().toISOString(),
      },
    }),

  clearScan: () =>
    set({ scanResult: { isScanning: false, detections: [], timestamp: null } }),

  setScanning: (v) =>
    set((state) => ({ scanResult: { ...state.scanResult, isScanning: v } })),

  // ── Camera active flag ──
  isCameraActive: false,
  setCameraActive: (v) => set({ isCameraActive: v }),

  // ── API ──
  apiBaseUrl: 'http://localhost:5000',
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
