export type HistoryDay = {
  date: string;
  record_count?: number;
  calories: number;
  protein: number;
  carbs: number;
  sugar: number;
  fat: number;
  saturated_fat: number;
  trans_fat: number;
  sodium: number;
  fiber: number;
};

export type HistoryResponse = {
  user_id: string;
  days: number;
  daily: HistoryDay[];
  summary: {
    avg_calories?: number;
    avg_protein?: number;
    avg_carbs?: number;
    avg_sugar?: number;
    avg_fat?: number;
    avg_saturated_fat?: number;
    avg_trans_fat?: number;
    avg_sodium?: number;
    avg_fiber?: number;
    recorded_days?: number;
    total_records?: number;
    avg_records_per_day?: number;
  };
};

export type FoodRecordItem = {
  name?: string;
  calories?: number;
  protein?: number;
  carbs?: number;
  fat?: number;
  sodium?: number;
  fiber?: number;
  sugar?: number;
  refined_sugar?: number;
  saturated_fat?: number;
  trans_fat?: number;
  is_fried?: boolean;
  source?: string;
  warnings?: string[];
};

export type DietaryRecord = {
  user_id: string;
  client_record_id?: string;
  timestamp: string;
  meal_type?: string;
  foods?: FoodRecordItem[];
  total_calories?: number;
  total_protein?: number;
  total_carbs?: number;
  total_fat?: number;
  total_sodium?: number;
  total_fiber?: number;
  total_sugar?: number;
  total_refined_sugar?: number;
  total_saturated_fat?: number;
  total_trans_fat?: number;
  contains_fried_food?: boolean;
  source?: string;
};

export type NutritionTargets = {
  calories: number;
  protein: number;
  carbs: number;
  sugar: number;
  fat: number;
  saturated_fat: number;
  trans_fat: number;
  fiber: number;
  sodium: number;
};

/** 每個營養素的目標是「上限」還是「至少要吃到」。同一個數字方向相反，結論就相反。 */
export type NutritionGoalTypes = Partial<Record<keyof NutritionTargets, 'upper_limit' | 'minimum_target'>>;

/**
 * 使用者現在生效的單餐上限，由後端依疾病規則算出。
 *
 * 前端只比大小，不自己抄門檻數字——這個專案已經因為「兩套會各自漂移的
 * 門檻」吃過好幾次虧（見 backend/services/medical_risk_service.py 的門檻
 * 一致性檢查）。
 */
export type MealNutrientLimit = {
  limit: number;
  unit: string;
  label_zh: string;
  /** 是哪些疾病要求這個上限，用來在訊息裡說清楚理由。 */
  conditions: string[];
};

export type MealNutrientLimits = Partial<Record<keyof NutritionTargets, MealNutrientLimit>>;

/** 後端還沒回時的預設方向，與 nutrition_progress_service.NUTRITION_GOAL_TYPES 一致。 */
export const DEFAULT_NUTRITION_GOAL_TYPES = {
  calories: 'upper_limit',
  protein: 'minimum_target',
  carbs: 'upper_limit',
  sugar: 'upper_limit',
  fat: 'upper_limit',
  saturated_fat: 'upper_limit',
  trans_fat: 'upper_limit',
  fiber: 'minimum_target',
  sodium: 'upper_limit',
} as const;

/**
 * 每日熱量目標是怎麼來的。
 *
 * App 裡同時存在三個數字：後端算的 TDEE、使用者自己填的 daily_calorie_target、
 * 以及疾病指引算出的臨床目標。畫面上先前三個混著出現又互相矛盾，
 * 有了 basis 才能只顯示一個生效值，並說明另外兩個為什麼沒被採用。
 */
export type NutritionTargetBasis = {
  /** disease = 疾病指引算出來的；user = 直接採用使用者填的數字。 */
  source: 'disease' | 'user';
  conditions: string[];
  ideal_body_weight: number;
  /** 每公斤理想體重給幾大卡，依活動量分級；source 為 user 時是 null。 */
  kcal_per_kg: number | null;
  activity_multiplier: number;
  bmr: number | null;
  /** 疾病目標算出來低於 BMR，已被抬到 BMR。 */
  floored_at_bmr: boolean;
  user_target: number | null;
  is_overweight: boolean;
};

