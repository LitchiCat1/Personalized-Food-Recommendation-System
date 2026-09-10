/**
 * 安全條件（病症／過敏原）的勾選規則。
 *
 * 抽出來是因為這裡出過錯：舊紀錄存的是中文標籤（'高血壓'），新的是 id
 * （'hypertension'）。畫面判定「已勾選」時同時認兩種，但 store 的 toggle 只
 * 比對 id，於是點一下會變成兩個都留著、顯示成已勾選，送去後端的卻是空陣列。
 * 少一個病症就等於那整組禁忌規則沒有套用，所以這條規則要有測試釘著。
 */
export function toggleSelection(current: string[], id: string, aliases: string[] = []): string[] {
  const names = new Set([id, ...aliases].filter(Boolean));
  const without = current.filter((value) => !names.has(value));
  const wasSelected = without.length !== current.length;
  return wasSelected ? without : [...without, id];
}

/** 畫面上是否顯示成已勾選。要跟 toggleSelection 用同一套比對，否則兩邊會漂移。 */
export function isSelected(current: string[], id: string, aliases: string[] = []): boolean {
  const names = new Set([id, ...aliases].filter(Boolean));
  return current.some((value) => names.has(value));
}
