import type { DetectedFood } from '@/constants/mock-data';
import type { ApiAuth } from '@/lib/api';


function buildHeaders(auth?: ApiAuth, contentType?: string): HeadersInit {
  const headers: Record<string, string> = {};
  if (contentType) headers['Content-Type'] = contentType;
  if (auth?.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`;
  return headers;
}

export function normalizeImageBase64(value: string): string {
  const trimmed = value.trim();
  const dataUri = trimmed.match(/^data:image\/(?:png|jpe?g|gif|webp);base64,([\s\S]*)$/i);
  const payload = (dataUri?.[1] ?? trimmed).replace(/\s/g, '');

  if (!payload || (trimmed.startsWith('data:') && !dataUri)) {
    throw new Error('圖片資料格式不正確，請重新拍照或選擇另一張圖片');
  }

  return payload;
}

export type RejectedDetection = {
  label: string;
  confidence: number;
  reason: string;
  search_hints?: string[];
};

export type OCRDraft = {
  product_name?: string;
  brand?: string;
  serving_size_g?: number;
  servings_per_container?: number;
  nutrition_per_serving?: {
    calories?: number;
    protein?: number;
    carbs?: number;
    fat?: number;
    sodium?: number;
    fiber?: number;
    sugar?: number;
  };
  nutrition_per_100g?: Record<string, number | null>;
  ocr_text?: string;
};

type OCRSuggestedCustomFood = Omit<OCRDraft, 'product_name'> & {
  name_zh?: string;
  product_name?: string;
};

type NutritionLabelOCRResponse = OCRDraft & {
  error?: string;
  suggested_custom_food?: OCRSuggestedCustomFood;
};

export const DEFAULT_OCR_FOOD_NAME = '未命名食品';
export const FOOD_NAME_REQUIRED_MESSAGE = '請輸入食物名稱';

export function normalizeFoodName(value?: string | null): string {
  return (value || '').trim();
}

function mapApiDetections(detections: any[]): DetectedFood[] {
  return detections.map((d: any, i: number) => ({
    id: `det_${Date.now()}_${i}`,
    foodName: d.name_zh || d.label,
    confidence: Math.round((d.confidence || 0) * 1000) / 10,
    source: d.source,
    needsConfirmation: d.needs_confirmation || false,
    boundingBox: d.bounding_box,
    estimatedWeight: d.estimated_weight_g,
    originalEstimatedWeight: d.estimated_weight_g,
    portionRange: d.portion_range_g ? {
      minG: d.portion_range_g.min_g,
      maxG: d.portion_range_g.max_g,
      uncertaintyPercent: d.portion_range_g.uncertainty_percent,
    } : undefined,
    portionEstimationMethod: d.portion_estimation_method,
    reliability: d.reliability ? {
      level: d.reliability.level,
      score: d.reliability.score,
      reasons: d.reliability.reasons || [],
    } : undefined,
    nutrition: d.nutrition,
    originalNutrition: d.nutrition,
    gi: d.gi || 'medium',
    allergens: d.allergens || [],
    warnings: d.warnings || [],
  }));
}

export async function runPrediction(params: {
  apiBaseUrl: string;
  imageBase64: string;
  healthConditions: string[];
  allergens: string[];
  userId?: string;
  auth?: ApiAuth;
}): Promise<{ detections: DetectedFood[]; rejectedDetections: RejectedDetection[] }> {
  const body = {
    image: normalizeImageBase64(params.imageBase64),
    health_conditions: params.healthConditions,
    allergens: params.allergens,
    user_id: params.userId,
  };

  const resp = await fetch(`${params.apiBaseUrl}/predict/vision-food`, {
    method: 'POST',
    headers: buildHeaders(params.auth, 'application/json'),
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || 'Gemini 食物辨識失敗');
  }
  return {
    detections: mapApiDetections(data.detections || []),
    rejectedDetections: data.rejected_detections || [],
  };
}

type SaveRecordParams = {
  apiBaseUrl: string;
  userId: string;
  clientRecordId?: string;
  foods: DetectedFood[];
  source: 'camera' | 'manual' | 'nutrition-label';
  auth?: ApiAuth;
};

const inFlightRecordRequests = new Map<string, Promise<void>>();

export async function saveRecord(params: SaveRecordParams): Promise<void> {
  const requestKey = params.clientRecordId
    ? `${params.apiBaseUrl}:${params.userId}:${params.clientRecordId}`
    : null;
  const existingRequest = requestKey ? inFlightRecordRequests.get(requestKey) : undefined;
  if (existingRequest) return existingRequest;

  const request = performSaveRecord(params);
  if (requestKey) inFlightRecordRequests.set(requestKey, request);

  try {
    await request;
  } finally {
    if (requestKey && inFlightRecordRequests.get(requestKey) === request) {
      inFlightRecordRequests.delete(requestKey);
    }
  }
}

async function performSaveRecord(params: SaveRecordParams): Promise<void> {
  if (params.foods.length === 0) return;
  const normalizedFoods = params.foods.map((food) => ({
    ...food,
    foodName: normalizeFoodName(food.foodName),
  }));
  if (normalizedFoods.some((food) => !food.foodName)) {
    throw new Error(FOOD_NAME_REQUIRED_MESSAGE);
  }
  const totalCalories = params.foods.reduce((sum, item) => sum + item.nutrition.calories, 0);
  const totalProtein = params.foods.reduce((sum, item) => sum + item.nutrition.protein, 0);
  const totalCarbs = params.foods.reduce((sum, item) => sum + item.nutrition.carbs, 0);
  const totalFat = params.foods.reduce((sum, item) => sum + item.nutrition.fat, 0);
  const totalSodium = params.foods.reduce((sum, item) => sum + item.nutrition.sodium, 0);
  const totalFiber = params.foods.reduce((sum, item) => sum + item.nutrition.fiber, 0);

  const resp = await fetch(`${params.apiBaseUrl}/record`, {
    method: 'POST',
    headers: buildHeaders(params.auth, 'application/json'),
    body: JSON.stringify({
      user_id: params.userId,
      client_record_id: params.clientRecordId,
      meal_type: '點心',
      foods: normalizedFoods.map((food) => ({
        name: food.foodName,
        calories: food.nutrition.calories,
        protein: food.nutrition.protein,
        carbs: food.nutrition.carbs,
        fat: food.nutrition.fat,
        sodium: food.nutrition.sodium,
        fiber: food.nutrition.fiber,
        source: food.source || params.source,
        warnings: food.warnings,
      })),
      total_calories: Math.round(totalCalories),
      total_protein: Math.round(totalProtein * 10) / 10,
      total_carbs: Math.round(totalCarbs * 10) / 10,
      total_fat: Math.round(totalFat * 10) / 10,
      total_sodium: Math.round(totalSodium),
      total_fiber: Math.round(totalFiber * 10) / 10,
      source: params.source,
    }),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.error || '飲食紀錄同步失敗');
  }
}

export async function manualSearchFood(params: {
  apiBaseUrl: string;
  keyword: string;
  limit?: number;
  userId?: string;
  auth?: ApiAuth;
}): Promise<DetectedFood[]> {
  const query = new URLSearchParams({
    q: params.keyword,
    limit: String(params.limit || 6),
  });
  if (params.userId) query.set('user_id', params.userId);
  const resp = await fetch(`${params.apiBaseUrl}/search/food?${query.toString()}`, {
    headers: buildHeaders(params.auth),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || '搜尋失敗');
  }
  return (data.results || []).map((food: any, index: number) => ({
    id: `manual_${Date.now()}_${index}`,
    foodName: food.name_zh,
    confidence: 100,
    source: food.source || 'TFDA-search',
    needsConfirmation: false,
    boundingBox: { x: 0, y: 0, w: 0, h: 0 },
    estimatedWeight: 100,
    portionRange: { minG: 100, maxG: 100, uncertaintyPercent: 0 },
    portionEstimationMethod: 'manual_tfda_100g',
    reliability: {
      level: 'high',
      score: 1,
      reasons: ['使用者手動選擇 TFDA 食品資料', '營養值以每 100g 顯示，份量仍需自行校正'],
    },
    nutrition: {
      calories: food.calories || 0,
      protein: food.protein || 0,
      carbs: food.carbs || 0,
      fat: food.fat || 0,
      sodium: food.sodium || 0,
      fiber: food.fiber || 0,
    },
    gi: 'medium',
    allergens: [],
    warnings: ['手動搜尋結果，份量暫以 100g 顯示'],
  }));
}

export async function runNutritionLabelOCR(params: {
  apiBaseUrl: string;
  imageBase64: string;
}): Promise<OCRDraft> {
  const resp = await fetch(`${params.apiBaseUrl}/ocr/nutrition-label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image: normalizeImageBase64(params.imageBase64) }),
  });
  const data = await resp.json() as NutritionLabelOCRResponse;
  if (!resp.ok) {
    throw new Error(data.error || '營養標示辨識失敗');
  }
  const suggestedFood = data.suggested_custom_food;
  const draft = suggestedFood || data;
  return {
    ...draft,
    product_name: normalizeFoodName(
      suggestedFood?.name_zh || suggestedFood?.product_name || data.product_name
    ) || DEFAULT_OCR_FOOD_NAME,
  };
}

