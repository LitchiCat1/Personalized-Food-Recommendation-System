// 飲食型態的選項只能有一份。
//
// 先前「我的」頁只接受「葷食」或「素食」，初次設定卻是一個自由輸入的
// 文字框、預設「均衡飲食」——於是新帳號一開始就拿到一個「我的」頁不
// 認得的值，儲存鈕從此是灰的，畫面上還不說為什麼。
export const DIET_TYPES = ['葷食', '素食'] as const;

export type DietType = (typeof DIET_TYPES)[number];

export const DEFAULT_DIET_TYPE: DietType = '葷食';

export function isKnownDietType(value: string | null | undefined): value is DietType {
  return DIET_TYPES.includes((value || '') as DietType);
}
