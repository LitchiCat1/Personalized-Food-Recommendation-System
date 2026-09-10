// app.json 的內容會以 `config` 傳進來，這裡只補上需要依環境變動的欄位。
//
// GitHub Pages 把網站放在 https://<帳號>.github.io/<倉庫名>/ 底下，不是網域根目錄。
// 靜態輸出必須知道這個前綴，否則 JS 與圖片會去根目錄找而全部 404。
// 用環境變數帶入，本機開發與其他部署方式（網域根目錄）就不受影響。
module.exports = ({ config }) => {
  const baseUrl = (process.env.EXPO_BASE_URL || '').trim();

  return {
    ...config,
    experiments: {
      ...(config.experiments || {}),
      ...(baseUrl ? { baseUrl } : {}),
    },
  };
};
