/**
 * NutriLens Design System
 * Premium dark-mode nutrition app theme
 */

import { Platform } from 'react-native';

// ─── Color Palette ──────────────────────────────────────────
export const Palette = {
  // Backgrounds
  bg: {
    primary: '#0A0A0F',
    secondary: '#12121A',
    card: '#1A1A2E',
    cardHover: '#222240',
    elevated: '#252540',
  },

  // Accents
  accent: {
    green: '#4ADE80',
    greenDim: 'rgba(74, 222, 128, 0.15)',
    blue: '#60A5FA',
    blueDim: 'rgba(96, 165, 250, 0.15)',
    orange: '#FB923C',
    orangeDim: 'rgba(251, 146, 60, 0.15)',
    purple: '#A78BFA',
    purpleDim: 'rgba(167, 139, 250, 0.15)',
    pink: '#F472B6',
    pinkDim: 'rgba(244, 114, 182, 0.15)',
    cyan: '#22D3EE',
    cyanDim: 'rgba(34, 211, 238, 0.15)',
  },

  // Text
  text: {
    primary: '#F1F5F9',
    secondary: '#94A3B8',
    tertiary: '#64748B',
    inverse: '#0F172A',
  },

  // Borders
  border: {
    subtle: 'rgba(255, 255, 255, 0.06)',
    medium: 'rgba(255, 255, 255, 0.12)',
    strong: 'rgba(255, 255, 255, 0.20)',
  },

  // Status
  status: {
    success: '#4ADE80',
    warning: '#FBBF24',
    error: '#F87171',
    info: '#60A5FA',
  },

  // Overlay
  overlay: 'rgba(0, 0, 0, 0.5)',
} as const;

// ─── Gradients ──────────────────────────────────────────────
export const Gradients = {
  greenBlue: ['#4ADE80', '#22D3EE'],
  purplePink: ['#A78BFA', '#F472B6'],
  orangeYellow: ['#FB923C', '#FBBF24'],
  blueIndigo: ['#60A5FA', '#818CF8'],
  cardGlow: ['rgba(74, 222, 128, 0.08)', 'rgba(34, 211, 238, 0.02)'],
  hero: ['rgba(74, 222, 128, 0.12)', 'rgba(96, 165, 250, 0.06)', 'transparent'],
} as const;

// ─── Spacing ────────────────────────────────────────────────
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

// ─── Border Radius ──────────────────────────────────────────
export const Radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  full: 9999,
} as const;

// ─── Typography ─────────────────────────────────────────────
export const Typography = {
  hero: { fontSize: 32, fontWeight: '800' as const, letterSpacing: -0.5 },
  h1: { fontSize: 26, fontWeight: '700' as const, letterSpacing: -0.3 },
  h2: { fontSize: 20, fontWeight: '700' as const, letterSpacing: -0.2 },
  h3: { fontSize: 17, fontWeight: '600' as const },
  body: { fontSize: 15, fontWeight: '400' as const },
  bodyBold: { fontSize: 15, fontWeight: '600' as const },
  caption: { fontSize: 13, fontWeight: '500' as const },
  small: { fontSize: 11, fontWeight: '500' as const },
  label: { fontSize: 12, fontWeight: '600' as const, letterSpacing: 0.8, textTransform: 'uppercase' as const },
} as const;

// ─── Shadows ────────────────────────────────────────────────
export const Shadows = {
  card: Platform.select({
    web: {
      boxShadow: '0px 4px 12px rgba(0, 0, 0, 0.3)',
    },
    default: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.3,
      shadowRadius: 12,
      elevation: 8,
    },
  }) as any,
  glow: (color: string) =>
    Platform.select({
      web: {
        boxShadow: `0px 0px 16px ${color}4D`,
      },
      default: {
        shadowColor: color,
        shadowOffset: { width: 0, height: 0 },
        shadowOpacity: 0.3,
        shadowRadius: 16,
        elevation: 8,
      },
    }) as any,
} as const;

// ─── Legacy Colors export (for compatibility with template) ─
const tintColorLight = '#4ADE80';
const tintColorDark = '#4ADE80';

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
    rounded: "'SF Pro Rounded', 'Hiragino Maru Gothic ProN', Meiryo, 'MS PGothic', sans-serif",
    mono: "SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  },
});
