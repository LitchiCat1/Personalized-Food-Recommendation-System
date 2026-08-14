import type { DietaryRecord, FoodRecordItem } from '@/lib/api';

const DATE_INPUT_PATTERN = /^(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})$/;
const TIMESTAMP_TIMEZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;
const DECIMAL_PATTERN = /^\d+(?:\.\d+)?$/;

export const RECORD_NUTRIENT_FIELDS = [
  { key: 'calories', label: '熱量', unit: 'kcal', required: true },
  { key: 'protein', label: '蛋白質', unit: 'g', required: true },
  { key: 'carbs', label: '總碳水化合物', unit: 'g', required: true },
  { key: 'sugar', label: '精緻糖', unit: 'g', required: false },
  { key: 'fat', label: '總脂肪', unit: 'g', required: true },
  { key: 'saturated_fat', label: '飽和脂肪', unit: 'g', required: false },
  { key: 'trans_fat', label: '反式脂肪', unit: 'g', required: false },
  { key: 'fiber', label: '膳食纖維', unit: 'g', required: true },
  { key: 'sodium', label: '鈉 (Sodium)', unit: 'mg', required: true },
  { key: 'calcium', label: '鈣 (Calcium)', unit: 'mg', required: false },
  { key: 'iron', label: '鐵 (Iron)', unit: 'mg', required: false },
] as const;

export type RecordNutrientKey = typeof RECORD_NUTRIENT_FIELDS[number]['key'];
export type RecordFoodDraft = Record<RecordNutrientKey, string> & {
  name: string;
  is_fried: 'true' | 'false';
  source?: string;
  warnings?: string[];
};

export type RecordDateRange = { startDate: string; endDate: string };
export type RecordDateRangeErrors = Partial<Record<keyof RecordDateRange, string>>;
export type RecordDraftErrors = Record<string, string>;

export type RecordDateValidation = {
  dateKey: string | null;
  error?: string;
};

export function formatDateInput(dateKey: string): string {
  return dateKey.replace(/-/g, '/');
}

