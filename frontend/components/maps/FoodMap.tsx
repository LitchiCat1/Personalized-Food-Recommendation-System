import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Line, Path, Rect } from 'react-native-svg';
import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import type { HealthyFoodRestaurant } from '@/lib/api';

type MapLocation = {
  lat: number;
  lng: number;
};

type FoodMapProps = {
  location: MapLocation;
  restaurants: HealthyFoodRestaurant[];
  selectedRestaurantId?: string | null;
  onSelectRestaurant: (restaurantId: string) => void;
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function markerColor(score: number) {
  if (score >= 80) return Palette.accent.green;
  if (score >= 60) return Palette.status.warning;
  return Palette.text.tertiary;
}

function getPoint(location: MapLocation, restaurant: HealthyFoodRestaurant) {
  const lngDelta = restaurant.lng - location.lng;
  const latDelta = restaurant.lat - location.lat;
  const x = clamp(50 + lngDelta * 9000, 9, 91);
  const y = clamp(50 - latDelta * 9000, 12, 88);
  return { x, y };
}

export default function FoodMap({ location, restaurants, selectedRestaurantId, onSelectRestaurant }: FoodMapProps) {
  return (
    <View style={styles.container}>
      <Svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
        <Rect x="0" y="0" width="100" height="100" rx="6" fill="#132033" />
        <Path d="M-5 82 C15 72 28 74 42 63 C58 49 72 57 105 39" stroke="#244866" strokeWidth="12" fill="none" opacity="0.58" />
        <Path d="M-5 20 C18 28 26 12 48 20 C68 28 78 22 105 16" stroke="#24324d" strokeWidth="8" fill="none" opacity="0.8" />
        <Line x1="0" y1="36" x2="100" y2="30" stroke="#334155" strokeWidth="1.2" opacity="0.7" />
        <Line x1="0" y1="63" x2="100" y2="58" stroke="#334155" strokeWidth="1.2" opacity="0.7" />
        <Line x1="21" y1="0" x2="15" y2="100" stroke="#334155" strokeWidth="1" opacity="0.58" />
        <Line x1="49" y1="0" x2="54" y2="100" stroke="#334155" strokeWidth="1" opacity="0.58" />
        <Line x1="80" y1="0" x2="73" y2="100" stroke="#334155" strokeWidth="1" opacity="0.58" />
        <Circle cx="50" cy="50" r="6" fill="rgba(34,211,238,0.18)" stroke={Palette.accent.cyan} strokeWidth="0.8" />
        <Circle cx="50" cy="50" r="2.2" fill={Palette.accent.cyan} />
      </Svg>

      {restaurants.map((restaurant, index) => {
        const point = getPoint(location, restaurant);
        const selected = restaurant.restaurant_id === selectedRestaurantId;
        const color = markerColor(restaurant.match_score);
        return (
          <Pressable
            key={restaurant.restaurant_id}
            onPress={() => onSelectRestaurant(restaurant.restaurant_id)}
            style={({ pressed }) => [
              styles.marker,
              {
                left: `${point.x}%`,
                top: `${point.y}%`,
                borderColor: selected ? Palette.text.primary : color,
                backgroundColor: selected ? color : Palette.bg.card,
                transform: [{ translateX: -15 }, { translateY: -30 }, { scale: selected ? 1.12 : 1 }],
                opacity: pressed ? 0.76 : 1,
                zIndex: selected ? 3 : 2,
              },
            ]}
          >
            <Text style={[styles.markerText, { color: selected ? Palette.text.inverse : color }]}>{index + 1}</Text>
          </Pressable>
        );
      })}

      <View style={styles.mapBadge}>
        <Text style={styles.mapBadgeText}>附近推薦地圖</Text>
      </View>
      <View style={styles.locationBadge}>
        <Text style={styles.locationText}>你的位置</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    height: 260,
    overflow: 'hidden',
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    backgroundColor: Palette.bg.secondary,
    position: 'relative',
    ...Shadows.card,
  },
  marker: {
    position: 'absolute',
    width: 30,
    height: 30,
    borderRadius: Radius.full,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markerText: { ...Typography.small, fontWeight: '800' },
  mapBadge: {
    position: 'absolute',
    top: Spacing.md,
    left: Spacing.md,
    backgroundColor: 'rgba(10,10,15,0.72)',
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  mapBadgeText: { ...Typography.small, color: Palette.text.primary },
  locationBadge: {
    position: 'absolute',
    left: '50%',
    top: '50%',
    transform: [{ translateX: 8 }, { translateY: 6 }],
    backgroundColor: 'rgba(34,211,238,0.18)',
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
  },
  locationText: { ...Typography.small, color: Palette.accent.cyan },
});