export type RecordsResponse = {
  records: DietaryRecord[];
  count: number;
  nutrition_targets?: NutritionTargets;
  nutrition_goal_types?: NutritionGoalTypes;
  nutrition_target_basis?: NutritionTargetBasis;
  meal_nutrient_limits?: MealNutrientLimits;
};

export type RecordMutationResponse = {
  message: string;
  record: DietaryRecord;
};

export type CreateDietaryRecordPayload = {
  user_id: string;
  client_record_id: string;
  timestamp: string;
  foods: FoodRecordItem[];
  total_calories: number;
  total_protein: number;
  total_carbs: number;
  total_sugar: number;
  total_fat: number;
  total_saturated_fat: number;
  total_trans_fat: number;
  total_sodium: number;
  total_fiber: number;
  source: 'manual';
};

export type CreateDietaryRecordResponse = RecordMutationResponse & {
  deduplicated: boolean;
};

export type HealthyFoodRecommendation = {
  restaurant_id: string;
  restaurant_name: string;
  restaurant_lat?: number;
  restaurant_lng?: number;
  address?: string;
  // 選填：/restaurant/menu 只收到店家座標，算不出使用者到店距離，不會回這個欄位
  distance_km?: number;
  tags: string[];
  item_id?: string;
  item_name: string;
  price: number;
  calories: number;
  protein: number;
  carbs: number;
  sugar?: number;
  fat: number;
  saturated_fat?: number;
  trans_fat?: number;
  sodium: number;
  fiber?: number;
  is_fried?: boolean;
  gi?: 'low' | 'medium' | 'high' | null;
  match_score: number;
  nutrition_available?: boolean;
  /**
   * 這一道是逐道菜比對過疾病禁忌與過敏原，還是只用店名與店家類型猜的。
   *
   * 回應裡本來只有整體的 venues_with_menu 與一句總結，但使用者看到的是一張
   * 一張的推薦卡——兩種來源長得一模一樣。對一個以「逐道菜比對」為賣點的
   * App，這個差別必須在每一筆上看得見。
   */
  menu_verified?: boolean;
  reasons: string[];
};

export type RestaurantMenuLink = {
  url: string;
  source: 'google_places_website';
};

export type HealthyFoodRestaurant = {
  restaurant_id: string;
  name: string;
  lat: number;
  lng: number;
  address?: string;
  phone?: string;
  google_place_id?: string;
  official_website_url?: string;
  google_maps_url?: string;
  menu_link?: RestaurantMenuLink;
  distance_km: number;
  tags: string[];
  price_level?: number | null;
  // null = 拿不到營業時間。不能當成營業中，那會顯示假的「營業中」。
  is_open: boolean | null;
  rating?: number | null;
  user_ratings_total?: number | null;
  match_score: number;
  data_source?: string;
  nutrition_available?: boolean;
  recommended_items: HealthyFoodRecommendation[];
  filtered_items?: { restaurant_id?: string; restaurant_name: string; item_name: string; reasons: string[] }[];
};

export type HealthyFoodResponse = {
  user_id: string;
  budget: number;
  radius_km?: number;
  category?: string;
  location: { lat: number; lng: number };
  remaining: {
    calories: number;
    protein: number;
    carbs: number;
    fat: number;
    sodium: number;
    fiber?: number;
  };
  recommended: HealthyFoodRecommendation[];
  restaurants?: HealthyFoodRestaurant[];
  filtered_out: { restaurant_name: string; item_name: string; reasons: string[] }[];
  data_source?: string;
  nutrition_available?: boolean;
  nutrition_note?: string;
  // 退回內建示範店家時的警告。先前後端有寫、前端從來沒顯示。
  data_source_warning?: string;
  // 現在沒開的店不推薦，但要讓使用者知道少掉幾家，不然清單變短會像壞掉
  closed_now?: number;
  opening_note?: string | null;
  venues_with_menu?: number;
  calorie_note?: string | null;
};

