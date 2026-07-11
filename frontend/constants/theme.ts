/**
 * NutriLens Design System
 * Clean medical nutrition app theme.
 */

import { Platform } from 'react-native';

export const Palette = {
  bg: {
    primary: '#F7FAF8',
    secondary: '#EEF6F1',
    card: '#FFFFFF',
    cardHover: '#F2F8F5',
    elevated: '#F0F6F3',
    mint: '#EAF7F1',
    wash: '#FDFEFC',
  },

  accent: {
    green: '#1F9D72',
    greenDim: 'rgba(31, 157, 114, 0.12)',
    blue: '#2F80ED',
    blueDim: 'rgba(47, 128, 237, 0.12)',
    orange: '#F59E0B',
    orangeDim: 'rgba(245, 158, 11, 0.14)',
    purple: '#7C6CF2',
    purpleDim: 'rgba(124, 108, 242, 0.12)',
    pink: '#D95F8D',
    pinkDim: 'rgba(217, 95, 141, 0.12)',
    cyan: '#1496A6',
    cyanDim: 'rgba(20, 150, 166, 0.12)',
  },

  text: {
    primary: '#14201B',
    secondary: '#40524A',
    tertiary: '#60716A',
    inverse: '#FFFFFF',
    muted: '#87958F',
  },

  border: {
    subtle: '#DDE8E2',
    medium: '#C7D8CF',
    strong: '#A9C0B6',
  },

  status: {
    success: '#1F9D72',
    warning: '#F59E0B',
    error: '#E25555',
    info: '#2F80ED',
  },

  overlay: 'rgba(20, 32, 27, 0.45)',
} as const;

export const Gradients = {
  greenBlue: ['#1F9D72', '#1496A6'],
  purplePink: ['#7C6CF2', '#D95F8D'],
  orangeYellow: ['#F59E0B', '#FBC02D'],
  blueIndigo: ['#2F80ED', '#7C6CF2'],
  cardGlow: ['rgba(31, 157, 114, 0.12)', 'rgba(255, 255, 255, 0.92)'],
  hero: ['rgba(31, 157, 114, 0.16)', 'rgba(47, 128, 237, 0.08)', 'rgba(255,255,255,0.92)'],
} as const;

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  '3xl': 32,
  '4xl': 40,
  '5xl': 48,
} as const;

export const Radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  full: 9999,
} as const;

export const Typography = {
  hero: { fontSize: 32, fontWeight: '800' as const, letterSpacing: 0, fontVariant: ['tabular-nums'] as any },
  h1: { fontSize: 26, fontWeight: '800' as const, letterSpacing: 0 },
  h2: { fontSize: 20, fontWeight: '700' as const, letterSpacing: 0 },
  h3: { fontSize: 17, fontWeight: '700' as const, letterSpacing: 0 },
  body: { fontSize: 15, fontWeight: '400' as const, lineHeight: 22 },
  bodyBold: { fontSize: 15, fontWeight: '700' as const, lineHeight: 22 },
  caption: { fontSize: 13, fontWeight: '500' as const, lineHeight: 18 },
  small: { fontSize: 11, fontWeight: '600' as const, lineHeight: 15 },
  label: { fontSize: 12, fontWeight: '700' as const, letterSpacing: 0, textTransform: 'uppercase' as const },
  number: { fontWeight: '800' as const, letterSpacing: 0, fontVariant: ['tabular-nums'] as any },
} as const;

export const Shadows = {
  card: Platform.select({
    web: {
      boxShadow: '0px 10px 26px rgba(22, 65, 48, 0.08)',
    },
    default: {
      shadowColor: '#164130',
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.08,
      shadowRadius: 18,
      elevation: 3,
    },
  }) as any,
  soft: Platform.select({
    web: {
      boxShadow: '0px 4px 14px rgba(22, 65, 48, 0.06)',
    },
    default: {
      shadowColor: '#164130',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.06,
      shadowRadius: 12,
      elevation: 2,
    },
  }) as any,
  glow: (color: string) =>
    Platform.select({
      web: {
        boxShadow: `0px 0px 18px ${color}33`,
      },
      default: {
        shadowColor: color,
        shadowOffset: { width: 0, height: 0 },
        shadowOpacity: 0.16,
        shadowRadius: 18,
        elevation: 4,
      },
    }) as any,
} as const;

const tintColorLight = Palette.accent.green;
const tintColorDark = Palette.accent.green;

export const Colors = {
  light: {
    text: Palette.text.primary,
    background: Palette.bg.primary,
    tint: tintColorLight,
    icon: Palette.text.secondary,
    tabIconDefault: Palette.text.tertiary,
    tabIconSelected: tintColorLight,
  },
  dark: {
    text: Palette.text.primary,
    background: Palette.bg.primary,
    tint: tintColorDark,
    icon: Palette.text.secondary,
    tabIconDefault: Palette.text.tertiary,
    tabIconSelected: tintColorDark,
  },
};

export const Fonts = Platform.select({
  ios: {
    sans: 'system-ui',
    serif: 'ui-serif',
    rounded: 'ui-rounded',
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    serif: "Georgia, 'Times New Roman', serif",
    rounded: "'SF Pro Rounded', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    mono: "SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  },
});
