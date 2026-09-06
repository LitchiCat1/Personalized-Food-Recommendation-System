import * as Location from 'expo-location';

/**
 * 拿不到定位時退回的座標（台北 101）。
 * 只是為了讓畫面有東西可看，不代表使用者在那裡。
 */
export const FALLBACK_LOCATION = { lat: 25.0338, lng: 121.5645 } as const;

export type ResolvedLocation = {
  lat: number;
  lng: number;
  /** device = 真的抓到使用者位置；fallback = 用了預設座標 */
  source: 'device' | 'fallback';
  /** 退回預設時的原因，用來告訴使用者為什麼看到的不是附近的店 */
  reason?: string;
};

/**
 * 取得目前位置，拿不到就退回預設座標。
 *
 * 重點是 `source`：先前各處都直接顯示「定位座標：25.0338, 121.5645」，
 * 不管那是真的位置還是預設值，於是「附近店家」其實是台北 101 附近的店，
 * 而畫面上看不出來。呼叫端拿到 source 才能誠實標示。
 */
export async function resolveLocation(timeoutMs = 10000): Promise<ResolvedLocation> {
  let reason = '無法取得定位';
  try {
    const located = await Promise.race([
      (async (): Promise<ResolvedLocation> => {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (!permission.granted) {
          reason = '未授權定位';
          throw new Error(reason);
        }
        const position = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        return {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          source: 'device',
        };
      })(),
      new Promise<never>((_, reject) =>
        setTimeout(() => {
          reason = '定位逾時';
          reject(new Error(reason));
        }, timeoutMs)
      ),
    ]);
    return located;
  } catch {
    return { ...FALLBACK_LOCATION, source: 'fallback', reason };
  }
}

/** 給畫面用的一行說明，退回預設時要講清楚。 */
export function describeLocation(location: ResolvedLocation): string {
  const coords = `${location.lat.toFixed(4)}, ${location.lng.toFixed(4)}`;
  return location.source === 'device'
    ? `目前位置：${coords}`
    : `${location.reason}，改用預設位置台北 101（${coords}）。搜到的店家不會是你附近的。`;
}