export type RestaurantAiSummary = {
  restaurant_type: string;
  likely_foods: string[];
  recommended_foods?: { name: string; reason: string }[];
  price_range_twd: { min: number; max: number };
  budget_fit: '適合' | '可能超出' | '不確定';
  health_tips: string[];
  confidence: 'low' | 'medium' | 'high';
  source_note: string;
};

export type RestaurantAiSummaryResponse = {
  summary: RestaurantAiSummary;
};

export type UserProfileResponse = {
  user_id: string;
  name: string;
  gender: 'male' | 'female';
  height: number;
  weight: number;
  age: number;
  activity_level: string;
  activity_multiplier: number;
  bmi: number;
  bmr: number;
  tdee: number;
  daily_calorie_target: number;
  health_conditions: string[];
  allergens: string[];
  target_weight?: number;
  diet_type: string;
  /** 使用者是否自己填過這份檔案；新帳號的空白檔案是 false。 */
  profile_complete?: boolean;
};

export type MedicalConditionRule = {
  id: string;
  condition: string;
  label_zh: string;
  aliases: string[];
  category?: string | null;
  description: string;
  screening_focus: string[];
  severity_options: string[];
  rule_version?: string | null;
  review_status?: string | null;
  last_reviewed?: string | null;
  reviewed_by?: string | null;
  evidence_level?: string | null;
  references: { title: string; url: string }[];
  medical_disclaimer?: string | null;
  limits: Record<string, unknown>;
  risk_nutrients: Record<string, { caution?: number; block?: number; unit?: string; label_zh?: string }>;
};

export type AllergenGroup = {
  id: string;
  label_zh: string;
  severity: 'high' | 'medium' | 'low' | string;
  aliases: string[];
  keywords: string[];
};

export type MedicalMetadataResponse = {
  disease_rules: {
    count: number;
    versions: string[];
    review_status_counts: Record<string, number>;
    conditions: MedicalConditionRule[];
    medical_disclaimer: string;
  };
  // 運動係數的選項由後端提供，前端不再自己抄一份
  activity_levels?: { id: string; label_zh: string; multiplier: number }[];
  allergen_taxonomy: {
    version?: string;
    review_status?: string;
    last_reviewed?: string;
    references: { title: string; url: string }[];
    medical_disclaimer?: string;
    count: number;
    groups: AllergenGroup[];
  };
  medical_disclaimer: string;
  data_sources: { name: string; role: string }[];
  /**
   * 規則檔簽核的數字與程式公式算出來的數字不一致的地方。實際生效的是較嚴的
   * 那個，所以審閱者在 disease_rules.json 上看到的門檻，可能不是系統執行的。
   * 後端一直有算，但前端從來沒顯示——這種事不該只存在於 API 回應裡。
   */
  threshold_conflicts?: {
    condition_id: string;
    nutrient: string;
    configured_block: number;
    derived_block: number;
    effective_block: number;
    ignored_source: 'configured' | 'derived';
  }[];
  /** 給使用者看的一句話。逐項數字與「需要臨床人員確認」那句留在下面兩個欄位。 */
  threshold_conflict_note?: string | null;
  /** 給審閱流程看的全文，不放進 App 畫面。 */
  threshold_conflict_review_note?: string | null;
  /** 表單的選項與合理範圍，前端不再自己抄一份。 */
  diet_types?: string[];
  profile_limits?: Record<string, { min: number; max: number; unit: string; label_zh: string }>;
};

export type ApiAuth = {
  accessToken?: string | null;
};

// 本機後端連不上時的遠端備援。寫死網址會在後端搬家或砍掉之後變成死連結，
// 改成用環境變數指定；沒設就不做 fallback。
const RENDER_API_BASE_URL = process.env.EXPO_PUBLIC_FALLBACK_API_BASE_URL?.trim() || '';

