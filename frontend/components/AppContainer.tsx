/**
 * AppContainer — Shared layout wrapper for all tab screens
 * 
 * Fixes:
 * - #4: Scroll to top on tab focus
 * - #5: Web desktop max-width centering
 * - #2: Bottom safe area padding for Samsung virtual buttons
 */

import React, { useRef, useCallback } from 'react';
import { View, ScrollView, StyleSheet } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useFocusEffect } from 'expo-router';
import { useResponsive } from '@/hooks/useResponsive';
import { Palette } from '@/constants/theme';
import DesktopSidebar from '@/components/ui/desktop-sidebar';

interface Props {
  children: React.ReactNode;
  /** Extra bottom padding beyond safe area (default: 80 for tab bar) */
  bottomPadding?: number;
}

export default function AppContainer({ children, bottomPadding = 80 }: Props) {
  const insets = useSafeAreaInsets();
  const { isDesktop, rs } = useResponsive();
  const scrollRef = useRef<ScrollView>(null);

  // Fix #4: Reset scroll position when tab becomes focused
  useFocusEffect(
    useCallback(() => {
      scrollRef.current?.scrollTo({ y: 0, animated: false });
    }, [])
  );

  // Fix #2: Bottom safe area for Samsung
  const safeBottom = Math.max(insets.bottom, 8);

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      {/* Fix #5: On desktop web, center the app with max-width */}
      <View style={[styles.outerContainer, isDesktop && styles.desktopOuter]}>
        {isDesktop ? <DesktopSidebar /> : null}
        <View style={[
          styles.innerContainer,
          isDesktop && styles.desktopContent,
        ]}>
          <ScrollView
            ref={scrollRef}
            showsVerticalScrollIndicator={false}
            contentContainerStyle={[
              styles.scrollContent,
              {
                paddingHorizontal: isDesktop ? 32 : rs(20),
                paddingBottom: isDesktop ? 32 : safeBottom + rs(bottomPadding),
              },
            ]}
          >
            {children}
          </ScrollView>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Palette.bg.primary,
  },
  outerContainer: {
    flex: 1,
  },
  desktopOuter: {
    flexDirection: 'row',
    alignSelf: 'center',
    width: '100%',
    maxWidth: 1280,
    backgroundColor: Palette.bg.secondary,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: Palette.border.subtle,
  },
  innerContainer: {
    flex: 1,
    width: '100%',
  },
  desktopContent: {
    flex: 1,
    width: 0,
    minWidth: 0,
  },
  scrollContent: {},
});
