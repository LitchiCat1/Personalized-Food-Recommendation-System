import type { NutritionEnrichmentResponse } from './nutrition-enrichment-api';

export const MANUFACTURER_NUTRIENTS = [
  ['calories', '熱量', 'kcal'], ['protein', '蛋白質', 'g'], ['fat', '脂肪', 'g'],
  ['carbs', '碳水化合物', 'g'], ['sodium', '鈉', 'mg'], ['fiber', '膳食纖維', 'g'],
  ['sugar', '糖', 'g'], ['saturated_fat', '飽和脂肪', 'g'], ['trans_fat', '反式脂肪', 'g'],
] as const;

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

const text = (value: unknown) => typeof value === 'string' && value.trim().length > 0 && value.length <= 256
  ? value.trim() : null;
const point = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;

function sourceUrl(value: unknown): `https://${string}` | null {
  if (typeof value !== 'string' || !value.startsWith('https://') || value.length > 2048 || /[\s\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname.includes('.') && !url.port && !url.hash && !url.username && !url.password
      ? url.href as `https://${string}` : null;
  } catch {
    return null;
  }
}

function hasManufacturerLabel(item: Record<string, unknown>): boolean {
  const details = object(object(item.nutrition_profile)?.source_details);
  return item.origin === 'web' && !!details && Object.prototype.hasOwnProperty.call(details, 'manufacturer_label');
}

export function getManufacturerLabelPreviews(response: NutritionEnrichmentResponse, eligibleIds: ReadonlySet<string>) {
  if (!['accepted', 'complete', 'success', 'partial'].includes(response.status)) return [];
  const seen = new Set<string>();
  return (response.result?.items ?? []).flatMap((item) => {
    if (!item || !hasManufacturerLabel(item) || !['accepted', 'complete', 'partial', 'needs_portion'].includes(String(item.status))) return [];
    const id = item.item_id;
    if (typeof id !== 'string' || !eligibleIds.has(id) || seen.has(id)) return [];
    const profile = object(item.nutrition_profile);
    const details = object(profile?.source_details);
    const label = object(details?.manufacturer_label);
    const publisher = text(label?.publisher);
    const product = text(label?.product_name);
    const datasetName = text(label?.dataset_name);
    const traceCode = text(label?.trace_code);
    const visualName = text(item.original_visual_name);
    const url = sourceUrl(details?.source_url);
    const basis = profile?.basis;
    const basisWeight = point(profile?.basis_weight_g);
    const per100g = object(profile?.per_100g);
    if (label && ('dataset_name' in label || 'trace_code' in label) &&
        (!datasetName || !traceCode || !/^[A-Z]-\d{9}-\d{5}-\d-\d{8}-\d{10}$/.test(traceCode))) return [];
    if (!publisher || !product || !visualName || !url || !per100g ||
        profile?.has_required_point_values !== true ||
        !(['calories', 'protein', 'fat', 'carbs'].every((key) => point(per100g[key]) !== null)) ||
        !((basis === 'per_100g' && basisWeight === 100) || (basis === 'per_serving' && basisWeight && basisWeight > 0))) return [];
    const bounds = object(profile.upper_bounds_per_100g);
    const nutrients = MANUFACTURER_NUTRIENTS.map(([key, name, unit]) => ({
      key, name, unit, value: point(per100g[key]), bound: point(bounds?.[key]),
    }));
    seen.add(id);
    return [{ id, visualName, publisher, product, url, basis, basisWeight, nutrients, datasetName, traceCode }];
  });
}

export type ManufacturerLabelPreview = ReturnType<typeof getManufacturerLabelPreviews>[number];
