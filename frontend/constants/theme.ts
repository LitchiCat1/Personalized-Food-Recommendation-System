/**
 * NutriLens Design System
 * Clean medical nutrition app theme.
 *
 * 顏色有兩份：`lightPalette` 與 `darkPalette`。
 *
 * 難處在於畫面用的是 `StyleSheet.create({...})`，那是模組載入時就算好的，
 * 之後換主題不會重算。全部改成「樣式是主題的函式」要動 600 多處引用，
 * 所以 web 走 CSS 變數：`Palette.text.primary` 產出的是 `var(--nl-text-primary)`，
 * 由 `app/+html.tsx` 注入的 `<style>` 依 prefers-color-scheme 決定實際值。
 * react-native-web 的 isWebColor 會原封不動放行 `var(` 開頭的字串，
 * 所以既有的 `Palette.*` 引用一個都不用改。
 *
 * 原生端沒有 CSS 變數，維持目前的淺色盤（行為不變）。
 */

import { Platform } from 'react-native';

/** 色票的形狀。兩個色盤都要填滿，才不會有某個 token 在深色下沒定義。 */
type PaletteShape = {
  bg: {
    primary: string;
    secondary: string;
    card: string;
    cardHover: string;
    elevated: string;
    mint: string;
    wash: string;
  };
  accent: {
    green: string;
    greenDim: string;
    blue: string;
    blueDim: string;
    orange: string;
    orangeDim: string;
    purple: string;
    purpleDim: string;
    pink: string;
    pinkDim: string;
    cyan: string;
    cyanDim: string;
  };
  text: {
    primary: string;
    secondary: string;
    tertiary: string;
    /** 綠色按鈕等「彩色底」上的文字。深淺兩種主題都是白的，不要跟著反轉。 */
    inverse: string;
    muted: string;
  };
  border: {
    subtle: string;
    medium: string;
    strong: string;
  };
  status: {
    success: string;
    warning: string;
    error: string;
    /**
     * 錯誤色的淡底。先前是在畫面裡用 `${Palette.status.error}14` 拼出來的，
     * 那招對 CSS 變數無效（會變成 `var(--x)14`），所以獨立成一個 token。
     */
    errorDim: string;
    info: string;
  };
  overlay: string;
  /** 卡片陰影的顏色，含透明度。 */
  shadowCard: string;
  shadowSoft: string;
};

export const lightPalette: PaletteShape = {
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
    errorDim: 'rgba(226, 85, 85, 0.08)',
    info: '#2F80ED',
  },

  overlay: 'rgba(20, 32, 27, 0.45)',
  shadowCard: 'rgba(22, 65, 48, 0.08)',
  shadowSoft: 'rgba(22, 65, 48, 0.06)',
};

/**
 * 深色盤。
 *
 * 重點不是把淺色反過來，是維持同樣的閱讀階層：內文對卡片底至少 4.5:1，
 * 強調色在深底上要提亮（#1F9D72 在 #18211D 上只有約 3.1:1，換成 #35C08D 約 7.4:1）。
 */
export const darkPalette: PaletteShape = {
  bg: {
    primary: '#0F1512',
    secondary: '#151D19',
    card: '#18211D',
    cardHover: '#1F2A25',
    elevated: '#1C2621',
    mint: '#17251F',
    wash: '#121814',
  },

  accent: {
    green: '#35C08D',
    greenDim: 'rgba(53, 192, 141, 0.18)',
    blue: '#5B9DF5',
    blueDim: 'rgba(91, 157, 245, 0.18)',
    orange: '#F5B547',
    orangeDim: 'rgba(245, 181, 71, 0.20)',
    purple: '#9B8DF7',
    purpleDim: 'rgba(155, 141, 247, 0.18)',
    pink: '#E888AC',
    pinkDim: 'rgba(232, 136, 172, 0.18)',
    cyan: '#3FB8C8',
    cyanDim: 'rgba(63, 184, 200, 0.18)',
  },

  text: {
    primary: '#E8F0EB',
    secondary: '#B3C2BA',
    tertiary: '#8B9C93',
    inverse: '#FFFFFF',
    muted: '#7D8D85',
  },

  border: {
    subtle: '#253029',
    medium: '#32403A',
    strong: '#45564E',
  },

  status: {
    success: '#35C08D',
    warning: '#F5B547',
    error: '#F0736F',
    errorDim: 'rgba(240, 115, 111, 0.16)',
    info: '#5B9DF5',
  },

  overlay: 'rgba(0, 0, 0, 0.62)',
  shadowCard: 'rgba(0, 0, 0, 0.45)',
  shadowSoft: 'rgba(0, 0, 0, 0.32)',
};

