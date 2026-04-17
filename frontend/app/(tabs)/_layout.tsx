import { Tabs } from 'expo-router';
import React from 'react';
import { StyleSheet, View, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import { Ionicons } from '@expo/vector-icons';
import { HapticTab } from '@/components/haptic-tab';
import { Palette, Spacing } from '@/constants/theme';
import { useStore } from '@/store/useStore';

export default function TabLayout() {
  const insets = useSafeAreaInsets();
  const isCameraActive = useStore((s) => s.isCameraActive);

  // Fix #2: Proper bottom safe area for Samsung virtual buttons
  const bottomInset = Math.max(insets.bottom, 8);
  const tabBarHeight = Platform.select({
    ios: 52 + bottomInset,
    android: 58 + bottomInset,
    default: 64,
  });

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarButton: HapticTab,
        tabBarActiveTintColor: Palette.accent.green,
        tabBarInactiveTintColor: Palette.text.tertiary,
        // Fix #3: Hide tab bar when camera is active
        tabBarStyle: isCameraActive
          ? { display: 'none' }
          : {
              position: 'absolute',
              borderTopWidth: 1,
              borderTopColor: Palette.border.subtle,
              backgroundColor: Platform.OS === 'ios' ? 'transparent' : Palette.bg.secondary,
              height: tabBarHeight,
              paddingTop: Spacing.xs,
              paddingBottom: bottomInset, // Fix #2: Samsung safe area
              elevation: 0,
            },
        tabBarLabelStyle: styles.tabBarLabel,
        tabBarBackground: () =>
          Platform.OS === 'ios' ? (
            <BlurView intensity={80} tint="dark" style={StyleSheet.absoluteFill} />
          ) : (
            <View style={[StyleSheet.absoluteFill, { backgroundColor: Palette.bg.secondary }]} />
          ),
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: '首頁',
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={focused ? 'home' : 'home-outline'} size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="scanner"
        options={{
          title: '辨識',
          tabBarIcon: ({ color, focused }) => (
            <View style={focused ? styles.scannerActive : undefined}>
              <Ionicons
                name={focused ? 'scan-circle' : 'scan-circle-outline'}
                size={focused ? 30 : 24}
                color={focused ? Palette.accent.green : color}
              />
            </View>
          ),
        }}
      />
      <Tabs.Screen
        name="recommend"
        options={{
          title: '推薦',
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={focused ? 'sparkles' : 'sparkles-outline'} size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="history"
        options={{
          title: '趨勢',
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={focused ? 'bar-chart' : 'bar-chart-outline'} size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: '我的',
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={focused ? 'person' : 'person-outline'} size={22} color={color} />
          ),
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tabBarLabel: {
    fontSize: 10,
    fontWeight: '600',
    marginTop: 2,
  },
  scannerActive: {
    marginTop: -2,
  },
});
