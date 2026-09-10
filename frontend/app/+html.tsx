import { ScrollViewStyleReset } from 'expo-router/html';
import type { PropsWithChildren } from 'react';

import { buildThemeCss } from '@/constants/theme';

/**
 * 靜態網頁的外殼，只在 web 用得到，且只在建置時跑一次。
 *
 * 先前沒有這個檔案，Expo 產出的 index.html 因此沒有 <title>（分頁只顯示網址、
 * 加書籤沒有名稱）、沒有 description，而且 lang 是預設的 "en"——整個 App 是
 * 繁體中文，讀屏軟體會用英文語音去唸。
 *
 * 深色主題的 CSS 變數也在這裡注入：畫面的 StyleSheet 是模組載入時就算好的，
 * 沒辦法在執行期換色，所以改由 CSS 端決定 `--nl-*` 的實際值。
 */

const DESCRIPTION =
  '依你的慢性疾病、過敏原與每日營養目標，篩選可以安心吃的餐點；支援拍照辨識、營養標示掃描與附近店家菜單比對。';

/**
 * RN 掛載前先把底色畫對，否則深色模式下會先閃一下白底。
 * 另外把 body 的預設邊界清掉，並讓根容器吃滿高度。
 */
const baseCss = `
html, body, #root {
  height: 100%;
}
body {
  margin: 0;
  background-color: var(--nl-bg-primary);
  color: var(--nl-text-primary);
  overscroll-behavior-y: none;
}
`;

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="zh-Hant-TW">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />

        {/*
          標題不能寫在這裡。expo-router 靜態輸出時會自己插一個
          `<title data-rh="true">`，而且排在這個 <head> 的內容之前；
          HTML 規範是「第一個 title 生效」，所以那個空的會贏，
          分頁上就只剩網址。改用 app/_layout.tsx 的 <Head> 去填它。
        */}
        <meta name="description" content={DESCRIPTION} />
        <meta name="application-name" content="NutriLens" />

        {/* 分享出去時的預覽卡片 */}
        <meta property="og:title" content="NutriLens 個人化飲食推薦" />
        <meta property="og:description" content={DESCRIPTION} />
        <meta property="og:type" content="website" />

        {/* 瀏覽器 UI（手機網址列）跟著主題走 */}
        <meta name="theme-color" media="(prefers-color-scheme: light)" content="#F7FAF8" />
        <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0F1512" />

        {/*
          Expo 的建議做法：關掉 body 捲動，讓 RN 的 ScrollView 自己處理捲動，
          否則 web 上會出現兩層捲軸。
        */}
        <ScrollViewStyleReset />

        <style dangerouslySetInnerHTML={{ __html: buildThemeCss() }} />
        <style dangerouslySetInnerHTML={{ __html: baseCss }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
