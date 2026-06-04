export type HistoryDay = {
  date: string;
  record_count?: number;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
};

export type HistoryResponse = {
  user_id: string;
  days: number;
  daily: HistoryDay[];
  summary: {
    avg_calories?: number;
    avg_protein?: number;
    avg_carbs?: number;
    avg_fat?: number;
    avg_sodium?: number;
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
  source?: string;
  warnings?: string[];
};

export type DietaryRecord = {
  user_id: string;
  timestamp: string;
  meal_type?: string;
  foods?: FoodRecordItem[];
  total_calories?: number;
  total_protein?: number;
  total_carbs?: number;
  total_fat?: number;
  total_sodium?: number;
  total_fiber?: number;
  source?: string;
};

export type RecordsResponse = {
  records: DietaryRecord[];
  count: number;
};

export type RecommendationItem = {
  label: string;
  name_zh: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
  gi?: 'low' | 'medium' | 'high' | null;
  source?: string;
  match_score: number;
  preference_score?: number;
  feedback_adjustment?: number;
  preference_reasons?: string[];
  safety_badges?: string[];
  reasons?: string[];
};

export type RecommendationResponse = {
  user_id: string;
  remaining_calories: number;
  health_conditions: string[];
  recommended: RecommendationItem[];
  filtered_out: RecommendationItem[];
  total_candidates: number;
  total_filtered: number;
  source_counts?: {
    total: number;
    manual_db: number;
    tfda: number;
    custom_foods: number;
  };
  preference_profile?: {
    record_count: number;
    food_count: number;
    feedback_count?: number;
    feedback_counts?: Record<RecommendationFeedbackAction, number>;
  };
};

export type RecommendationFeedbackAction = 'accepted' | 'skipped' | 'disliked';

export type RecommendationFeedbackResponse = {
  message: string;
  feedback: {
    user_id: string;
    action: RecommendationFeedbackAction;
    item_label: string;
    item_name?: string;
    item_source?: string;
    created_at: string;
  };
};

export type HealthyFoodRecommendation = {
  restaurant_id: string;
  restaurant_name: string;
  restaurant_lat?: number;
  restaurant_lng?: number;
  address?: string;
  distance_km: number;
  tags: string[];
  item_id?: string;
  item_name: string;
  price: number;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
  gi?: 'low' | 'medium' | 'high' | null;
  match_score: number;
  nutrition_available?: boolean;
  reasons: string[];
};

export type HealthyFoodRestaurant = {
  restaurant_id: string;
  name: string;
  lat: number;
  lng: number;
  address?: string;
  phone?: string;
  google_place_id?: string;
  distance_km: number;
  tags: string[];
  price_level?: number | null;
  is_open: boolean;
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
  };
  recommended: HealthyFoodRecommendation[];
  restaurants?: HealthyFoodRestaurant[];
  filtered_out: { restaurant_name: string; item_name: string; reasons: string[] }[];
  data_source?: string;
  nutrition_available?: boolean;
  nutrition_note?: string;
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
};

export type ApiAuth = {
  accessToken?: string | null;
};

const RENDER_API_BASE_URL = 'https://personalized-food-recommendation-system-nq8t.onrender.com';

function buildHeaders(auth?: ApiAuth, contentType?: string): HeadersInit {
  const headers: Record<string, string> = {};
  if (contentType) headers['Content-Type'] = contentType;
  if (auth?.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`;
  return headers;
}

async function parseJson<T>(resp: Response): Promise<T> {
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || 'API request failed');
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

export async function fetchRecords(apiBaseUrl: string, userId: string, date?: string, auth?: ApiAuth): Promise<RecordsResponse> {
  const query = date ? `?date=${encodeURIComponent(date)}` : '';
  const resp = await fetch(`${apiBaseUrl}/records/${encodeURIComponent(userId)}${query}`, {
    headers: buildHeaders(auth),
  });
  return parseJson<RecordsResponse>(resp);
}

export async function fetchRecommendations(apiBaseUrl: string, userId: string, auth?: ApiAuth): Promise<RecommendationResponse> {
  const resp = await fetch(`${apiBaseUrl}/recommend/${encodeURIComponent(userId)}`, {
    headers: buildHeaders(auth),
  });
  return parseJson<RecommendationResponse>(resp);
}

export async function saveRecommendationFeedback(
  apiBaseUrl: string,
  userId: string,
  action: RecommendationFeedbackAction,
  item: RecommendationItem,
  auth?: ApiAuth
): Promise<RecommendationFeedbackResponse> {
  const resp = await fetch(`${apiBaseUrl}/recommend/${encodeURIComponent(userId)}/feedback`, {
    method: 'POST',
    headers: buildHeaders(auth, 'application/json'),
    body: JSON.stringify({ action, item }),
  });
  return parseJson<RecommendationFeedbackResponse>(resp);
}

export async function fetchUserProfile(apiBaseUrl: string, userId: string, auth?: ApiAuth): Promise<UserProfileResponse> {
  const resp = await fetch(`${apiBaseUrl}/user/${encodeURIComponent(userId)}`, {
    headers: buildHeaders(auth),
  });
  return parseJson<UserProfileResponse>(resp);
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
  if (!auth?.accessToken) {
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
    if (isLocalApiBaseUrl(apiBaseUrl) && apiBaseUrl !== RENDER_API_BASE_URL) {
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
