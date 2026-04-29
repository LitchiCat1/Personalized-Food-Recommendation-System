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
  };
};

export type HealthyFoodRecommendation = {
  restaurant_id: string;
  restaurant_name: string;
  distance_km: number;
  tags: string[];
  item_name: string;
  price: number;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sodium: number;
  gi?: 'low' | 'medium' | 'high' | null;
  match_score: number;
  reasons: string[];
};

export type HealthyFoodResponse = {
  user_id: string;
  budget: number;
  location: { lat: number; lng: number };
  remaining: {
    calories: number;
    protein: number;
    carbs: number;
    fat: number;
    sodium: number;
  };
  recommended: HealthyFoodRecommendation[];
  filtered_out: { restaurant_name: string; item_name: string; reasons: string[] }[];
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

async function parseJson<T>(resp: Response): Promise<T> {
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || 'API request failed');
  }
  return data as T;
}

export async function fetchHistory(apiBaseUrl: string, userId: string, days = 7): Promise<HistoryResponse> {
  const resp = await fetch(`${apiBaseUrl}/history/${encodeURIComponent(userId)}?days=${days}`);
  return parseJson<HistoryResponse>(resp);
}

export async function fetchRecords(apiBaseUrl: string, userId: string, date?: string): Promise<RecordsResponse> {
  const query = date ? `?date=${encodeURIComponent(date)}` : '';
  const resp = await fetch(`${apiBaseUrl}/records/${encodeURIComponent(userId)}${query}`);
  return parseJson<RecordsResponse>(resp);
}

export async function fetchRecommendations(apiBaseUrl: string, userId: string): Promise<RecommendationResponse> {
  const resp = await fetch(`${apiBaseUrl}/recommend/${encodeURIComponent(userId)}`);
  return parseJson<RecommendationResponse>(resp);
}

export async function fetchUserProfile(apiBaseUrl: string, userId: string): Promise<UserProfileResponse> {
  const resp = await fetch(`${apiBaseUrl}/user/${encodeURIComponent(userId)}`);
  return parseJson<UserProfileResponse>(resp);
}

export async function saveUserProfile(apiBaseUrl: string, payload: Record<string, unknown>) {
  const resp = await fetch(`${apiBaseUrl}/user`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseJson<{ message: string; user: UserProfileResponse }>(resp);
}

export async function fetchHealthyFoodRecommendations(
  apiBaseUrl: string,
  userId: string,
  params: { budget: number; lat: number; lng: number }
): Promise<HealthyFoodResponse> {
  const query = new URLSearchParams({
    budget: String(params.budget),
    lat: String(params.lat),
    lng: String(params.lng),
  });
  const resp = await fetch(`${apiBaseUrl}/healthy-food-recommend/${encodeURIComponent(userId)}?${query.toString()}`);
  return parseJson<HealthyFoodResponse>(resp);
}
