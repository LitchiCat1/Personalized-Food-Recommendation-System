import type { DetectedFood } from '@/constants/mock-data';
import type { ApiAuth } from '@/lib/api';
import type { MealType } from '@/lib/meal';
import type { NutritionEnrichmentItem, NutritionEnrichmentResponse, NutritionScanContext } from '@/lib/nutrition-enrichment-api';
import type { NutritionFdcCandidateSnapshotResponse } from '@/lib/nutrition-fdc-candidate-api';


// 後端回 401 時通知 AuthGate 帶回登入畫面（事件名稱見 lib/auth.ts 的 UNAUTHORIZED_EVENT）。
// 這個檔案會被 Node 的測試直接載入，不能 import 只有 App 裡才解析得到的模組。
function reportIfUnauthorized(resp: Response, isCurrentSession?: () => boolean) {
  if (resp.status === 401 && (!isCurrentSession || isCurrentSession())
    && typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event('nutrilens:unauthorized'));
  }
}

function buildHeaders(auth?: ApiAuth, contentType?: string): HeadersInit {
  const headers: Record<string, string> = {};
  if (contentType) headers['Content-Type'] = contentType;
  if (auth?.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`;
  return headers;
}

// 後端逾時、502 時回的是 HTML，直接 resp.json() 會丟出 "Unexpected token '<'"，
// 畫面上只剩一句看不懂的英文。讀不到 JSON 就當作沒有內容，改用狀態碼說明。
async function readJson(resp: Response): Promise<any> {
  return resp.json().catch(() => ({}));
}

function failureMessage(resp: Response, data: any, fallback: string): string {
  return data?.error || `${fallback}（HTTP ${resp.status}）`;
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
  item_id?: string;
  label: string;
  confidence: number;
  reason: string;
  search_hints?: string[];
  recognition_status?: 'recognized';
  nutrition_status?: 'unmatched';
};

export function formatReviewedPendingFoods(
  items: RejectedDetection[], snapshot: NutritionFdcCandidateSnapshotResponse | null,
): RejectedDetection[] {
  if (!snapshot?.selection) return items;
  const matched = new Set(snapshot.selection.items
    .filter((item) => item.reason === 'reviewed_match')
    .map((item) => item.item_id));
  return items.map((item) => item.item_id && matched.has(item.item_id) &&
    item.recognition_status === 'recognized' && item.nutrition_status === 'unmatched'
    ? { ...item, reason: '已找到相容的 USDA 參考營養；請在下方確認名稱與估計份量，尚未計入營養合計。', search_hints: [] }
    : item);
}

export function formatScannerSourceBadge(sources: Array<string | undefined>, pendingCount = 0): string {
  const labels = new Set<string>();
  for (const value of sources) {
    const source = String(value || '').trim().toLowerCase();
    if (!source) continue;
    if (source === 'tfda' || source === 'tfda-search') labels.add('TFDA');
    else if (source.includes('usda')) labels.add('USDA');
    else if (source === 'custom' || source === 'custom-food') labels.add('自訂');
    else if (source.startsWith('web:')) labels.add('網路');
    else labels.add('其他');
  }
  if (labels.size > 0) return Array.from(labels).join(' + ');
  return pendingCount > 0 ? '待營養配對' : '資料來源';
}

export function formatScannerResultTitle(matchedCount: number, pendingCount: number): string | null {
  if (matchedCount > 0) return `已配對 ${matchedCount} 項營養資料`;
  if (pendingCount > 0) return `${pendingCount} 項食物待確認`;
  return null;
}

export function hasReviewableNutritionMiss(
  rejectedDetections: RejectedDetection[],
  scanContext: NutritionScanContext | null,
): boolean {
  if (!scanContext) return false;
  const validItemIds = new Set(scanContext.items
    .filter((item) => item.validation_issues.length === 0)
    .map((item) => item.item_id));
  return rejectedDetections.some((item) => item.recognition_status === 'recognized' &&
    item.nutrition_status === 'unmatched' && typeof item.item_id === 'string' && validItemIds.has(item.item_id));
}

export function getUserConfirmableIdentityItems(
  rejectedDetections: RejectedDetection[],
  scanContext: NutritionScanContext | null,
): NutritionEnrichmentItem[] {
  if (!scanContext) return [];
  const rejectedIds = new Set(rejectedDetections
    .map((item) => item.item_id).filter((value): value is string => typeof value === 'string'));
  const knownValues = {
    food_state: new Set(['prepared', 'raw', 'dry']),
    preparation_method: new Set(['boiled', 'stir_fried', 'pan_fried', 'deep_fried', 'roasted', 'braised', 'steamed', 'mixed']),
    components_scope: new Set(['food_only', 'noodles_only', 'whole_dish_with_broth', 'with_sides']),
  };
  return scanContext.items.filter((item) => item.identity_confirmation_required === true &&
    rejectedIds.has(item.item_id) && item.validation_issues.length === 0 &&
    knownValues.food_state.has(item.food_state || '') &&
    knownValues.preparation_method.has(item.preparation_method || '') &&
    knownValues.components_scope.has(item.components_scope || ''));
}

export function hasUserConfirmableIdentity(
  rejectedDetections: RejectedDetection[],
  scanContext: NutritionScanContext | null,
): boolean {
  return getUserConfirmableIdentityItems(rejectedDetections, scanContext).length > 0;
}

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
    saturated_fat?: number;
    trans_fat?: number;
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
    // Keep the server-owned item ID so a later enrichment response can be
    // joined without trusting a client-generated index or timestamp.
    id: typeof d.item_id === 'string' && d.item_id.trim() ? d.item_id : `det_${Date.now()}_${i}`,
    foodName: d.name_zh || d.label,
    confidence: Math.round((d.confidence || 0) * 1000) / 10,
    source: d.source,
    needsConfirmation: d.needs_confirmation || false,
    missingNutritionFields: d.missing_nutrition_fields || [],
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

function mapScanContext(value: any): NutritionScanContext | null {
  if (!value || value.status !== 'persisted' || typeof value.scan_id !== 'string'
      || !Number.isSafeInteger(value.scan_revision) || value.scan_revision < 0
      || !Array.isArray(value.items) || value.items.length === 0) {
    return null;
  }
  const items: NutritionEnrichmentItem[] = [];
  for (const item of value.items) {
    if (!item || typeof item !== 'object' || typeof item.item_id !== 'string'
        || !Number.isSafeInteger(item.item_revision) || item.item_revision < 0
        || typeof item.name_zh !== 'string' || !Array.isArray(item.validation_issues)) {
      return null;
    }
    if (item.identity_confirmation_required !== undefined
        && typeof item.identity_confirmation_required !== 'boolean') return null;
    if (item.identity_confirmation_source !== undefined && item.identity_confirmation_source !== 'user') return null;
    if (item.identity_confirmation_id !== undefined &&
        (typeof item.identity_confirmation_id !== 'string' || !item.identity_confirmation_id.trim())) return null;
    if ((item.identity_confirmation_source === 'user') !== (item.identity_confirmation_id !== undefined) ||
        (item.identity_confirmation_source === 'user' && item.identity_confirmation_required !== false)) return null;
    const numeric = (candidate: unknown): number | null =>
      candidate === null || candidate === undefined
        ? null
        : typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : Number.NaN;
    const confidence = numeric(item.confidence);
    const weightConfidence = numeric(item.weight_confidence);
    const estimatedWeight = numeric(item.estimated_weight_g);
    if ([confidence, weightConfidence, estimatedWeight].some((candidate) => Number.isNaN(candidate))) {
      return null;
    }
    items.push({
      item_id: item.item_id,
      item_revision: item.item_revision,
      name_zh: item.name_zh,
      confidence,
      weight_confidence: weightConfidence,
      estimated_weight_g: estimatedWeight,
      food_state: typeof item.food_state === 'string' ? item.food_state : null,
      preparation_method: typeof item.preparation_method === 'string' ? item.preparation_method : null,
      components_scope: typeof item.components_scope === 'string' ? item.components_scope : null,
      brand: typeof item.brand === 'string' ? item.brand : null,
      variant: typeof item.variant === 'string' ? item.variant : null,
      validation_issues: item.validation_issues.filter((issue: unknown): issue is string => typeof issue === 'string'),
      ...(typeof item.identity_confirmation_required === 'boolean'
        ? { identity_confirmation_required: item.identity_confirmation_required } : {}),
      ...(item.identity_confirmation_source === 'user'
        ? { identity_confirmation_source: 'user' as const } : {}),
      ...(typeof item.identity_confirmation_id === 'string'
        ? { identity_confirmation_id: item.identity_confirmation_id } : {}),
    });
  }
  return {
    status: 'persisted',
    scan_id: value.scan_id,
    scan_revision: value.scan_revision,
    items,
    ...(typeof value.expires_at === 'string' ? { expires_at: value.expires_at } : {}),
    ...(typeof value.authority_token === 'string' && value.authority_token.trim()
      ? { authority_token: value.authority_token } : {}),
  };
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function enrichedFood(item: any, existing?: DetectedFood): DetectedFood | null {
  if (!item || typeof item !== 'object' || typeof item.item_id !== 'string'
      || !item.portion || typeof item.portion !== 'object') return null;
  const values = item.portion.values;
  if (!values || typeof values !== 'object'
      || !['calories', 'protein', 'carbs', 'fat', 'sodium'].every((key) => finite(values[key]))
      || (!existing && !finite(values.fiber))) {
    // A partial profile is deliberately left unresolved. The legacy scanner
    // must not turn missing point values into invented zeroes.
    return null;
  }
  const context = item.recognition_context && typeof item.recognition_context === 'object'
    ? item.recognition_context : {};
  // A nutrition profile without a server-owned positive weight cannot be
  // turned into a recordable food.  In particular, never invent 100g for a
  // missing portion because that would make the displayed nutrients look
  // precise while silently applying the wrong serving size.
  const hasPortionWeight = Object.prototype.hasOwnProperty.call(item.portion, 'weight_g')
    && item.portion.weight_g !== null && item.portion.weight_g !== undefined;
  const portionWeight = hasPortionWeight && finite(item.portion.weight_g) && item.portion.weight_g > 0
    ? item.portion.weight_g : null;
  if (hasPortionWeight && portionWeight === null) return null;
  const contextWeight = finite(context.estimated_weight_g) && context.estimated_weight_g > 0
    ? context.estimated_weight_g : null;
  const estimatedWeight = portionWeight ?? contextWeight;
  if (estimatedWeight === null) return null;
  const sourceDetails = item.nutrition_profile?.source_details;
  const sourceId = sourceDetails && typeof sourceDetails.source_id === 'string'
    ? sourceDetails.source_id : null;
  const localSource = sourceDetails && typeof sourceDetails.source === 'string' ? sourceDetails.source : null;
  const source = item.origin === 'web' ? `web:${sourceId || 'reviewed-source'}`
    : item.origin === 'local' ? (localSource || existing?.source || 'local-nutrition')
      : (existing?.source || 'nutrition-enrichment');
  const nutrition = {
    calories: values.calories,
    protein: values.protein,
    carbs: values.carbs,
    fat: values.fat,
    sodium: values.sodium,
    // Keep the existing numeric snapshot when the enrichment source omits an
    // optional field. This preserves arithmetic safety and the original
    // evidence while missingNutritionFields still tells the UI the value is
    // not supplied by the new profile.
    fiber: finite(values.fiber) ? values.fiber : existing?.nutrition.fiber,
    sugar: finite(values.sugar) ? values.sugar : existing?.nutrition.sugar,
    saturated_fat: finite(values.saturated_fat) ? values.saturated_fat : existing?.nutrition.saturated_fat,
    trans_fat: finite(values.trans_fat) ? values.trans_fat : existing?.nutrition.trans_fat,
    is_fried: existing?.nutrition.is_fried,
  };
  const missing = Array.isArray(item.portion.missing_nutrition_fields)
    ? item.portion.missing_nutrition_fields.filter((value: unknown): value is string => typeof value === 'string') : [];
  const warning = item.origin === 'web'
    ? '營養資料由已核准的網路來源補全，仍請確認食物名稱與份量'
    : '營養資料已由伺服器資料層重新計算';
  if (existing) {
    return {
      ...existing,
      source,
      nutrition,
      missingNutritionFields: missing,
      needsConfirmation: existing.needsConfirmation || item.status !== 'accepted' && item.status !== 'complete',
      warnings: [...new Set([...(existing.warnings || []), warning])],
    };
  }
  const confidence = finite(context.confidence) ? context.confidence : 0;
  return {
    id: item.item_id,
    foodName: typeof item.original_visual_name === 'string' ? item.original_visual_name : (context.name_zh || '未命名食品'),
    confidence: Math.round(confidence * 1000) / 10,
    source,
    needsConfirmation: item.status !== 'accepted' && item.status !== 'complete',
    missingNutritionFields: missing,
    boundingBox: { x: 0, y: 0, w: 0, h: 0 },
    estimatedWeight,
    originalEstimatedWeight: estimatedWeight,
    portionEstimationMethod: 'server_nutrition_enrichment',
    reliability: { level: item.origin === 'web' ? 'medium' : 'high', score: confidence, reasons: [warning] },
    nutrition,
    originalNutrition: nutrition,
    gi: 'medium',
    allergens: [],
    warnings: [warning],
  };
}

/** Merge only complete point-value portions; unresolved items remain visible. */
export function mergeNutritionEnrichmentResult(
  detections: DetectedFood[], response: NutritionEnrichmentResponse | null,
): DetectedFood[] {
  const items = response?.result?.items;
  if (!Array.isArray(items)) return detections;
  const existingIds = new Set(detections.map((food) => food.id));
  const merged = detections.map((food) => {
    const item = items.find((candidate) => candidate && typeof candidate === 'object' && candidate.item_id === food.id);
    return enrichedFood(item, food) || food;
  });
  for (const item of items) {
    if (!item || typeof item !== 'object' || typeof item.item_id !== 'string' || existingIds.has(item.item_id)) continue;
    const food = enrichedFood(item);
    if (food) merged.push(food);
  }
  return merged;
}

export async function runPrediction(params: {
  apiBaseUrl: string;
  imageBase64: string;
  healthConditions: string[];
  allergens: string[];
  userId?: string;
  auth?: ApiAuth;
  isCurrentSession?: () => boolean;
}): Promise<{
  detections: DetectedFood[];
  rejectedDetections: RejectedDetection[];
  mealWarnings: string[];
  scanContext: NutritionScanContext | null;
}> {
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
  reportIfUnauthorized(resp, params.isCurrentSession);
  const data = await readJson(resp);
  if (!resp.ok) {
    throw new Error(failureMessage(resp, data, 'Gemini 食物辨識失敗'));
  }
  return {
    detections: mapApiDetections(data.detections || []),
    rejectedDetections: data.rejected_detections || [],
    // 每道菜單獨都在額度內、加起來卻超過整餐上限的提醒
    mealWarnings: data.meal_warnings || [],
    scanContext: mapScanContext(data.scan_context),
  };
}

type SaveRecordParams = {
  apiBaseUrl: string;
  userId: string;
  clientRecordId?: string;
  foods: DetectedFood[];
  source: 'camera' | 'manual' | 'nutrition-label';
  auth?: ApiAuth;
  /**
   * 這一餐是哪一餐，由呼叫端指定——這裡不自己猜。
   *
   * 原本寫死「點心」，畫面上先顯示依時間判定的「早餐」，重新同步後又變回
   * 「點心」。改成必填是因為正確答案取決於「這筆紀錄何時發生」，只有呼叫端
   * 知道：離線佇列補送時要用當初入列的時間，不是送出的時間。
   */
  mealType: MealType;
  /**
   * 這一餐吃的時間（帶時區偏移）。不帶就由後端用收到的時間。
   *
   * 離線佇列補送時一定要帶：23:50 排隊的晚餐隔天早上才送出，不帶的話會被存成
   * 隔天早上，算進隔天的熱量與鈉。
   */
  timestamp?: string;
  isCurrentSession?: () => boolean;
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
  const totalSugar = params.foods.reduce((sum, item) => sum + (item.nutrition.sugar || 0), 0);
  const totalFat = params.foods.reduce((sum, item) => sum + item.nutrition.fat, 0);
  const totalSaturatedFat = params.foods.reduce((sum, item) => sum + (item.nutrition.saturated_fat || 0), 0);
  const totalTransFat = params.foods.reduce((sum, item) => sum + (item.nutrition.trans_fat || 0), 0);
  const totalSodium = params.foods.reduce((sum, item) => sum + item.nutrition.sodium, 0);
  const totalFiber = params.foods.reduce((sum, item) => sum + item.nutrition.fiber, 0);

  const resp = await fetch(`${params.apiBaseUrl}/record`, {
    method: 'POST',
    headers: buildHeaders(params.auth, 'application/json'),
    body: JSON.stringify({
      user_id: params.userId,
      client_record_id: params.clientRecordId,
      meal_type: params.mealType,
      ...(params.timestamp ? { timestamp: params.timestamp } : {}),
      foods: normalizedFoods.map((food) => ({
        name: food.foodName,
        calories: food.nutrition.calories,
        protein: food.nutrition.protein,
        carbs: food.nutrition.carbs,
        sugar: food.nutrition.sugar || 0,
        fat: food.nutrition.fat,
        saturated_fat: food.nutrition.saturated_fat || 0,
        trans_fat: food.nutrition.trans_fat || 0,
        sodium: food.nutrition.sodium,
        fiber: food.nutrition.fiber,
        is_fried: food.nutrition.is_fried === true,
        source: food.source || params.source,
        warnings: food.warnings,
      })),
      total_calories: Math.round(totalCalories),
      total_protein: Math.round(totalProtein * 10) / 10,
      total_carbs: Math.round(totalCarbs * 10) / 10,
      total_sugar: Math.round(totalSugar * 10) / 10,
      total_fat: Math.round(totalFat * 10) / 10,
      total_saturated_fat: Math.round(totalSaturatedFat * 10) / 10,
      total_trans_fat: Math.round(totalTransFat * 10) / 10,
      total_sodium: Math.round(totalSodium),
      total_fiber: Math.round(totalFiber * 10) / 10,
      source: params.source,
    }),
  });
  reportIfUnauthorized(resp, params.isCurrentSession);
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
  reportIfUnauthorized(resp);
  const data = await readJson(resp);
  if (!resp.ok) {
    throw new Error(failureMessage(resp, data, '搜尋失敗'));
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
      sugar: food.sugar || food.refined_sugar || 0,
      fat: food.fat || 0,
      saturated_fat: food.saturated_fat || 0,
      trans_fat: food.trans_fat || 0,
      sodium: food.sodium || 0,
      fiber: food.fiber || 0,
      is_fried: food.is_fried === true,
    },
    gi: 'medium',
    allergens: [],
    warnings: ['手動搜尋結果，份量暫以 100g 顯示'],
  }));
}

export async function runNutritionLabelOCR(params: {
  apiBaseUrl: string;
  imageBase64: string;
  auth?: ApiAuth;
}): Promise<OCRDraft> {
  const resp = await fetch(`${params.apiBaseUrl}/ocr/nutrition-label`, {
    method: 'POST',
    // 這條會呼叫 Gemini，後端已經改成要驗證，不帶 token 會被擋
    headers: buildHeaders(params.auth, 'application/json'),
    body: JSON.stringify({ image: normalizeImageBase64(params.imageBase64) }),
  });
  reportIfUnauthorized(resp);
  const data = await readJson(resp) as NutritionLabelOCRResponse;
  if (!resp.ok) {
    throw new Error(failureMessage(resp, data, '營養標示辨識失敗'));
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
  reportIfUnauthorized(resp);
  const data = await readJson(resp);
  if (!resp.ok) {
    throw new Error(failureMessage(resp, data, '儲存自訂食品失敗'));
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
      sugar: Number(draft.nutrition_per_serving?.sugar || 0),
      fat: Number(draft.nutrition_per_serving?.fat || 0),
      saturated_fat: Number(draft.nutrition_per_serving?.saturated_fat || 0),
      trans_fat: Number(draft.nutrition_per_serving?.trans_fat || 0),
      sodium: Number(draft.nutrition_per_serving?.sodium || 0),
      fiber: Number(draft.nutrition_per_serving?.fiber || 0),
    },
    gi: 'medium',
    allergens: [],
    warnings: ['營養標示 OCR 結果，建議人工核對後再長期使用'],
  };
}
