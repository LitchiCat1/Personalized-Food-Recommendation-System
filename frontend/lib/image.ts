type ImageAssetLike = {
  base64?: string | null;
  uri?: string | null;
};

const DATA_IMAGE_URI = /^data:image\/(?:png|jpe?g|gif|webp);base64,[\s\S]+$/i;

/**
 * Expo ImagePicker returns base64 on native platforms, but some web browsers
 * only expose a blob/data URI. Convert that URI before sending it to Flask.
 */
export async function resolveImageBase64(asset?: ImageAssetLike | null): Promise<string | null> {
  const base64 = asset?.base64?.trim();
  if (base64) return base64;

  const uri = asset?.uri?.trim();
  if (!uri) return null;
  if (DATA_IMAGE_URI.test(uri)) return uri;

  if (typeof fetch !== 'function' || typeof FileReader === 'undefined') return null;

  try {
    const response = await fetch(uri);
    if (!response.ok) return null;
    const blob = await response.blob();
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = typeof reader.result === 'string' ? reader.result : '';
        resolve(result || '');
      };
      reader.onerror = () => reject(reader.error || new Error('無法讀取圖片'));
      reader.readAsDataURL(blob);
    });
  } catch {
    return null;
  }
}
