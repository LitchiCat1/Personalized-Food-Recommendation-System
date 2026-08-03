import type { DietaryRecord, FoodRecordItem } from '@/lib/api';

const DATE_INPUT_PATTERN = /^(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})$/;
const TIMESTAMP_TIMEZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;
const DECIMAL_PATTERN = /^\d+(?:\.\d+)?$/;

export const RECORD_NUTRIENT_FIELDS = [
  { key: 'calories', label: '熱量', unit: 'kcal' },
  { key: 'protein', label: '蛋白質', unit: 'g' },
  { key: 'carbs', label: '碳水', unit: 'g' },
  { key: 'fat', label: '脂肪', unit: 'g' },
  { key: 'sodium', label: '鈉', unit: 'mg' },
  { key: 'fiber', label: '纖維', unit: 'g' },
] as const;

export type RecordNutrientKey = typeof RECORD_NUTRIENT_FIELDS[number]['key'];
export type RecordFoodDraft = Record<RecordNutrientKey, string> & {
  name: string;
  source?: string;
  warnings?: string[];
};

export type RecordDateRange = { startDate: string; endDate: string };
export type RecordDateRangeErrors = Partial<Record<keyof RecordDateRange, string>>;
export type RecordDraftErrors = Record<string, string>;

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

export function validateRecordDateRange(range: RecordDateRange): {
  dateKeys: { startDate: string; endDate: string } | null;
  errors: RecordDateRangeErrors;
} {
  const startDate = parseDateInput(range.startDate);
  const endDate = parseDateInput(range.endDate);
  const errors: RecordDateRangeErrors = {};
  if (!startDate) errors.startDate = '請輸入有效的開始日期（年/月/日）';
  if (!endDate) errors.endDate = '請輸入有效的結束日期（年/月/日）';
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
    fat: record.total_fat || 0,
    sodium: record.total_sodium || 0,
    fiber: record.total_fiber || 0,
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
    fat: String(toFiniteNumber(food.fat)),
    sodium: String(toFiniteNumber(food.sodium)),
    fiber: String(toFiniteNumber(food.fiber)),
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
    const food: FoodRecordItem = { name, source: draft.source, warnings: draft.warnings };
    for (const field of RECORD_NUTRIENT_FIELDS) {
      const rawValue = draft[field.key].trim();
      if (!rawValue) {
        errors[`foods.${index}.${field.key}`] = `${field.label}為必填`;
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

function formatLocalDateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function toFiniteNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
