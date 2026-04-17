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

  // Content max width — on desktop, cap the app to phone-like width
  const maxContentWidth = isWeb && deviceType === 'desktop' ? 430 : width;

  // Effective width for layout calculations (capped on desktop)
  const effectiveWidth = Math.min(width, maxContentWidth);

  // Breakpoints based on effective width
  const screenSize: ScreenSize =
    effectiveWidth < 375 ? 'small' : effectiveWidth <= 413 ? 'medium' : 'large';

  // Scale factor relative to design base (390px = iPhone 14)
  const scale = effectiveWidth / 390;

  // Responsive scaling functions
  const wp = (percentage: number) => Math.round((effectiveWidth * percentage) / 100);
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
  const gridCol2 = (gap: number) => (effectiveWidth - gap * 3 - 40) / 2;
  const gridCol3 = (gap: number) => (effectiveWidth - gap * 4 - 40) / 3;

  // Tab bar safe height
  const tabBarHeight = isIOS ? 88 : isAndroid ? 68 : 64;

  return {
    width,
    height,
    effectiveWidth,
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
