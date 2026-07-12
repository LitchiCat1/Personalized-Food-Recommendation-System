/**
 * Responsive utilities for NutriLens
 * Adapts layout across phone sizes + PC web viewport
 */

import { useWindowDimensions, Platform, PixelRatio } from 'react-native';

export type ScreenSize = 'small' | 'medium' | 'large';
export type DeviceType = 'phone' | 'tablet' | 'desktop';

export function useResponsive() {
  const { width, height } = useWindowDimensions();
  const isLandscape = width > height;
  const fontScale = PixelRatio.getFontScale();

  // ── Platform detection ──
  const isWeb = Platform.OS === 'web';
  const isIOS = Platform.OS === 'ios';
  const isAndroid = Platform.OS === 'android';

  // Device type (for web: detect by viewport width)
  const deviceType: DeviceType =
    isWeb
      ? width >= 1024 ? 'desktop' : width >= 600 ? 'tablet' : 'phone'
      : width >= 600 ? 'tablet' : 'phone';

  // Web uses a real application shell. Compact controls still use a phone-sized
  // scale so desktop spacing does not grow with the viewport.
  const maxContentWidth = isWeb
    ? deviceType === 'desktop'
      ? 1280
      : deviceType === 'tablet'
        ? Math.min(width, 960)
        : width
    : width;

  // Effective width for layout calculations (capped on desktop)
  const effectiveWidth = Math.min(width, maxContentWidth);

  const compactWidth = Math.min(effectiveWidth, 430);

  // Breakpoints based on compact control width
  const screenSize: ScreenSize =
    compactWidth < 375 ? 'small' : compactWidth <= 413 ? 'medium' : 'large';

  // Scale factor relative to design base (390px = iPhone 14)
  const scale = compactWidth / 390;

  // Responsive scaling functions
  const wp = (percentage: number) => Math.round((compactWidth * percentage) / 100);
  const hp = (percentage: number) => Math.round((height * percentage) / 100);

  // Scale a value proportionally to screen width
  const rs = (size: number) => {
    const newSize = size * scale;
    if (isWeb) return Math.round(newSize);
    return Math.round(PixelRatio.roundToNearestPixel(newSize));
  };

  // Font scale — respects user accessibility settings
  const fs = (size: number) => {
    const scaled = size * Math.min(scale, 1.15); // cap at 115% for readability
    return Math.round(PixelRatio.roundToNearestPixel(scaled));
  };

  // Grid column width for 2-column layout with gap
  const gridCol2 = (gap: number) => (compactWidth - gap * 3 - 40) / 2;
  const gridCol3 = (gap: number) => (compactWidth - gap * 4 - 40) / 3;

  // Tab bar safe height
  const tabBarHeight = isIOS ? 88 : isAndroid ? 68 : 64;

  return {
    width,
    height,
    effectiveWidth,
    compactWidth,
    maxContentWidth,
    screenSize,
    scale,
    isLandscape,
    fontScale,
    wp,
    hp,
    rs,
    fs,
    gridCol2,
    gridCol3,
    tabBarHeight,
    isSmall: screenSize === 'small',
    isMedium: screenSize === 'medium',
    isLarge: screenSize === 'large',
    isWeb,
    isIOS,
    isAndroid,
    deviceType,
    isDesktop: deviceType === 'desktop',
    isPhone: deviceType === 'phone',
  };
}