const VAR_PREFIX = '--nl';

/** `['bg','primary']` -> `--nl-bg-primary`，色盤與 CSS 變數名共用同一份 key。 */
function varName(path: string[]): string {
  return [VAR_PREFIX, ...path].join('-');
}

/** 把色盤攤平成 `[變數名, 色值]`，用來產生 CSS。 */
function flattenPalette(palette: PaletteShape): [string, string][] {
  const out: [string, string][] = [];
  const walk = (node: unknown, path: string[]) => {
    if (typeof node === 'string') {
      out.push([varName(path), node]);
      return;
    }
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      walk(value, [...path, key]);
    }
  };
  walk(palette, []);
  return out;
}

/** 形狀跟色盤一樣，但每個葉子換成 `var(--nl-...)`。 */
function toCssVarPalette(palette: PaletteShape): PaletteShape {
  const walk = (node: unknown, path: string[]): unknown => {
    if (typeof node === 'string') return `var(${varName(path)})`;
    return Object.fromEntries(
      Object.entries(node as Record<string, unknown>).map(([key, value]) => [key, walk(value, [...path, key])])
    );
  };
  return walk(palette, []) as PaletteShape;
}

/**
 * 產生要塞進 `<style>` 的 CSS。
 *
 * `data-theme` 是給之後想做手動切換用的掛勾：沒有它就跟隨系統。
 */
export function buildThemeCss(): string {
  const declarations = (palette: PaletteShape) =>
    flattenPalette(palette)
      .map(([name, value]) => `  ${name}: ${value};`)
      .join('\n');

  return [
    ':root {',
    '  color-scheme: light dark;',
    declarations(lightPalette),
    '}',
    '@media (prefers-color-scheme: dark) {',
    '  :root:not([data-theme="light"]) {',
    declarations(darkPalette),
    '  }',
    '}',
    ':root[data-theme="dark"] {',
    declarations(darkPalette),
    '}',
  ].join('\n');
}

/**
 * 畫面實際使用的色盤。
 *
 * web 拿到的是 var() 參照，所以同一份 StyleSheet 在深淺主題下都成立；
 * 原生拿到的是淺色實值。
 */
export const Palette: PaletteShape = Platform.OS === 'web' ? toCssVarPalette(lightPalette) : lightPalette;

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
      boxShadow: `0px 10px 26px ${Palette.shadowCard}`,
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
      boxShadow: `0px 4px 14px ${Palette.shadowSoft}`,
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
        boxShadow: `0px 0px 18px ${color}`,
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

export const Colors = {
  light: {
    text: lightPalette.text.primary,
    background: lightPalette.bg.primary,
    tint: lightPalette.accent.green,
    icon: lightPalette.text.secondary,
    tabIconDefault: lightPalette.text.tertiary,
    tabIconSelected: lightPalette.accent.green,
  },
  dark: {
    text: darkPalette.text.primary,
    background: darkPalette.bg.primary,
    tint: darkPalette.accent.green,
    icon: darkPalette.text.secondary,
    tabIconDefault: darkPalette.text.tertiary,
    tabIconSelected: darkPalette.accent.green,
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
