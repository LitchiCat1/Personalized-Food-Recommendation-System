/**
 * 網頁版取得目前位置。
 *
 * 不用 expo-location 的 getCurrentPositionAsync：它的網頁版會帶 `maximumAge: Infinity`
 * 給瀏覽器，瀏覽器就一直回傳第一次定位的結果。網頁開著、人從基隆移動到九份，
 * 按「更新地圖」看到的還是基隆的座標和店家，要重新整理頁面才會變。
 *
 * 這個檔案不能 import expo 或 react-native，測試才能直接用 node 跑。
 */

/** 不接受舊的位置，每次都重新定位，跟手機版 getCurrentPositionAsync 的行為一致。 */
export const BROWSER_POSITION_MAX_AGE_MS = 0;

export function getBrowserPosition(
  geolocation: Pick<Geolocation, 'getCurrentPosition'>
): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    geolocation.getCurrentPosition(resolve, reject, {
      maximumAge: BROWSER_POSITION_MAX_AGE_MS,
      // 原本的 Accuracy.Balanced 在 expo 網頁版就是不開高精度
      enableHighAccuracy: false,
    });
  });
}
