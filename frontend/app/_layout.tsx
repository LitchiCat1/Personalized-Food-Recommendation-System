import { DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
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
      <AuthGate>
        <Stack>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        </Stack>
        <StatusBar style="dark" />
      </AuthGate>
    </ThemeProvider>
  );
}
