import { Tabs } from 'expo-router';
import React, { useEffect } from 'react';
import { StyleSheet, View, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import { Ionicons } from '@expo/vector-icons';
import { HapticTab } from '@/components/haptic-tab';
import { Palette, Spacing } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { fetchUserProfile } from '@/lib/api';
import { useResponsive } from '@/hooks/useResponsive';

export default function TabLayout() {
  const insets = useSafeAreaInsets();
  const { isDesktop } = useResponsive();
  const isCameraActive = useStore((s) => s.isCameraActive);
  const apiBaseUrl = useStore((s) => s.apiBaseUrl);
  const accessToken = useStore((s) => s.accessToken);
  const isAuthenticated = useStore((s) => s.isAuthenticated);

  useEffect(() => {
    if (!isAuthenticated || !accessToken) {
      return;
    }

    let cancelled = false;
    const currentUser = useStore.getState().user;

    fetchUserProfile(apiBaseUrl, currentUser.userId, { accessToken })
      .then((data) => {
        if (cancelled) return;
        if (!useStore.getState().isAuthenticated) return;
        const latestUser = useStore.getState().user;
        useStore.getState().replaceUser({
          ...latestUser,
          userId: data.user_id,
          name: data.name,
          gender: data.gender,
          height: data.height,
          weight: data.weight,
          age: data.age,
          bmi: data.bmi,
          activityLevel: data.activity_level,
          activityMultiplier: data.activity_multiplier,
          bmr: data.bmr,
          tdee: data.tdee,
          healthConditions: data.health_conditions,
          allergens: data.allergens,
          dailyCalorieTarget: data.daily_calorie_target,
          targetWeight: data.target_weight || latestUser.targetWeight,
          dietType: data.diet_type,
        });
      })
      .catch(() => {
        // Individual screens still surface API errors where the user can act on them.
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiBaseUrl, isAuthenticated]);

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
        tabBarStyle: isCameraActive || isDesktop
          ? { display: 'none' }
          : {
              position: 'absolute',
              borderTopWidth: 1,
              borderTopColor: Palette.border.subtle,
              backgroundColor: Platform.OS === 'ios' ? 'transparent' : Palette.bg.card,
              height: tabBarHeight,
              paddingTop: Spacing.xs,
              paddingBottom: bottomInset, // Fix #2: Samsung safe area
              elevation: 0,
            },
        tabBarLabelStyle: styles.tabBarLabel,
        tabBarBackground: () =>
          Platform.OS === 'ios' ? (
            <BlurView intensity={88} tint="light" style={StyleSheet.absoluteFill} />
          ) : (
            <View style={[StyleSheet.absoluteFill, { backgroundColor: Palette.bg.card }]} />
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
