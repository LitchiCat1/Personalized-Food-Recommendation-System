import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import type { HealthyFoodRestaurant } from '@/lib/api';

type FoodMapProps = {
  location: { lat: number; lng: number };
  restaurants: HealthyFoodRestaurant[];
  selectedRestaurantId?: string | null;
  onSelectRestaurant: (restaurantId: string) => void;
};

export default function FoodMap(_props: FoodMapProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Native 地圖尚未啟用</Text>
      <Text style={styles.text}>Web 版已接 Google Maps。若要在 iOS/Android 顯示真地圖，下一步請接 react-native-maps 或 Google Maps native SDK。</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    height: 260,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
    padding: Spacing.xl,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    backgroundColor: Palette.bg.secondary,
    ...Shadows.card,
  },
  title: { ...Typography.bodyBold, color: Palette.status.warning, textAlign: 'center' },
  text: { ...Typography.caption, color: Palette.text.tertiary, textAlign: 'center', lineHeight: 20 },
});
