import { DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import Head from 'expo-router/head';
import { StatusBar } from 'expo-status-bar';
import 'react-native-reanimated';

import AuthGate from '@/components/AuthGate';
import { Palette } from '@/constants/theme';

const NutriLensTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: Palette.accent.green,
    background: Palette.bg.primary,
    card: Palette.bg.card,
    text: Palette.text.primary,
    border: Palette.border.subtle,
    notification: Palette.accent.orange,
  },
};

export const unstable_settings = {
  anchor: '(tabs)',
};

export default function RootLayout() {
  return (
    <ThemeProvider value={NutriLensTheme}>
      {/*
        web 的分頁標題。expo-router 一定會輸出一個 title 元素，沒人填就是空的，
        瀏覽器分頁因此只顯示網址、加書籤也沒有名稱。
      */}
      <Head>
        <title>NutriLens 個人化飲食推薦</title>
      </Head>
      <AuthGate>
        <Stack>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        </Stack>
        <StatusBar style="auto" />
      </AuthGate>
    </ThemeProvider>
  );
}