export async function saveCustomFood(params: {
  apiBaseUrl: string;
  userId: string;
  draft: OCRDraft;
  auth?: ApiAuth;
}) {
  const foodName = normalizeFoodName(params.draft.product_name);
  if (!foodName) {
    throw new Error(FOOD_NAME_REQUIRED_MESSAGE);
  }
  const resp = await fetch(`${params.apiBaseUrl}/custom-food`, {
    method: 'POST',
    headers: buildHeaders(params.auth, 'application/json'),
    body: JSON.stringify({
      user_id: params.userId,
      name_zh: foodName,
      brand: params.draft.brand,
      serving_size_g: params.draft.serving_size_g,
      servings_per_container: params.draft.servings_per_container,
      nutrition_per_serving: params.draft.nutrition_per_serving,
      nutrition_per_100g: params.draft.nutrition_per_100g,
      ocr_text: params.draft.ocr_text,
      source: 'nutrition-label-ocr',
    }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || '儲存自訂食品失敗');
  }
  return data;
}

export function buildOCRDetectedFood(draft: OCRDraft): DetectedFood {
  const foodName = normalizeFoodName(draft.product_name);
  if (!foodName) {
    throw new Error(FOOD_NAME_REQUIRED_MESSAGE);
  }
  return {
    id: `ocr_${Date.now()}`,
    foodName,
    confidence: 100,
    source: 'nutrition-label-ocr',
    needsConfirmation: false,
    boundingBox: { x: 0, y: 0, w: 0, h: 0 },
    estimatedWeight: draft.serving_size_g || 100,
    portionRange: { minG: draft.serving_size_g || 100, maxG: draft.serving_size_g || 100, uncertaintyPercent: 0 },
    portionEstimationMethod: 'nutrition_label_serving_size',
    reliability: {
      level: 'medium',
      score: 0.8,
      reasons: ['使用 Gemini OCR 讀取營養標示', '仍需人工核對包裝文字與每份重量'],
    },
    nutrition: {
      calories: Number(draft.nutrition_per_serving?.calories || 0),
      protein: Number(draft.nutrition_per_serving?.protein || 0),
      carbs: Number(draft.nutrition_per_serving?.carbs || 0),
      fat: Number(draft.nutrition_per_serving?.fat || 0),
      sodium: Number(draft.nutrition_per_serving?.sodium || 0),
      fiber: Number(draft.nutrition_per_serving?.fiber || 0),
    },
    gi: 'medium',
    allergens: [],
    warnings: ['營養標示 OCR 結果，建議人工核對後再長期使用'],
  };
}