export function parseDateInput(value: string): string | null {
  const match = value.trim().match(DATE_INPUT_PATTERN);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const candidate = new Date(Date.UTC(year, month - 1, day));
  if (
    candidate.getUTCFullYear() !== year
    || candidate.getUTCMonth() + 1 !== month
    || candidate.getUTCDate() !== day
  ) return null;
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function getDefaultRecordDateRange(now = new Date()): RecordDateRange {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  return {
    startDate: formatDateInput(formatLocalDateKey(start)),
    endDate: formatDateInput(formatLocalDateKey(end)),
  };
}

export function getLocalTodayDateKey(now = new Date()): string {
  return formatLocalDateKey(now);
}

export function validateRecordDate(value: string, now = new Date()): RecordDateValidation {
  const dateKey = parseDateInput(value);
  if (!dateKey) return { dateKey: null, error: '請選擇有效的紀錄日期' };
  if (dateKey > getLocalTodayDateKey(now)) {
    return { dateKey: null, error: '紀錄日期不得晚於今天' };
  }
  return { dateKey };
}

export function buildLocalTimestampForDate(value: string, now = new Date()): string {
  const dateKey = parseDateInput(value);
  if (!dateKey) throw new Error('請選擇有效的紀錄日期');
  const [year, month, day] = dateKey.split('-').map(Number);
  const localDateTime = new Date(
    year,
    month - 1,
    day,
    now.getHours(),
    now.getMinutes(),
    now.getSeconds(),
    now.getMilliseconds()
  );
  const offsetMinutes = localDateTime.getTimezoneOffset();
  const offsetSign = offsetMinutes <= 0 ? '+' : '-';
  const absoluteOffset = Math.abs(offsetMinutes);
  const offsetHours = String(Math.floor(absoluteOffset / 60)).padStart(2, '0');
  const offsetRemainder = String(absoluteOffset % 60).padStart(2, '0');
  const time = [
    localDateTime.getHours(),
    localDateTime.getMinutes(),
    localDateTime.getSeconds(),
  ].map((part) => String(part).padStart(2, '0')).join(':');
  const milliseconds = String(localDateTime.getMilliseconds()).padStart(3, '0');
  return `${dateKey}T${time}.${milliseconds}${offsetSign}${offsetHours}:${offsetRemainder}`;
}

export function createManualRecordFoodDraft(): RecordFoodDraft {
  return {
    name: '',
    calories: '',
    protein: '',
    carbs: '',
    sugar: '',
    fat: '',
    saturated_fat: '',
    trans_fat: '',
    sodium: '',
    fiber: '',
    calcium: '',
    iron: '',
    is_fried: 'false',
    source: 'manual',
    warnings: [],
  };
}

export function calculateRecordFoodTotals(foods: FoodRecordItem[]): Record<RecordNutrientKey, number> {
  return RECORD_NUTRIENT_FIELDS.reduce((totals, field) => {
    totals[field.key] = Math.round(
      foods.reduce((sum, food) => {
        const value = field.key === 'sugar'
          ? food.sugar ?? food.refined_sugar
          : food[field.key];
        return sum + Number(value || 0);
      }, 0) * 100
    ) / 100;
    return totals;
  }, {} as Record<RecordNutrientKey, number>);
}

export function validateRecordDateRange(range: RecordDateRange): {
  dateKeys: { startDate: string; endDate: string } | null;
  errors: RecordDateRangeErrors;
} {
  const startDate = parseDateInput(range.startDate);
  const endDate = parseDateInput(range.endDate);
  const errors: RecordDateRangeErrors = {};
  if (!startDate) errors.startDate = '請選擇有效的開始日期';
  if (!endDate) errors.endDate = '請選擇有效的結束日期';
  if (startDate && endDate && endDate < startDate) {
    errors.endDate = '結束日期不得早於開始日期';
  }
  return {
    dateKeys: Object.keys(errors).length === 0 && startDate && endDate ? { startDate, endDate } : null,
    errors,
  };
}

export function filterAndSortRecords(
  records: DietaryRecord[],
  userId: string,
  startDate: string,
  endDate: string,
  timezoneOffsetMinutes?: number
): DietaryRecord[] {
  return records
    .filter((record) => {
      if (record.user_id !== userId) return false;
      const date = normalizeRecordDateForRange(record.timestamp, timezoneOffsetMinutes);
      return Boolean(date && date >= startDate && date <= endDate);
    })
    .sort((left, right) => {
      const timestampOrder = getTimestampMillis(right.timestamp) - getTimestampMillis(left.timestamp);
      if (timestampOrder !== 0) return timestampOrder;
      return String(right.client_record_id || '').localeCompare(String(left.client_record_id || ''));
    });
}

export function getEditableRecordFoods(record: DietaryRecord): FoodRecordItem[] {
  if (Array.isArray(record.foods) && record.foods.length > 0) return record.foods;
  return [{
    name: record.meal_type || '未命名餐點',
    calories: record.total_calories || 0,
    protein: record.total_protein || 0,
    carbs: record.total_carbs || 0,
    sugar: record.total_sugar ?? record.total_refined_sugar ?? 0,
    fat: record.total_fat || 0,
    saturated_fat: record.total_saturated_fat || 0,
    trans_fat: record.total_trans_fat || 0,
    sodium: record.total_sodium || 0,
    fiber: record.total_fiber || 0,
    calcium: record.total_calcium || 0,
    iron: record.total_iron || 0,
    is_fried: record.contains_fried_food || false,
    source: record.source,
    warnings: [],
  }];
}

export function createRecordFoodDrafts(record: DietaryRecord): RecordFoodDraft[] {
  return getEditableRecordFoods(record).map((food) => ({
    name: String(food.name || ''),
    calories: String(toFiniteNumber(food.calories)),
    protein: String(toFiniteNumber(food.protein)),
    carbs: String(toFiniteNumber(food.carbs)),
    sugar: String(toFiniteNumber(food.sugar ?? food.refined_sugar)),
    fat: String(toFiniteNumber(food.fat)),
    saturated_fat: String(toFiniteNumber(food.saturated_fat)),
    trans_fat: String(toFiniteNumber(food.trans_fat)),
    sodium: String(toFiniteNumber(food.sodium)),
    fiber: String(toFiniteNumber(food.fiber)),
    calcium: String(toFiniteNumber(food.calcium)),
    iron: String(toFiniteNumber(food.iron)),
    is_fried: food.is_fried ? 'true' : 'false',
    source: food.source,
    warnings: food.warnings,
  }));
}

export function validateRecordFoodDrafts(drafts: RecordFoodDraft[]): {
  foods: FoodRecordItem[] | null;
  errors: RecordDraftErrors;
} {
  const errors: RecordDraftErrors = {};
  const foods = drafts.map((draft, index) => {
    const name = draft.name.trim();
    if (!name) errors[`foods.${index}.name`] = '食物名稱不可空白';
    const food: FoodRecordItem = {
      name,
      is_fried: draft.is_fried === 'true',
      source: draft.source,
      warnings: draft.warnings,
    };
    for (const field of RECORD_NUTRIENT_FIELDS) {
      const rawValue = draft[field.key].trim();
      if (!rawValue) {
        if (field.required) {
          errors[`foods.${index}.${field.key}`] = `${field.label}為必填`;
        } else {
          food[field.key] = 0;
        }
        continue;
      }
      if (!DECIMAL_PATTERN.test(rawValue)) {
        errors[`foods.${index}.${field.key}`] = `${field.label}需為 0 或正數`;
        continue;
      }
      const value = Number(rawValue);
      if (!Number.isFinite(value) || value < 0) {
        errors[`foods.${index}.${field.key}`] = `${field.label}需為 0 或正數`;
        continue;
      }
      food[field.key] = value;
    }
    return food;
  });
  return { foods: Object.keys(errors).length === 0 ? foods : null, errors };
}

export function formatRecordDateTime(timestamp: string): string {
  const parsed = parseRecordTimestamp(timestamp);
  if (!parsed) return timestamp || '時間未知';
  return parsed.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function getRecordFoodNames(record: DietaryRecord): string {
  return getEditableRecordFoods(record).map((food) => String(food.name || '').trim()).filter(Boolean).join('、') || '未命名餐點';
}

function normalizeRecordDateForRange(timestamp: string, timezoneOffsetMinutes?: number): string | null {
  const parsed = parseRecordTimestamp(timestamp);
  if (!parsed) return null;
  if (timezoneOffsetMinutes === undefined) return formatLocalDateKey(parsed);
  const localMillis = parsed.getTime() - timezoneOffsetMinutes * 60_000;
  const localDate = new Date(localMillis);
  return `${localDate.getUTCFullYear()}-${String(localDate.getUTCMonth() + 1).padStart(2, '0')}-${String(localDate.getUTCDate()).padStart(2, '0')}`;
}

function parseRecordTimestamp(timestamp: string): Date | null {
  const value = typeof timestamp === 'string' ? timestamp.trim() : '';
  if (!value) return null;
  const parsed = new Date(TIMESTAMP_TIMEZONE_PATTERN.test(value) ? value : `${value}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getTimestampMillis(timestamp: string): number {
  return parseRecordTimestamp(timestamp)?.getTime() || 0;
}

export function formatLocalDateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function toFiniteNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
