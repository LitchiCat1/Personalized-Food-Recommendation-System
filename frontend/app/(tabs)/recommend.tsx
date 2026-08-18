import React, { useState } from 'react';
import { Alert, View, Text, StyleSheet, ActivityIndicator, TextInput, Pressable, Linking, Modal, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import type { DetectedFood } from '@/constants/mock-data';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import SegmentedControl from '@/components/ui/segmented-control';
import FoodMap from '@/components/maps/FoodMap';
import { saveRecord } from '@/lib/scanner';
import {
  fetchHealthyFoodRecommendations,
  fetchRestaurantAiSummary,
  fetchRestaurantDetailedMenu,
  type HealthyFoodRestaurant,
  type RestaurantAiSummary,
  type HealthyFoodResponse,
} from '@/lib/api';


const RADIUS_OPTIONS = [
  { value: '1', label: '1 km' },
  { value: '3', label: '3 km' },
  { value: '5', label: '5 km' },
];

const CATEGORY_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: '便當', label: '便當' },
  { value: '小吃', label: '小吃' },
  { value: '早餐', label: '早餐' },
  { value: '飲料', label: '飲料' },
  { value: '沙拉', label: '沙拉' },
];

export default function RecommendScreen() {
  const user = useStore((state) => state.user);
  const apiBaseUrl = useStore((state) => state.apiBaseUrl);
  const accessToken = useStore((state) => state.accessToken);
  const addMealFromScan = useStore((state) => state.addMealFromScan);
  const invalidateDietaryRecords = useStore((state) => state.invalidateDietaryRecords);

  const [budget, setBudget] = useState('150');
  const [radiusKm, setRadiusKm] = useState(3);
  const [category, setCategory] = useState('all');
  const [healthyLoading, setHealthyLoading] = useState(false);
  const [healthyError, setHealthyError] = useState<string | null>(null);
  const [healthyData, setHealthyData] = useState<HealthyFoodResponse | null>(null);
  const [summaryByRestaurant, setSummaryByRestaurant] = useState<Record<string, RestaurantAiSummary>>({});
  const [summaryLoadingKey, setSummaryLoadingKey] = useState<string | null>(null);
  const [selectedRestaurantId, setSelectedRestaurantId] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState('尚未取得定位');
  const [viewingMenuRest, setViewingMenuRest] = useState<HealthyFoodRestaurant | null>(null);
  const [menuLoading, setMenuLoading] = useState(false);
  const [addingFoodName, setAddingFoodName] = useState<string | null>(null);

  const mapRestaurants = healthyData?.restaurants || [];
  const mapLocation = healthyData?.location || null;
  const selectedRestaurant = mapRestaurants.find((restaurant) => restaurant.restaurant_id === selectedRestaurantId) || mapRestaurants[0] || null;

  const handleQuickAddRecord = async (item: {
    item_name?: string;
    name?: string;
    calories?: number;
    protein?: number;
    carbs?: number;
    fat?: number;
    sodium?: number;
    sugar?: number;
    saturated_fat?: number;
    trans_fat?: number;
    fiber?: number;
    calcium?: number;
    iron?: number;
    price?: number;
  }) => {
    const foodName = item.item_name || item.name || '推薦餐點';
    const clientRecordId = `rec_${Date.now()}`;
    setAddingFoodName(foodName);
    try {
      const foodItem = {
        name: foodName,
        calories: Number(item.calories || 350),
        protein: Number(item.protein || 15),
        carbs: Number(item.carbs || 45),
        fat: Number(item.fat || 10),
        sodium: Number(item.sodium || 500),
        sugar: Number(item.sugar || 0),
        saturated_fat: Number(item.saturated_fat || 0),
        trans_fat: Number(item.trans_fat || 0),
        fiber: Number(item.fiber || 3),
        calcium: Number(item.calcium || 0),
        iron: Number(item.iron || 0),
        source: 'manual',
      };

      const detectedFoodItem: DetectedFood = {
        id: clientRecordId,
        foodName,
        confidence: 100,
        source: 'manual',
        needsConfirmation: false,
        boundingBox: { x: 0, y: 0, w: 0, h: 0 },
        estimatedWeight: 200,
        portionRange: { minG: 200, maxG: 200, uncertaintyPercent: 0 },
        portionEstimationMethod: 'nutrition_label_serving_size',
        reliability: { level: 'high', score: 0.9, reasons: ['來自 AI 個人化推薦'] },
        nutrition: foodItem,
        gi: 'medium',
        allergens: [],
        warnings: [],
      };

      await saveRecord({
        apiBaseUrl,
        userId: user.userId,
        clientRecordId,
        foods: [detectedFoodItem],
        source: 'manual',
        auth: { accessToken },
      });
      invalidateDietaryRecords();
      addMealFromScan([detectedFoodItem]);
      Alert.alert('已新增紀錄', `已成功將「${foodName} (${foodItem.calories} kcal)」加入今日飲食紀錄！`);
    } catch (err: any) {
      Alert.alert('新增紀錄失敗', err?.message || '請稍後再試');
    } finally {
      setAddingFoodName(null);
    }
  };

  const handleHealthyFoodSearch = async () => {
    setHealthyLoading(true);
    setHealthyError(null);
    let lat = 25.0338;
    let lng = 121.5645;
    try {
      const geoPromise = (async () => {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (permission.granted) {
          const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
          return { lat: position.coords.latitude, lng: position.coords.longitude };
        }
        throw new Error('未授權定位');
      })();

      const timeoutPromise = new Promise<{ lat: number; lng: number }>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 10000)
      );

      const coords = await Promise.race([geoPromise, timeoutPromise]).catch(() => {
        return { lat: 25.0338, lng: 121.5645 };
      });

      lat = coords.lat;
      lng = coords.lng;
      setLocationLabel(`定位座標：${lat.toFixed(4)}, ${lng.toFixed(4)}`);

      const result = await fetchHealthyFoodRecommendations(
        apiBaseUrl,
        user.userId,
        { budget: Number(budget) || 150, lat, lng, radiusKm, category },
        { accessToken }
      );
      setHealthyData(result);
      setSelectedRestaurantId(result.restaurants?.[0]?.restaurant_id || null);
    } catch (err: any) {
      setHealthyError(err?.message || '無法取得健康餐點推薦');
    } finally {
      setHealthyLoading(false);
    }
  };

  const handleLoadRestaurantSummary = async (restaurant: HealthyFoodRestaurant) => {
    setSummaryLoadingKey(restaurant.restaurant_id);
    try {
      const result = await fetchRestaurantAiSummary(
        apiBaseUrl,
        user.userId,
        { restaurant, budget: Number(budget) || 150, category },
        { accessToken }
      );
      setSummaryByRestaurant((current: Record<string, RestaurantAiSummary>) => ({
        ...current,
        [restaurant.restaurant_id]: result.summary,
      }));
    } catch (err: any) {
      alert(err?.message || '無法取得 AI 摘要');
    } finally {
      setSummaryLoadingKey(null);
    }
  };

  const handleViewMenu = async (restaurant: HealthyFoodRestaurant) => {
    setViewingMenuRest(restaurant);
    if ((restaurant.recommended_items || []).length === 0 || !restaurant.nutrition_available) {
      setMenuLoading(true);
      try {
        const response = await fetchRestaurantDetailedMenu(
          apiBaseUrl,
          {
            restaurant_id: restaurant.restaurant_id,
            name: restaurant.name,
            address: restaurant.address,
            budget: Number(budget) || 150,
            user_id: user.userId,
            lat: restaurant.lat,
            lng: restaurant.lng,
          },
          { accessToken }
        );
        setViewingMenuRest((prev: HealthyFoodRestaurant | null) =>
          prev ? { ...prev, recommended_items: response.recommended_items, filtered_items: response.filtered_items } : null
        );
      } catch (err) {
        console.log('Failed to fetch detailed menu:', err);
      } finally {
        setMenuLoading(false);
      }
    }
  };

  const handleOpenNavigation = (restaurant: HealthyFoodRestaurant) => {
    const query = encodeURIComponent(`${restaurant.name} ${restaurant.address}`);
    const url = `https://www.google.com/maps/search/?api=1&query=${query}`;
    Linking.openURL(url);
  };

  const handleOpenRestaurantWebsite = (restaurant: HealthyFoodRestaurant) => {
    if (restaurant.menu_link) {
      Linking.openURL(restaurant.menu_link.url);
    }
  };

  const handleOpenRestaurantInfo = (restaurant: HealthyFoodRestaurant) => {
    const query = encodeURIComponent(`${restaurant.name} ${restaurant.address}`);
    const url = `https://www.google.com/maps/search/?api=1&query=${query}`;
    Linking.openURL(url);
  };

  return (
    <AppContainer>
      <ScreenHeader
        title="智慧推薦"
        subtitle="查看符合個人條件的餐點，再用定位找附近可行店家。"
        badge="地圖搜尋"
        badgeTone="success"
      />

      <SectionBlock title="附近店家推薦" subtitle="Google Places 只提供真實店家位置；實際餐點營養仍建議用掃描確認。">
            <View style={styles.budgetRow}>
              <TextInput
                value={budget}
                onChangeText={setBudget}
                keyboardType="numeric"
                placeholder="本餐預算"
                placeholderTextColor={Palette.text.muted}
                style={styles.budgetInput}
              />
              <PrimaryButton
                label={healthyLoading ? '搜尋中' : '更新地圖'}
                onPress={handleHealthyFoodSearch}
                fullWidth={false}
                icon={healthyLoading ? <ActivityIndicator size="small" color={Palette.text.inverse} /> : <Ionicons name="location-outline" size={17} color={Palette.text.inverse} />}
              />
            </View>
            <Text style={styles.optionLabel}>搜尋半徑</Text>
            <SegmentedControl options={RADIUS_OPTIONS} value={String(radiusKm)} onChange={(value) => setRadiusKm(Number(value))} />
            <Text style={styles.optionLabel}>店家類型</Text>
            <View style={styles.categoryWrap}>
              {CATEGORY_OPTIONS.map((option) => (
                <Pressable key={option.value} accessibilityRole="button" accessibilityState={{ selected: category === option.value }} onPress={() => setCategory(option.value)} style={[styles.categoryChip, category === option.value && styles.categoryChipActive]}>
                  <Text style={[styles.categoryText, category === option.value && styles.categoryTextActive]}>{option.label}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.locationText}>{locationLabel}</Text>
            {healthyError ? (
              <View style={styles.apiErrorBox}>
                <Text style={styles.errorText}>{healthyError}</Text>
                <Text style={styles.errorMeta}>API：{apiBaseUrl}</Text>
                <Text style={styles.errorMeta}>登入狀態：{accessToken ? 'Bearer token 已載入' : '尚未載入 Bearer token'}</Text>
              </View>
            ) : null}
          </SectionBlock>

          {mapRestaurants.length && mapLocation ? (
            <>
              <View style={styles.mapCard}>
                <FoodMap
                  location={mapLocation}
                  restaurants={mapRestaurants}
                  selectedRestaurantId={selectedRestaurant?.restaurant_id || null}
                  onSelectRestaurant={setSelectedRestaurantId}
                />
                {selectedRestaurant ? (
                  <View style={styles.selectedMapInfo}>
                    <View style={styles.mapTitleRow}>
                      <Text style={styles.restaurantName}>{selectedRestaurant.name}</Text>
                      <DataPill tone="info">推薦 {selectedRestaurant.match_score}</DataPill>
                    </View>
                    <Text style={styles.restaurantMeta}>{selectedRestaurant.address || '尚無地址'} · {selectedRestaurant.distance_km} km</Text>
                    <SecondaryButton label="開啟 Google Maps 導航" onPress={() => handleOpenNavigation(selectedRestaurant)} icon={<Ionicons name="navigate-outline" size={15} color={Palette.accent.green} />} />
                  </View>
                ) : null}
              </View>

              {mapRestaurants.map((restaurant, index) => (
                <RestaurantCard
                  key={restaurant.restaurant_id}
                  restaurant={restaurant}
                  index={index}
                  addingFoodName={addingFoodName}
                  selected={selectedRestaurantId === restaurant.restaurant_id}
                  summary={summaryByRestaurant[restaurant.restaurant_id]}
                  summaryLoading={summaryLoadingKey === restaurant.restaurant_id}
                  onSelect={() => setSelectedRestaurantId(restaurant.restaurant_id)}
                  onSummary={() => handleLoadRestaurantSummary(restaurant)}
                  onNavigate={() => handleOpenNavigation(restaurant)}
                  onViewMenu={() => handleViewMenu(restaurant)}
                  onOpenRestaurantWebsite={() => handleOpenRestaurantWebsite(restaurant)}
                  onOpenRestaurantInfo={() => handleOpenRestaurantInfo(restaurant)}
                  onQuickAddRecord={handleQuickAddRecord}
                />
              ))}
            </>
          ) : null}

      <Modal
        visible={viewingMenuRest !== null}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setViewingMenuRest(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>{viewingMenuRest?.name}</Text>
              <Pressable onPress={() => setViewingMenuRest(null)}>
                <Ionicons name="close" size={24} color={Palette.text.primary} />
              </Pressable>
            </View>

            {menuLoading ? (
              <View style={{ justifyContent: 'center', alignItems: 'center', paddingVertical: Spacing.xl }}>
                <ActivityIndicator size="large" color={Palette.accent.green} />
                <Text style={[styles.emptyText, { marginTop: Spacing.md }]}>正在讀取或使用 AI 即時解析菜單...</Text>
              </View>
            ) : (
              <ScrollView contentContainerStyle={styles.modalScroll}>
                <Text style={styles.restaurantMeta}>{viewingMenuRest?.address}</Text>

                <Text style={styles.modalSectionTitle}>餐點安全分析</Text>
                {(viewingMenuRest?.recommended_items || []).length === 0 && (viewingMenuRest?.filtered_items || []).length === 0 ? (
                  <View style={{ padding: Spacing.lg, alignItems: 'center', backgroundColor: Palette.bg.wash, borderRadius: Radius.lg, borderWidth: 1, borderColor: Palette.border.subtle, marginVertical: Spacing.md }}>
                    <Ionicons name="document-text-outline" size={32} color={Palette.text.tertiary} style={{ marginBottom: Spacing.xs }} />
                    <Text style={[styles.itemName, { textAlign: 'center', marginBottom: 4 }]}>線上查無此店菜單</Text>
                    <Text style={[styles.restaurantMeta, { textAlign: 'center' }]}>
                      您可以點擊店卡中的「AI 摘要」預測其常規品項，或使用頁面右下角的「相機掃描」拍照記錄實體菜單！
                    </Text>
                  </View>
                ) : (
                  <>
                    {(viewingMenuRest?.recommended_items || []).length === 0 ? (
                      <Text style={styles.emptyText}>沒有符合條件的餐點</Text>
                    ) : (
                      (viewingMenuRest?.recommended_items || []).map((item) => (
                        <View key={item.item_name} style={styles.menuItemCard}>
                          <View style={styles.menuItemHeader}>
                            <Text style={styles.menuItemName}>{item.item_name}</Text>
                            <Text style={styles.menuItemPrice}>${item.price}</Text>
                          </View>
                          <View style={styles.nutritionRow}>
                            <NutritionMini label="熱量" value={`${item.calories} kcal`} color={Palette.accent.green} />
                            <NutritionMini label="蛋白質" value={`${item.protein} g`} color={Palette.accent.blue} />
                            <NutritionMini label="鈉" value={`${item.sodium} mg`} color={Palette.accent.pink} />
                          </View>
                          {item.reasons && item.reasons.length > 0 ? (
                            <Text style={styles.customizationText}>判定依據：{item.reasons.join('、')}</Text>
                          ) : null}
                          <View style={{ marginTop: Spacing.xs, alignItems: 'flex-end' }}>
                            <SecondaryButton
                              disabled={addingFoodName === item.item_name}
                              label={addingFoodName === item.item_name ? '新增中...' : '+ 加入今日紀錄'}
                              onPress={() => handleQuickAddRecord(item)}
                              icon={<Ionicons name="add-circle-outline" size={14} color={Palette.accent.green} />}
                            />
                          </View>
                        </View>
                      ))
                    )}

                    <Text style={[styles.modalSectionTitle, { marginTop: Spacing.xl }]}>不符合 / 需注意餐點</Text>
                    {(viewingMenuRest?.filtered_items || []).length === 0 ? (
                      <Text style={styles.emptyText}>此店無需要排除的餐點</Text>
                    ) : (
                      (viewingMenuRest?.filtered_items || []).map((item) => (
                        <View key={item.item_name} style={[styles.menuItemCard, { borderColor: Palette.status.warning }]}>
                          <View style={styles.menuItemHeader}>
                            <Text style={[styles.menuItemName, { color: Palette.status.warning }]}>{item.item_name}</Text>
                          </View>
                          {item.reasons && item.reasons.length > 0 ? (
                            <Text style={styles.warningText}>⚠️ 排除原因：{item.reasons.join('、')}</Text>
                          ) : null}
                        </View>
                      ))
                    )}
                  </>
                )}

              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

    </AppContainer>
  );
}

function RestaurantCard({
  restaurant,
  index,
  selected,
  summary,
  summaryLoading,
  addingFoodName,
  onSelect,
  onSummary,
  onNavigate,
  onViewMenu,
  onOpenRestaurantWebsite,
  onOpenRestaurantInfo,
  onQuickAddRecord,
}: {
  restaurant: HealthyFoodRestaurant;
  index: number;
  selected: boolean;
  summary?: RestaurantAiSummary;
  summaryLoading: boolean;
  addingFoodName: string | null;
  onSelect: () => void;
  onSummary: () => void;
  onNavigate: () => void;
  onViewMenu: () => void;
  onOpenRestaurantWebsite: () => void;
  onOpenRestaurantInfo: () => void;
  onQuickAddRecord: (item: any) => void;
}) {
  return (
    <View style={[styles.restaurantCard, selected && styles.restaurantCardSelected]}>
      <View style={styles.mealTop}>
        <View style={styles.rankBadge}><Text style={styles.rankText}>{index + 1}</Text></View>
        <View style={styles.mealInfo}>
          <Text style={styles.restaurantName}>{restaurant.name}</Text>
          <Text style={styles.restaurantMeta}>{restaurant.tags.slice(0, 2).join('、')} · {restaurant.distance_km} km · {restaurant.is_open ? '營業中' : '未營業'}</Text>
        </View>
        <DataPill tone="info">{restaurant.match_score}</DataPill>
      </View>
      <View style={styles.pillRow}>
        {restaurant.tags.slice(0, 4).map((tag) => <DataPill key={tag} tone="success">{tag}</DataPill>)}
      </View>
      {restaurant.recommended_items.slice(0, 5).map((item) => (
        <View key={`${restaurant.restaurant_id}_${item.item_id || item.item_name}`} style={styles.restaurantItem}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={styles.itemName}>{item.item_name}</Text>
            <SecondaryButton
              disabled={addingFoodName === item.item_name}
              label={addingFoodName === item.item_name ? '新增中' : '+ 加入今日紀錄'}
              onPress={() => onQuickAddRecord(item)}
              icon={<Ionicons name="add-circle-outline" size={13} color={Palette.accent.green} />}
            />
          </View>
          {item.nutrition_available ? (
            <View style={styles.nutritionRow}>
              <NutritionMini label="熱量" value={`${item.calories} kcal`} color={Palette.accent.green} />
              <NutritionMini label="蛋白質" value={`${item.protein} g`} color={Palette.accent.blue} />
              <NutritionMini label="鈉" value={`${item.sodium} mg`} color={Palette.accent.pink} />
            </View>
          ) : (
            <Text style={styles.restaurantMeta}>菜單價格與營養資料需到店後用掃描或手動搜尋確認。</Text>
          )}
        </View>
      ))}
      <View style={styles.restaurantActions}>
        <SecondaryButton label="完整菜單" onPress={onViewMenu} icon={<Ionicons name="restaurant-outline" size={14} color={Palette.accent.green} />} />
        {restaurant.menu_link ? (
          <SecondaryButton label="店家網站" onPress={onOpenRestaurantWebsite} icon={<Ionicons name="open-outline" size={14} color={Palette.accent.green} />} />
        ) : null}
        <SecondaryButton label="地圖標示" onPress={onSelect} />
        <SecondaryButton label={summaryLoading ? '產生中' : 'AI 摘要'} onPress={onSummary} />
        <SecondaryButton label="導航" onPress={onNavigate} />
      </View>
      {summary ? (
        <View style={styles.aiSummaryBox}>
          <Text style={styles.itemName}>AI 推測：{summary.restaurant_type}</Text>
          <Text style={styles.restaurantMeta}>可能販售：{summary.likely_foods.join('、') || '不確定'}</Text>
          <Text style={styles.restaurantMeta}>價格：約 {summary.price_range_twd.min}-{summary.price_range_twd.max} 元 · 預算：{summary.budget_fit}</Text>
          {(summary.recommended_foods || []).length ? (
            <View style={styles.personalizedRecommendations}>
              <View style={styles.personalizedTitleRow}>
                <Ionicons name="sparkles-outline" size={16} color={Palette.accent.green} />
                <Text style={styles.personalizedTitle}>疾病與今日進度提醒</Text>
              </View>
              {(summary.recommended_foods || []).map((item, itemIndex) => (
                <View key={`${item.name}_${itemIndex}`} style={[styles.personalizedItem, { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }]}>
                  <View style={{ flex: 1, paddingRight: Spacing.sm }}>
                    <Text style={styles.personalizedFood}>{item.name}</Text>
                    <Text style={styles.restaurantMeta}>{item.reason}</Text>
                  </View>
                  <SecondaryButton
                    disabled={addingFoodName === item.name}
                    label={addingFoodName === item.name ? '新增中' : '+ 加入今日紀錄'}
                    onPress={() => onQuickAddRecord({ name: item.name, calories: 400, protein: 18, carbs: 45, fat: 12, sodium: 550 })}
                    icon={<Ionicons name="add-circle-outline" size={13} color={Palette.accent.green} />}
                  />
                </View>
              ))}
            </View>
          ) : null}
          <Text style={styles.restaurantMeta}>建議：{summary.health_tips.join('、') || '到店後確認餐點內容'}</Text>
          <Text style={styles.errorMeta}>{summary.source_note}</Text>
        </View>
      ) : null}
    </View>
  );
}


function NutritionMini({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={styles.nutritionMini}>
      <Text style={styles.nutritionMiniLabel}>{label}</Text>
      <Text style={[styles.nutritionMiniValue, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  emptyText: { ...Typography.body, color: Palette.text.tertiary, textAlign: 'center' },
  mealTop: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.md },
  mealInfo: { flex: 1, gap: Spacing.sm },
  pillRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutritionRow: { flexDirection: 'row', gap: Spacing.sm },
  nutritionMini: { flex: 1, backgroundColor: Palette.bg.card, borderRadius: Radius.lg, padding: Spacing.sm },
  nutritionMiniLabel: { ...Typography.small, color: Palette.text.tertiary },
  nutritionMiniValue: { ...Typography.caption, ...Typography.number },
  budgetRow: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'center', marginBottom: Spacing.md },
  budgetInput: {
    flex: 1,
    minHeight: 48,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    ...Typography.caption,
  },
  optionLabel: { ...Typography.small, color: Palette.text.tertiary, marginTop: Spacing.md, marginBottom: Spacing.sm },
  categoryWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  categoryChip: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    justifyContent: 'center',
  },
  categoryChipActive: { borderColor: 'rgba(31,157,114,0.26)', backgroundColor: Palette.accent.greenDim },
  categoryText: { ...Typography.small, color: Palette.text.secondary },
  categoryTextActive: { color: Palette.accent.green },
  locationText: { ...Typography.small, color: Palette.text.tertiary, marginTop: Spacing.md },
  apiErrorBox: {
    marginTop: Spacing.sm,
    backgroundColor: Palette.accent.orangeDim,
    borderColor: 'rgba(245,158,11,0.2)',
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.sm,
  },
  errorText: { ...Typography.small, color: Palette.status.warning },
  errorMeta: { ...Typography.small, color: Palette.text.tertiary, marginTop: 2 },
  mapCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.md,
    ...Shadows.card,
  },
  selectedMapInfo: { marginTop: Spacing.md, gap: Spacing.sm, backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md },
  mapTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm },
  restaurantCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.lg,
    gap: Spacing.md,
    ...Shadows.soft,
  },
  restaurantCardSelected: { borderColor: 'rgba(31,157,114,0.36)' },
  rankBadge: { width: 38, height: 38, borderRadius: 19, backgroundColor: Palette.bg.mint, alignItems: 'center', justifyContent: 'center' },
  rankText: { ...Typography.bodyBold, color: Palette.accent.green },
  restaurantName: { ...Typography.bodyBold, color: Palette.text.primary, flex: 1 },
  restaurantMeta: { ...Typography.caption, color: Palette.text.secondary },
  restaurantItem: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md, gap: Spacing.sm },
  itemName: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  restaurantActions: { flexDirection: 'row', gap: Spacing.sm, flexWrap: 'wrap' },
  aiSummaryBox: {
    gap: Spacing.sm,
    backgroundColor: Palette.accent.blueDim,
    borderColor: 'rgba(47,128,237,0.18)',
    borderWidth: 1,
    borderRadius: Radius.lg,
    padding: Spacing.md,
  },
  personalizedRecommendations: { borderTopWidth: 1, borderTopColor: Palette.border.subtle, paddingTop: Spacing.sm, gap: Spacing.sm },
  personalizedTitleRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.xs },
  personalizedTitle: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  personalizedItem: { gap: 2 },
  personalizedFood: { ...Typography.caption, color: Palette.accent.green, fontWeight: '700' },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center', alignItems: 'center', padding: Spacing.lg },
  modalContent: { width: '100%', maxWidth: 500, maxHeight: '80%', backgroundColor: Palette.bg.card, borderRadius: Radius.xl, borderWidth: 1, borderColor: Palette.border.subtle, padding: Spacing.lg, ...Shadows.soft },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: Spacing.md },
  modalTitle: { ...Typography.bodyBold, color: Palette.text.primary },
  modalScroll: { gap: Spacing.md },
  modalSectionTitle: { ...Typography.bodyBold, color: Palette.text.primary, marginTop: Spacing.sm },
  menuItemCard: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, borderWidth: 1, borderColor: Palette.border.subtle, padding: Spacing.md, gap: Spacing.sm },
  menuItemHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  menuItemName: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  menuItemPrice: { ...Typography.caption, color: Palette.text.secondary },
  customizationText: { ...Typography.small, color: Palette.accent.green, marginTop: Spacing.xs },
  warningText: { ...Typography.small, color: Palette.status.warning, marginTop: Spacing.xs },
});

