import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { APIProvider, Map, Marker } from '@vis.gl/react-google-maps';
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

export default function FoodMap({ location, restaurants, selectedRestaurantId, onSelectRestaurant }: FoodMapProps) {
  const apiKey = process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY?.trim();
  if (!apiKey) {
    return (
      <View style={[styles.container, styles.missingKeyContainer]}>
        <Text style={styles.missingKeyTitle}>尚未設定 Google Maps API Key</Text>
        <Text style={styles.missingKeyText}>請在 Render frontend 設定 GOOGLE_PLACES_API_KEY 後重新部署，前端 build 會自動注入 Google Maps JavaScript API key。</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <APIProvider apiKey={apiKey} language="zh-TW" region="TW">
        <Map
          defaultCenter={location}
          center={location}
          defaultZoom={15}
          gestureHandling="greedy"
          disableDefaultUI={false}
          style={{ width: '100%', height: '100%' }}
        >
          <Marker position={location} title="你的位置" label="你" />
          {restaurants.map((restaurant, index) => {
            const selected = restaurant.restaurant_id === selectedRestaurantId;
            return (
              <Marker
                key={restaurant.restaurant_id}
                position={{ lat: restaurant.lat, lng: restaurant.lng }}
                title={restaurant.name}
                label={`${index + 1}`}
                opacity={selected ? 1 : 0.82}
                onClick={() => onSelectRestaurant(restaurant.restaurant_id)}
              />
            );
          })}
        </Map>
      </APIProvider>
      <View style={styles.mapBadge}>
        <Text style={styles.mapBadgeText}>Google Maps 真實店家</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    height: 300,
    overflow: 'hidden',
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    backgroundColor: Palette.bg.secondary,
    position: 'relative',
    ...Shadows.card,
  },
  missingKeyContainer: { alignItems: 'center', justifyContent: 'center', padding: Spacing.xl, gap: Spacing.sm },
  missingKeyTitle: { ...Typography.bodyBold, color: Palette.status.warning, textAlign: 'center' },
  missingKeyText: { ...Typography.caption, color: Palette.text.tertiary, textAlign: 'center', lineHeight: 20 },
  mapBadge: {
    position: 'absolute',
    top: Spacing.md,
    left: Spacing.md,
    backgroundColor: 'rgba(10,10,15,0.76)',
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  mapBadgeText: { ...Typography.small, color: Palette.text.primary },
});
