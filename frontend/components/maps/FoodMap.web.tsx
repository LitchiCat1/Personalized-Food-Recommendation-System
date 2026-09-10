import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { AdvancedMarker, APIProvider, Map, Marker } from '@vis.gl/react-google-maps';
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
  /**
   * google.maps.Marker 自 2024-02-21 起標為 deprecated，接替的是 AdvancedMarkerElement。
   * 但 AdvancedMarker 需要在 Google Cloud 建一個 Map ID，沒有它標記會整個不顯示。
   * 所以有設定 Map ID 才切過去，沒設定就沿用舊的 Marker（會有 console 警告，但地圖是好的）。
   */
  const mapId = process.env.EXPO_PUBLIC_GOOGLE_MAPS_MAP_ID?.trim();
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
          mapId={mapId || undefined}
          /**
           * greedy 會讓地圖吃掉所有捲動手勢：滑鼠停在地圖上時整頁捲不動，
           * 手機上單指拖曳也只會平移地圖，使用者會以為畫面卡住。
           * cooperative 才是「地圖嵌在會捲動的頁面裡」該用的模式
           * ——滾輪捲頁面（按住 Ctrl 才縮放），單指捲頁面、雙指操作地圖。
           */
          gestureHandling="cooperative"
          disableDefaultUI={false}
          style={{ width: '100%', height: '100%' }}
        >
          {mapId ? (
            <>
              <AdvancedMarker position={location} title="你的位置" />
              {restaurants.map((restaurant, index) => (
                <AdvancedMarker
                  key={restaurant.restaurant_id}
                  position={{ lat: restaurant.lat, lng: restaurant.lng }}
                  title={`${index + 1}. ${restaurant.name}`}
                  onClick={() => onSelectRestaurant(restaurant.restaurant_id)}
                />
              ))}
            </>
          ) : (
            <>
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
            </>
          )}
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
  mapBadgeText: { ...Typography.small, color: Palette.text.inverse },
});