function buildHeaders(auth?: ApiAuth, contentType?: string): HeadersInit {
  const headers: Record<string, string> = {};
  if (contentType) headers['Content-Type'] = contentType;
  if (auth?.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`;
  return headers;
}

async function parseJson<T>(resp: Response): Promise<T> {
  // 後端逾時、502、或路由不存在時回的是 HTML 或空 body，
  // 先 resp.json() 會丟出 "Unexpected token '<'"，把真正的狀態碼蓋掉。
  const raw = await resp.text();
  let data: any = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = null;
    }
  }

  if (!resp.ok) {
    if (data?.error) throw new Error(data.error);
    if (resp.status === 404) throw new Error(`找不到這個 API（HTTP 404）。後端可能還是舊版本，請確認 Render 部署的分支。`);
    if (resp.status === 401 || resp.status === 403) throw new Error(`沒有權限（HTTP ${resp.status}）。請登出後重新登入，讓 access token 更新。`);
    if (resp.status >= 500) throw new Error(`後端錯誤（HTTP ${resp.status}）。可能是處理逾時，請看 Render logs。`);
    throw new Error(`API 請求失敗（HTTP ${resp.status}）${raw ? `：${raw.slice(0, 160)}` : ''}`);
  }

  if (data === null) {
    throw new Error('後端回應不是有效的 JSON，可能中途被截斷或逾時。');
  }
  return data as T;
}

function isLocalApiBaseUrl(apiBaseUrl: string) {
  return /^https?:\/\/(localhost|127\.0\.0\.1|10\.0\.2\.2|192\.168\.|10\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(apiBaseUrl);
}

function isNetworkFetchError(err: any) {
  return err instanceof TypeError || err?.message === 'Failed to fetch' || err?.message === 'Network request failed';
}

async function canReachBackendHealth(apiBaseUrl: string) {
  try {
    const resp = await fetch(`${apiBaseUrl}/health`);
    return resp.ok;
  } catch {
    return false;
  }
}

async function fetchJsonWithNetworkMessage<T>(url: string, init?: RequestInit): Promise<T> {
  try {
    const resp = await fetch(url, init);
    return parseJson<T>(resp);
  } catch (err: any) {
    if (isNetworkFetchError(err)) {
      throw new Error(`無法連線到後端 API：${url.replace(/\?.*$/, '')}`);
    }
    throw err;
  }
}

export async function fetchHistory(apiBaseUrl: string, userId: string, days = 7, auth?: ApiAuth): Promise<HistoryResponse> {
  const resp = await fetch(`${apiBaseUrl}/history/${encodeURIComponent(userId)}?days=${days}`, {
    headers: buildHeaders(auth),
  });
  return parseJson<HistoryResponse>(resp);
}

export type RecordsQueryOptions = {
  limit?: number;
  offset?: number;
};

export async function fetchRecords(
  apiBaseUrl: string,
  userId: string,
  date?: string,
  auth?: ApiAuth,
  options?: RecordsQueryOptions
): Promise<RecordsResponse> {
  const queryParams = new URLSearchParams();
  if (date) queryParams.set('date', date);
  if (options?.limit !== undefined) queryParams.set('limit', String(options.limit));
  if (options?.offset !== undefined) queryParams.set('offset', String(options.offset));
  const query = queryParams.toString() ? `?${queryParams.toString()}` : '';
  const resp = await fetch(`${apiBaseUrl}/records/${encodeURIComponent(userId)}${query}`, {
    headers: buildHeaders(auth),
  });
  return parseJson<RecordsResponse>(resp);
}

/** Fetch every record page so trend aggregation never drops a busy user's meals. */
export async function fetchAllRecordsWithTargets(
  apiBaseUrl: string,
  userId: string,
  auth?: ApiAuth
): Promise<{
  records: DietaryRecord[];
  targets?: NutritionTargets;
  goalTypes?: NutritionGoalTypes;
  basis?: NutritionTargetBasis;
}> {
  const pageSize = 250;
  const records: DietaryRecord[] = [];
  let offset = 0;
  let targets: NutritionTargets | undefined;
  let goalTypes: NutritionGoalTypes | undefined;
  let basis: NutritionTargetBasis | undefined;

  while (true) {
    const page = await fetchRecords(apiBaseUrl, userId, undefined, auth, { limit: pageSize, offset });
    targets = targets ?? page.nutrition_targets;
    goalTypes = goalTypes ?? page.nutrition_goal_types;
    basis = basis ?? page.nutrition_target_basis;
    records.push(...(page.records || []));
    if ((page.records || []).length < pageSize) break;
    offset += pageSize;
  }

  return { records, targets, goalTypes, basis };
}

export async function fetchAllRecords(apiBaseUrl: string, userId: string, auth?: ApiAuth): Promise<DietaryRecord[]> {
  return (await fetchAllRecordsWithTargets(apiBaseUrl, userId, auth)).records;
}

export async function createDietaryRecord(
  apiBaseUrl: string,
  payload: CreateDietaryRecordPayload,
  auth?: ApiAuth
): Promise<CreateDietaryRecordResponse> {
  const resp = await fetch(`${apiBaseUrl}/record`, {
    method: 'POST',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify(payload),
  });
  return parseJson<CreateDietaryRecordResponse>(resp);
}

export async function updateDietaryRecord(
  apiBaseUrl: string,
  userId: string,
  clientRecordId: string,
  foods: FoodRecordItem[],
  auth?: ApiAuth
): Promise<RecordMutationResponse> {
  const resp = await fetch(`${apiBaseUrl}/records/${encodeURIComponent(userId)}/${encodeURIComponent(clientRecordId)}`, {
    method: 'PATCH',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify({ foods }),
  });
  return parseJson<RecordMutationResponse>(resp);
}

export async function deleteDietaryRecord(
  apiBaseUrl: string,
  userId: string,
  clientRecordId: string,
  auth?: ApiAuth
): Promise<RecordMutationResponse> {
  const resp = await fetch(`${apiBaseUrl}/records/${encodeURIComponent(userId)}/${encodeURIComponent(clientRecordId)}`, {
    method: 'DELETE',
    headers: buildHeaders(auth),
  });
  return parseJson<RecordMutationResponse>(resp);
}

export async function fetchUserProfile(apiBaseUrl: string, userId: string, auth?: ApiAuth): Promise<UserProfileResponse> {
  const resp = await fetch(`${apiBaseUrl}/user/${encodeURIComponent(userId)}`, {
    headers: buildHeaders(auth),
  });
  return parseJson<UserProfileResponse>(resp);
}

export async function fetchMedicalMetadata(apiBaseUrl: string): Promise<MedicalMetadataResponse> {
  const resp = await fetch(`${apiBaseUrl}/medical-metadata`);
  return parseJson<MedicalMetadataResponse>(resp);
}

export async function saveUserProfile(apiBaseUrl: string, payload: Record<string, unknown>, auth?: ApiAuth) {
  const resp = await fetch(`${apiBaseUrl}/user`, {
    method: 'POST',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify(payload),
  });
  return parseJson<{ message: string; user: UserProfileResponse }>(resp);
}

export async function fetchHealthyFoodRecommendations(
  apiBaseUrl: string,
  userId: string,
  params: { budget: number; lat: number; lng: number; radiusKm?: number; category?: string },
  auth?: ApiAuth
): Promise<HealthyFoodResponse> {
  if (!auth?.accessToken && !isLocalApiBaseUrl(apiBaseUrl)) {
    throw new Error('登入 session 尚未就緒，請重新整理頁面或重新登入後再定位推薦');
  }

  const query = new URLSearchParams({
    budget: String(params.budget),
    lat: String(params.lat),
    lng: String(params.lng),
    radius_km: String(params.radiusKm || 5),
    category: params.category || 'all',
  });
  const path = `/map-food-recommend/${encodeURIComponent(userId)}?${query.toString()}`;
  const requestInit = { headers: buildHeaders(auth) };

  try {
    return await fetchJsonWithNetworkMessage<HealthyFoodResponse>(`${apiBaseUrl}${path}`, requestInit);
  } catch (err: any) {
    if (RENDER_API_BASE_URL && isLocalApiBaseUrl(apiBaseUrl) && apiBaseUrl !== RENDER_API_BASE_URL) {
      return fetchJsonWithNetworkMessage<HealthyFoodResponse>(`${RENDER_API_BASE_URL}${path}`, requestInit);
    }
    if (err?.message?.startsWith('無法連線到後端 API')) {
      const healthReachable = await canReachBackendHealth(apiBaseUrl);
      if (healthReachable) {
        throw new Error('後端健康檢查可連線，但推薦 API request 失敗。請重新整理頁面或登出後重新登入，讓 Supabase session token 更新後再試一次。');
      }
    }
    throw err;
  }
}

export type VenueIndexSummary = {
  message: string;
  found: number;
  already_cached: number;
  refreshed?: number;
  analysed: number;
  failed: number;
  remaining: number;
  total_cached: number;
};

export type IndexedVenue = {
  name: string;
  address: string;
  items: number;
  has_opening_hours: boolean;
  business_status: string;
  age_days: number | null;
  stale: boolean;
};

export async function listNearbyVenueIndex(
  apiBaseUrl: string,
  userId: string,
  auth?: ApiAuth
): Promise<{ count: number; stale: number; without_opening_hours: number; venues: IndexedVenue[] }> {
  return fetchJsonWithNetworkMessage(`${apiBaseUrl}/restaurants/index/${encodeURIComponent(userId)}`, {
    headers: buildHeaders(auth),
  });
}

export async function clearNearbyVenueIndex(
  apiBaseUrl: string,
  userId: string,
  auth?: ApiAuth
): Promise<{ message: string; removed: number }> {
  return fetchJsonWithNetworkMessage(`${apiBaseUrl}/restaurants/index/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
    headers: buildHeaders(auth),
  });
}

