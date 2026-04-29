import type { DetectedFood } from '@/constants/mock-data';

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
}): Promise<{ detections: DetectedFood[]; rejectedDetections: RejectedDetection[] }> {
  const resp = await fetch(`${params.apiBaseUrl}/predict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image: params.imageBase64,
      health_conditions: params.healthConditions,
      allergens: params.allergens,
    }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || '辨識失敗');
  }
  return {
    detections: mapApiDetections(data.detections || []),
    rejectedDetections: data.rejected_detections || [],
  };
}

export async function saveRecord(params: {
  apiBaseUrl: string;
  userId: string;
  foods: DetectedFood[];
  source: 'camera' | 'manual' | 'nutrition-label';
}) {
  if (params.foods.length === 0) return;
  const totalCalories = params.foods.reduce((sum, item) => sum + item.nutrition.calories, 0);
  const totalProtein = params.foods.reduce((sum, item) => sum + item.nutrition.protein, 0);
  const totalCarbs = params.foods.reduce((sum, item) => sum + item.nutrition.carbs, 0);
  const totalFat = params.foods.reduce((sum, item) => sum + item.nutrition.fat, 0);
  const totalSodium = params.foods.reduce((sum, item) => sum + item.nutrition.sodium, 0);
  const totalFiber = params.foods.reduce((sum, item) => sum + item.nutrition.fiber, 0);

  await fetch(`${params.apiBaseUrl}/record`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: params.userId,
      meal_type: '點心',
      foods: params.foods.map((food) => ({
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
}

export async function manualSearchFood(params: {
  apiBaseUrl: string;
  keyword: string;
  limit?: number;
}): Promise<DetectedFood[]> {
  const resp = await fetch(`${params.apiBaseUrl}/search/food?q=${encodeURIComponent(params.keyword)}&limit=${params.limit || 6}`);
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
    body: JSON.stringify({ image: params.imageBase64 }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || '營養標示辨識失敗');
  }
  return data.suggested_custom_food || data;
}

export async function saveCustomFood(params: {
  apiBaseUrl: string;
  userId: string;
  draft: OCRDraft;
}) {
  const resp = await fetch(`${params.apiBaseUrl}/custom-food`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: params.userId,
      name_zh: params.draft.product_name,
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
  return {
    id: `ocr_${Date.now()}`,
    foodName: draft.product_name || '營養標示食品',
    confidence: 100,
    source: 'nutrition-label-ocr',
    needsConfirmation: false,
    boundingBox: { x: 0, y: 0, w: 0, h: 0 },
    estimatedWeight: draft.serving_size_g || 100,
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
