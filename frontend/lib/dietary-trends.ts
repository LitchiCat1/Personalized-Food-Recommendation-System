import type { DietaryRecord, FoodRecordItem, HistoryDay, HistoryResponse } from '@/lib/api';

const DATE_KEY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const TIMESTAMP_TIMEZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;

export type DietaryTrendOptions = {
  maxDays?: number;
  /** Useful for deterministic tests; omitted means the device's local timezone. */
  timezoneOffsetMinutes?: number;
  userId?: string;
};

export type DietaryTrendData = {
  daily: HistoryDay[];
  summary: HistoryResponse['summary'];
};

type DailyTotals = Omit<HistoryDay, 'record_count'> & { record_count: number };

/**
 * Convert the API's timestamp formats into a local calendar date. Older backend
 * records are timezone-less UTC strings, so they are parsed as UTC explicitly.
 */
export function normalizeRecordDate(timestamp: string | null | undefined, timezoneOffsetMinutes?: number): string | null {
  const value = typeof timestamp === 'string' ? timestamp.trim() : '';
  if (!value) return null;
  if (DATE_KEY_PATTERN.test(value)) return value;

  const parsed = new Date(TIMESTAMP_TIMEZONE_PATTERN.test(value) ? value : `${value}Z`);
  if (Number.isNaN(parsed.getTime())) return null;

  if (timezoneOffsetMinutes === undefined) {
    return formatDateKey(parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate());
  }

  const localMillis = parsed.getTime() - timezoneOffsetMinutes * 60_000;
  const localDate = new Date(localMillis);
  return formatDateKey(localDate.getUTCFullYear(), localDate.getUTCMonth() + 1, localDate.getUTCDate());
}

/** Select the newest non-empty run, never bridging a missing calendar date. */
export function selectLatestContinuousDays(daily: HistoryDay[], maxDays = 7): HistoryDay[] {
  const limit = Math.max(1, Math.floor(maxDays));
  const ordered = [...daily]
    .filter((day) => DATE_KEY_PATTERN.test(day.date) && (day.record_count || 0) > 0)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (ordered.length === 0) return [];

  const selected: HistoryDay[] = [ordered[ordered.length - 1]];
  for (let index = ordered.length - 2; index >= 0 && selected.length < limit; index -= 1) {
    const previous = selected[selected.length - 1];
    if (differenceInCalendarDays(previous.date, ordered[index].date) !== 1) break;
    selected.push(ordered[index]);
  }
  return selected.reverse();
}

export function buildDietaryTrend(records: DietaryRecord[], options: DietaryTrendOptions = {}): DietaryTrendData {
  const grouped = new Map<string, DailyTotals>();

  for (const record of records) {
    if (options.userId && record.user_id !== options.userId) continue;
    const date = normalizeRecordDate(record.timestamp, options.timezoneOffsetMinutes);
    if (!date) continue;

    const current = grouped.get(date) || createEmptyDay(date);
    const nutrients = getRecordNutrients(record);
    grouped.set(date, {
      ...current,
      record_count: current.record_count + 1,
      calories: current.calories + nutrients.calories,
      protein: current.protein + nutrients.protein,
      carbs: current.carbs + nutrients.carbs,
      fat: current.fat + nutrients.fat,
      sodium: current.sodium + nutrients.sodium,
    });
  }

  const daily = selectLatestContinuousDays(
    Array.from(grouped.values()).map(roundDay),
    options.maxDays ?? 7
  );
  return { daily, summary: buildSummary(daily) };
}

function getRecordNutrients(record: DietaryRecord) {
  const foods = Array.isArray(record.foods) ? record.foods : [];
  return {
    calories: getRecordNutrient(record.total_calories, foods, 'calories'),
    protein: getRecordNutrient(record.total_protein, foods, 'protein'),
    carbs: getRecordNutrient(record.total_carbs, foods, 'carbs'),
    fat: getRecordNutrient(record.total_fat, foods, 'fat'),
    sodium: getRecordNutrient(record.total_sodium, foods, 'sodium'),
  };
}

function getRecordNutrient(recordValue: number | undefined, foods: FoodRecordItem[], key: keyof FoodRecordItem): number {
  if (recordValue !== undefined && Number.isFinite(Number(recordValue))) return Number(recordValue);
  return foods.reduce((sum, food) => sum + toNumber(food[key]), 0);
}

function createEmptyDay(date: string): DailyTotals {
  return { date, record_count: 0, calories: 0, protein: 0, carbs: 0, fat: 0, sodium: 0 };
}

function roundDay(day: DailyTotals): HistoryDay {
  return {
    date: day.date,
    record_count: day.record_count,
    calories: Math.round(day.calories),
    protein: Math.round(day.protein),
    carbs: Math.round(day.carbs),
    fat: Math.round(day.fat),
    sodium: Math.round(day.sodium),
  };
}

function buildSummary(daily: HistoryDay[]): HistoryResponse['summary'] {
  if (daily.length === 0) return { recorded_days: 0, total_records: 0, avg_records_per_day: 0 };
  const totalRecords = daily.reduce((sum, day) => sum + (day.record_count || 0), 0);
  return {
    avg_calories: Math.round(daily.reduce((sum, day) => sum + day.calories, 0) / daily.length),
    avg_protein: Math.round(daily.reduce((sum, day) => sum + day.protein, 0) / daily.length),
    avg_carbs: Math.round(daily.reduce((sum, day) => sum + day.carbs, 0) / daily.length),
    avg_fat: Math.round(daily.reduce((sum, day) => sum + day.fat, 0) / daily.length),
    avg_sodium: Math.round(daily.reduce((sum, day) => sum + day.sodium, 0) / daily.length),
    recorded_days: daily.length,
    total_records: totalRecords,
    avg_records_per_day: Math.round((totalRecords / daily.length) * 10) / 10,
  };
}

function differenceInCalendarDays(later: string, earlier: string): number {
  const laterMillis = dateKeyToUtcMillis(later);
  const earlierMillis = dateKeyToUtcMillis(earlier);
  return Math.round((laterMillis - earlierMillis) / 86_400_000);
}

function dateKeyToUtcMillis(date: string): number {
  const [year, month, day] = date.split('-').map(Number);
  return Date.UTC(year, month - 1, day);
}

function formatDateKey(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function toNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