export async function indexNearbyVenues(
  apiBaseUrl: string,
  userId: string,
  params: { budget?: number; lat?: number; lng?: number; radiusKm?: number; category?: string; limit?: number },
  auth?: ApiAuth
): Promise<VenueIndexSummary> {
  return fetchJsonWithNetworkMessage<VenueIndexSummary>(`${apiBaseUrl}/restaurants/index/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify({
      budget: params.budget ?? 150,
      lat: params.lat,
      lng: params.lng,
      radius_km: params.radiusKm,
      category: params.category,
      // Places 按請求計費，不是按筆數，所以一次要滿 20 家跟要 10 家一樣的錢
      limit: params.limit ?? 20,
    }),
  });
}

export async function fetchRestaurantAiSummary(
  apiBaseUrl: string,
  userId: string,
  params: { restaurant: HealthyFoodRestaurant; budget: number; category: string },
  auth?: ApiAuth
): Promise<RestaurantAiSummaryResponse> {
  if (!auth?.accessToken && !isLocalApiBaseUrl(apiBaseUrl)) {
    throw new Error('登入 session 尚未就緒，請重新整理頁面或重新登入後再產生 AI 摘要');
  }
  const resp = await fetch(`${apiBaseUrl}/map-food-recommend/${encodeURIComponent(userId)}/restaurant-summary`, {
    method: 'POST',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify(params),
  });
  return parseJson<RestaurantAiSummaryResponse>(resp);
}

export async function fetchRestaurantDetailedMenu(
  apiBaseUrl: string,
  params: { restaurant_id: string; name: string; address?: string; budget?: number; user_id?: string; lat?: number; lng?: number; distance_km?: number; menu_image?: string },
  auth?: ApiAuth
): Promise<{
  restaurant_id: string;
  name: string;
  recommended_items: HealthyFoodRecommendation[];
  filtered_items: any[];
  menu_recognition?: { recognition_status?: 'recognized' | 'error'; recognition_error?: string; recognition_model?: string } | null;
}> {
  const resp = await fetch(`${apiBaseUrl}/restaurant/menu`, {
    method: 'POST',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify(params),
  });
  return parseJson(resp);
}

