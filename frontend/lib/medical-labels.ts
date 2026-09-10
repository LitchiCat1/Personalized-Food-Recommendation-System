/**
 * 疾病與過敏原的代碼 → 中文標籤。
 *
 * 後端把使用者選的項目正規化成英文 id（diabetes、milk），存的、回的都是 id。
 * 畫面上大多數地方是拿後端 metadata 的 label_zh 來顯示，但掃描頁的
 * 「安全條件已套用」直接把 id 陣列 join 起來，於是全中文的介面上會出現
 * 「疾病：diabetes、hypertension · 過敏原：milk」。
 *
 * 這份對照表跟 backend/config/disease_rules.json 與 allergen_taxonomy.json
 * 的 id 一致。對不上的 id 原樣回傳——沒有翻譯總比顯示空白好。
 */

const CONDITION_LABELS: Record<string, string> = {
  diabetes: '糖尿病',
  gout: '痛風',
  hyperlipidemia: '高血脂',
  hypertension: '高血壓',
  kidney_disease: '慢性腎臟病',
  // 前端 constants/mock-data.ts 的舊 id，舊帳號的資料可能還是這個
  kidney: '慢性腎臟病',
};

const ALLERGEN_LABELS: Record<string, string> = {
  peanut: '花生',
  tree_nut: '堅果',
  milk: '牛奶',
  egg: '蛋',
  soy: '大豆',
  wheat_gluten: '小麥 / 麩質',
  fish: '魚類',
  shellfish: '甲殼類 / 蝦蟹',
  sesame: '芝麻',
  sulfite: '亞硫酸鹽',
};

function translate(dictionary: Record<string, string>, value: string): string {
  const key = String(value ?? '').trim();
  if (!key) return '';
  return dictionary[key.toLowerCase()] ?? key;
}

export function conditionLabel(condition: string): string {
  return translate(CONDITION_LABELS, condition);
}

export function allergenLabel(allergen: string): string {
  return translate(ALLERGEN_LABELS, allergen);
}

/** 給「疾病：糖尿病、高血壓」這種一行摘要用。空清單回 fallback。 */
export function conditionLabels(conditions: string[] | undefined | null, fallback = '未設定'): string {
  const labels = (conditions || []).map(conditionLabel).filter(Boolean);
  return labels.length ? labels.join('、') : fallback;
}

export function allergenLabels(allergens: string[] | undefined | null, fallback = '未設定'): string {
  const labels = (allergens || []).map(allergenLabel).filter(Boolean);
  return labels.length ? labels.join('、') : fallback;
}
