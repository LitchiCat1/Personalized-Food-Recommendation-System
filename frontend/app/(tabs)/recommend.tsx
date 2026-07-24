import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TextInput, Pressable, Linking, Modal, ScrollView, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { router } from 'expo-router';

import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import MetricCard from '@/components/ui/metric-card';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import SegmentedControl from '@/components/ui/segmented-control';
import FoodMap from '@/components/maps/FoodMap';
import { useResponsive } from '@/hooks/useResponsive';
import {
  fetchHealthyFoodRecommendations,
  fetchRestaurantAiSummary,
  fetchRecommendations,
  saveRecommendationFeedback,
  scrapeAndEnrichRestaurant,
  addDietaryRecord,
  fetchRecords,
  type HealthyFoodRestaurant,
  type RestaurantAiSummary,
  type RecommendationFeedbackAction,
  type HealthyFoodResponse,
  type RecommendationItem,
  type RecommendationResponse,
} from '@/lib/api';
import { Alert } from 'react-native';





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
  const { isDesktop } = useResponsive();
  const { user, apiBaseUrl, accessToken } = useStore();
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [healthyData, setHealthyData] = useState<HealthyFoodResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [healthyLoading, setHealthyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [healthyError, setHealthyError] = useState<string | null>(null);
  const [feedbackStatus, setFeedbackStatus] = useState<Record<string, RecommendationFeedbackAction>>({});
  const [feedbackSavingKey, setFeedbackSavingKey] = useState<string | null>(null);
  const [summaryByRestaurant, setSummaryByRestaurant] = useState<Record<string, RestaurantAiSummary>>({});
  const [summaryLoadingKey, setSummaryLoadingKey] = useState<string | null>(null);
  const [budget, setBudget] = useState('150');
  const [radiusKm, setRadiusKm] = useState(3);
  const [category, setCategory] = useState('all');
  const [selectedRestaurantId, setSelectedRestaurantId] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState('尚未取得定位');
  const [showAllMeals, setShowAllMeals] = useState(false);

  const [viewingMenuRest, setViewingMenuRest] = useState<HealthyFoodRestaurant | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const handleAiEnrichForViewingRest = async () => {
    if (!viewingMenuRest) return;
    setAiLoading(true);
    try {
      const res = await scrapeAndEnrichRestaurant(
        apiBaseUrl,
        {
          restaurant_name: viewingMenuRest.name,
          address: viewingMenuRest.address || '台灣',
        },
        { accessToken }
      );
      const enrichedRest = {
        ...viewingMenuRest,
        items: res.restaurant.items,
      };
      setViewingMenuRest(enrichedRest);
      if (healthyData) {
        const updatedRests = healthyData.restaurants?.map((r) =>
          r.restaurant_id === viewingMenuRest.restaurant_id ? enrichedRest : r
        );
        setHealthyData({ ...healthyData, restaurants: updatedRests });
      }
      Alert.alert('AI 分析成功', `已成功建立「${viewingMenuRest.name}」的完整菜單！`);
    } catch (err: any) {
      Alert.alert('AI 分析失敗', err.message || 'Gemini AI 目前忙碌中，請稍後再試。');
    } finally {
      setAiLoading(false);
    }
  };

  const handleAddRecordFromMenu = (item: any) => {
    Alert.alert(
      '新增飲食紀錄',
      `您要將「${item.name || item.item_name}」記錄至今日的哪個時段？`,
      [
        { text: '取消', style: 'cancel' },
        { text: '🍳 早餐', onPress: () => executeAddRecord(item, '早餐') },
        { text: '🍱 午餐', onPress: () => executeAddRecord(item, '午餐') },
        { text: '🍛 晚餐', onPress: () => executeAddRecord(item, '晚餐') },
        { text: '🍰 點心', onPress: () => executeAddRecord(item, '點心') },
      ]
    );
  };

  const executeAddRecord = async (item: any, mealType: string) => {
    try {
      const foodPayload = {
        name: `${viewingMenuRest?.name} - ${item.name || item.item_name}`,
        calories: Number(item.calories || 0),
        protein: Number(item.protein || 0),
        carbs: Number(item.carbs || 0),
        fat: Number(item.fat || 0),
        sodium: Number(item.sodium || 0),
        fiber: Number(item.fiber || 0),
        source: 'manual',
      };
      const payload = {
        user_id: user.userId,
        meal_type: mealType,
        foods: [foodPayload],
        total_calories: foodPayload.calories,
        total_protein: foodPayload.protein,
        total_carbs: foodPayload.carbs,
        total_fat: foodPayload.fat,
        total_sodium: foodPayload.sodium,
        total_fiber: foodPayload.fiber,
        source: 'manual',
      };
      await addDietaryRecord(apiBaseUrl, payload, { accessToken });
      
      const now = new Date();
      const yyyy = now.getFullYear();
      const mm = String(now.getMonth() + 1).padStart(2, '0');
      const dd = String(now.getDate()).padStart(2, '0');
      const dateStr = `${yyyy}-${mm}-${dd}`;
      const recordsData = await fetchRecords(apiBaseUrl, user.userId, dateStr, { accessToken });
      useStore.getState().replaceDashboardFromRecords(recordsData.records || []);

      Alert.alert('記錄成功', `已成功將「${foodPayload.name}」加入今日${mealType}！`);
    } catch (err: any) {
      Alert.alert('記錄失敗', err.message || '無法寫入紀錄');
    }
  };



  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchRecommendations(apiBaseUrl, user.userId, { accessToken })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiBaseUrl, user.userId]);

  const recommended = data?.recommended || [];
  const sourceCounts = data?.source_counts;
  const preferenceProfile = data?.preference_profile;
  const remaining = data?.remaining_calories ?? user.dailyCalorieTarget;
  const mapRestaurants = healthyData?.restaurants || [];
  const mapLocation = healthyData?.location || null;
  const selectedRestaurant = mapRestaurants.find((restaurant) => restaurant.restaurant_id === selectedRestaurantId) || mapRestaurants[0] || null;

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
        setTimeout(() => reject(new Error('timeout')), 1500)
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


  const handleRecommendationFeedback = async (meal: RecommendationItem, action: RecommendationFeedbackAction) => {
    const key = meal.label;
    setFeedbackSavingKey(key);
    try {
      await saveRecommendationFeedback(apiBaseUrl, user.userId, action, meal, { accessToken });
      setFeedbackStatus((current) => ({ ...current, [key]: action }));
    } catch (err: any) {
      setError(err?.message || '推薦回饋儲存失敗');
    } finally {
      setFeedbackSavingKey(null);
    }
  };

  const handleOpenNavigation = async (restaurant: HealthyFoodRestaurant) => {
    try {
      await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${restaurant.lat},${restaurant.lng}&travelmode=walking`);
    } catch (err: any) {
      setHealthyError(err?.message || '無法開啟 Google Maps 導航');
    }
  };

  const handleLoadRestaurantSummary = async (restaurant: HealthyFoodRestaurant) => {
    setHealthyError(null);
    setSummaryLoadingKey(restaurant.restaurant_id);
    try {
      const response = await fetchRestaurantAiSummary(apiBaseUrl, user.userId, { restaurant, budget: Number(budget) || 150, category }, { accessToken });
      setSummaryByRestaurant((current) => ({ ...current, [restaurant.restaurant_id]: response.summary }));
    } catch (err: any) {
      setHealthyError(err?.message || 'AI 店家摘要產生失敗');
    } finally {
      setSummaryLoadingKey(null);
    }
  };

  return (
    <AppContainer>
      <ScreenHeader
        title="智慧推薦"
        subtitle="查看符合個人條件的餐點，再用定位找附近可行店家。"
        badge="安全過濾"
        badgeTone="success"
      />

      {loading ? (
        <StateCard icon="sparkles-outline" text="讀取推薦中..." loading />
      ) : error ? (
        <View style={styles.stateCard}>
          <Ionicons name="person-add-outline" size={40} color={Palette.status.warning} />
          <Text style={styles.emptyText}>{error}</Text>
          <View style={{ marginTop: Spacing.md, width: '100%', maxWidth: 280 }}>
            <PrimaryButton
              label="立即填寫個人檔案"
              onPress={() => router.push('/profile')}
              icon={<Ionicons name="arrow-forward-outline" size={17} color={Palette.text.inverse} />}
            />
          </View>
        </View>

      ) : (
        <>
          <View style={styles.metricRow}>
            <MetricCard label="剩餘熱量" value={remaining} unit="kcal" accent={Palette.accent.green} />
            <MetricCard label="可推薦" value={recommended.length} unit="項" accent={Palette.accent.blue} />
          </View>

          <View style={isDesktop ? styles.desktopColumns : styles.recommendSections}>

          <View style={isDesktop ? styles.desktopPane : undefined}>

          <SectionBlock title="餐點推薦" subtitle="依熱量契合、疾病禁忌、過敏原和近期偏好排序。">
            <View style={styles.sourceSummary}>
              {sourceCounts ? <DataPill tone="info">TFDA {sourceCounts.tfda} · 自訂 {sourceCounts.custom_foods} · 基礎 {sourceCounts.manual_db}</DataPill> : null}
              {preferenceProfile && preferenceProfile.food_count > 0 ? <DataPill tone="success">參考 {preferenceProfile.record_count} 筆紀錄</DataPill> : null}
              <DataPill tone={user.healthConditions.length ? 'warning' : 'success'}>{user.healthConditions.length ? user.healthConditions.join('、') : '未設定疾病'}</DataPill>
            </View>

            <View style={styles.recommendList}>
              {recommended.length === 0 ? (
                <Text style={styles.emptyText}>目前找不到符合條件的推薦，請先調整個人條件或新增更多食品資料。</Text>
              ) : (
                (showAllMeals ? recommended : recommended.slice(0, 3)).map((meal, index) => (
                  <RecommendationCard
                    key={`${meal.label}_${index}`}
                    meal={meal}
                    feedbackStatus={feedbackStatus[meal.label]}
                    saving={feedbackSavingKey === meal.label}
                    onFeedback={(action) => handleRecommendationFeedback(meal, action)}
                  />
                ))
              )}
              {recommended.length > 3 ? (
                <SecondaryButton label={showAllMeals ? '收合推薦' : `查看其餘 ${recommended.length - 3} 項`} onPress={() => setShowAllMeals((value) => !value)} icon={<Ionicons name={showAllMeals ? 'chevron-up' : 'chevron-down'} size={16} color={Palette.accent.green} />} />
              ) : null}
            </View>
          </SectionBlock>
          </View>

          <View style={isDesktop ? styles.desktopPane : undefined}>
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
                  selected={selectedRestaurantId === restaurant.restaurant_id}
                  summary={summaryByRestaurant[restaurant.restaurant_id]}
                  summaryLoading={summaryLoadingKey === restaurant.restaurant_id}
                  onSelect={() => setSelectedRestaurantId(restaurant.restaurant_id)}
                  onSummary={() => handleLoadRestaurantSummary(restaurant)}
                  onNavigate={() => handleOpenNavigation(restaurant)}
                  onViewMenu={() => setViewingMenuRest(restaurant)}
                />
              ))}
            </>
          ) : null}
          </View>
          </View>
        </>
      )}

      {/* 完整菜單詳細 Modal 彈窗 */}
      <Modal
        visible={viewingMenuRest !== null}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setViewingMenuRest(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle} numberOfLines={1}>{viewingMenuRest?.name}</Text>
              <Pressable onPress={() => setViewingMenuRest(null)}>
                <Ionicons name="close" size={24} color={Palette.text.primary} />
              </Pressable>
            </View>

            <ScrollView contentContainerStyle={styles.modalScroll} showsVerticalScrollIndicator={false}>
              <Text style={styles.restaurantMeta}>📍 {viewingMenuRest?.address || '尚無地址'}</Text>

              {/* 1. 安全餐點推薦 */}
              <Text style={styles.modalSectionTitle}>🌟 安全餐點推薦</Text>
              {(viewingMenuRest?.recommended_items || []).length === 0 ? (
                <Text style={styles.emptyText}>無推薦的餐點</Text>
              ) : (
                (viewingMenuRest?.recommended_items || []).map((item, idx) => (
                  <View key={idx} style={styles.menuItemCard}>
                    <View style={styles.menuItemHeader}>
                      <Text style={styles.menuItemName}>{item.item_name}</Text>
                      <View style={{ flexDirection: 'row', gap: Spacing.sm, alignItems: 'center' }}>
                        <Text style={styles.menuItemPrice}>${item.price}</Text>
                        <TouchableOpacity
                          style={{ backgroundColor: Palette.accent.green, borderRadius: Radius.sm, paddingHorizontal: Spacing.sm, paddingVertical: 4 }}
                          onPress={() => handleAddRecordFromMenu(item)}
                        >
                          <Text style={{ fontSize: 11, fontWeight: '700', color: Palette.text.inverse }}>＋記錄</Text>
                        </TouchableOpacity>
                      </View>
                    </View>
                    <View style={styles.nutritionRow}>
                      <NutritionMini label="熱量" value={`${item.calories} kcal`} color={Palette.accent.green} />
                      <NutritionMini label="蛋白質" value={`${item.protein} g`} color={Palette.accent.blue} />
                      <NutritionMini label="鈉" value={`${item.sodium} mg`} color={Palette.accent.pink} />
                    </View>
                    {item.reasons && item.reasons.length > 0 ? (
                      <Text style={styles.customizationText}>💡 推薦原因：{item.reasons.join('、')}</Text>
                    ) : null}
                  </View>
                ))
              )}

              {/* 2. 不符合 / 需注意餐點 */}
              <Text style={[styles.modalSectionTitle, { marginTop: Spacing.lg }]}>⚠️ 需注意餐點</Text>
              {(viewingMenuRest?.filtered_items || []).length === 0 ? (
                <Text style={styles.emptyText}>此店無需要排除的餐點</Text>
              ) : (
                (viewingMenuRest?.filtered_items || []).map((item, idx) => (
                  <View key={idx} style={[styles.menuItemCard, { borderColor: Palette.status.warning }]}>
                    <View style={styles.menuItemHeader}>
                      <Text style={[styles.menuItemName, { color: Palette.status.warning }]}>{item.item_name}</Text>
                    </View>
                    {item.reasons && item.reasons.length > 0 ? (
                      <Text style={styles.warningText}>⚠️ 排除原因：{item.reasons.join('、')}</Text>
                    ) : null}
                  </View>
                ))
              )}

              {/* 3. 完整菜單 */}
              <Text style={[styles.modalSectionTitle, { marginTop: Spacing.lg }]}>📋 完整菜單</Text>
              {viewingMenuRest?.items && viewingMenuRest.items.length > 0 ? (
                viewingMenuRest.items.map((item: any, idx: number) => (
                  <View key={idx} style={styles.menuItemCard}>
                    <View style={styles.menuItemHeader}>
                      <Text style={styles.menuItemName}>{item.name || item.item_name}</Text>
                      <View style={{ flexDirection: 'row', gap: Spacing.sm, alignItems: 'center' }}>
                        {item.price ? <Text style={styles.menuItemPrice}>${item.price}</Text> : null}
                        <TouchableOpacity
                          style={{ backgroundColor: Palette.accent.green, borderRadius: Radius.sm, paddingHorizontal: Spacing.sm, paddingVertical: 4 }}
                          onPress={() => handleAddRecordFromMenu(item)}
                        >
                          <Text style={{ fontSize: 11, fontWeight: '700', color: Palette.text.inverse }}>＋記錄</Text>
                        </TouchableOpacity>
                      </View>
                    </View>
                    <View style={styles.nutritionRow}>
                      <NutritionMini label="熱量" value={`${item.calories} kcal`} color={Palette.accent.green} />
                      <NutritionMini label="蛋白質" value={`${item.protein} g`} color={Palette.accent.blue} />
                      <NutritionMini label="鈉" value={`${item.sodium} mg`} color={Palette.accent.pink} />
                    </View>
                  </View>
                ))
              ) : (
                <View style={{ backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.lg, alignItems: 'center', gap: Spacing.md, borderWidth: 1, borderColor: Palette.border.subtle }}>
                  <Text style={[styles.emptyText, { fontSize: 13 }]}>尚未建立此店的完整菜單與營養分析。</Text>
                  <TouchableOpacity
                    style={{ flexDirection: 'row', backgroundColor: Palette.accent.purple, borderRadius: Radius.md, paddingVertical: 8, paddingHorizontal: Spacing.lg, alignItems: 'center' }}
                    onPress={handleAiEnrichForViewingRest}
                    disabled={aiLoading}
                  >
                    {aiLoading ? (
                      <ActivityIndicator size="small" color={Palette.text.inverse} />
                    ) : (
                      <>
                        <Ionicons name="sparkles" size={14} color={Palette.text.inverse} style={{ marginRight: 6 }} />
                        <Text style={{ ...Typography.caption, fontWeight: '700', color: Palette.text.inverse }}>請 AI 立即爬取與標註菜單</Text>
                      </>
                    )}
                  </TouchableOpacity>
                </View>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </AppContainer>
  );
}


function StateCard({ icon, text, loading, tone }: { icon: keyof typeof Ionicons.glyphMap; text: string; loading?: boolean; tone?: 'warning' }) {
  return (
    <View style={styles.stateCard}>
      {loading ? <ActivityIndicator size="large" color={Palette.accent.green} /> : <Ionicons name={icon} size={30} color={tone === 'warning' ? Palette.status.warning : Palette.text.tertiary} />}
      <Text style={styles.emptyText}>{text}</Text>
    </View>
  );
}

function RecommendationCard({
  meal,
  feedbackStatus,
  saving,
  onFeedback,
}: {
  meal: RecommendationItem;
  feedbackStatus?: RecommendationFeedbackAction;
  saving: boolean;
  onFeedback: (action: RecommendationFeedbackAction) => void;
}) {
  return (
    <View style={styles.mealCard}>
      <View style={styles.mealTop}>
        <View style={styles.mealInfo}>
          <Text style={styles.mealName}>{meal.name_zh}</Text>
          <View style={styles.pillRow}>
            <DataPill tone="success">{meal.source === 'TFDA' ? 'TFDA 官方資料' : meal.source === 'manual-db' ? '基礎資料庫' : '自訂食品'}</DataPill>
            {meal.gi ? <DataPill tone={meal.gi === 'high' ? 'danger' : meal.gi === 'medium' ? 'warning' : 'success'}>GI {meal.gi === 'low' ? '低' : meal.gi === 'medium' ? '中' : '高'}</DataPill> : null}
          </View>
        </View>
        <View style={styles.scoreBox}>
          <Text style={styles.scoreValue}>{meal.match_score}</Text>
          <Text style={styles.scoreLabel}>契合</Text>
        </View>
      </View>
      <View style={styles.reasonBox}>
        {(meal.preference_reasons || []).length > 0 ? (
          (meal.preference_reasons || []).map((reason) => <Text key={reason} style={styles.reasonText}>因為 {reason}</Text>)
        ) : (
          <Text style={styles.reasonText}>已通過健康條件與過敏原安全篩選。</Text>
        )}
      </View>
      <View style={styles.nutritionRow}>
        <NutritionMini label="熱量" value={`${meal.calories} kcal`} color={Palette.accent.green} />
        <NutritionMini label="蛋白質" value={`${meal.protein} g`} color={Palette.accent.blue} />
        <NutritionMini label="鈉" value={`${meal.sodium} mg`} color={meal.sodium > 800 ? Palette.status.warning : Palette.accent.pink} />
      </View>
      <View style={styles.feedbackRow}>
        {[
          { action: 'accepted' as const, label: '採納', icon: 'checkmark-circle-outline' as const },
          { action: 'skipped' as const, label: '略過', icon: 'play-skip-forward-outline' as const },
          { action: 'disliked' as const, label: '不喜歡', icon: 'thumbs-down-outline' as const },
        ].map((item) => {
          const active = feedbackStatus === item.action;
          return (
            <Pressable
              key={item.action}
              disabled={saving}
              accessibilityRole="button"
              accessibilityLabel={`推薦回饋：${item.label}`}
              accessibilityState={{ selected: active, disabled: saving }}
              onPress={() => onFeedback(item.action)}
              style={[styles.feedbackButton, active && styles.feedbackButtonActive]}
            >
              {saving && item.action === 'accepted' ? <ActivityIndicator size="small" color={Palette.accent.green} /> : <Ionicons name={item.icon} size={13} color={active ? Palette.accent.green : Palette.text.tertiary} />}
              <Text style={[styles.feedbackButtonText, active && styles.feedbackButtonTextActive]}>{item.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function RestaurantCard({
  restaurant,
  index,
  selected,
  summary,
  summaryLoading,
  onSelect,
  onSummary,
  onNavigate,
  onViewMenu,
}: {
  restaurant: HealthyFoodRestaurant;
  index: number;
  selected: boolean;
  summary?: RestaurantAiSummary;
  summaryLoading: boolean;
  onSelect: () => void;
  onSummary: () => void;
  onNavigate: () => void;
  onViewMenu: () => void;
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
      {restaurant.recommended_items.slice(0, 2).map((item) => (
        <View key={`${restaurant.restaurant_id}_${item.item_id || item.item_name}`} style={styles.restaurantItem}>
          <Text style={styles.itemName}>{item.item_name}</Text>
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
                <Text style={styles.personalizedTitle}>依疾病與今日進度推薦</Text>
              </View>
              {(summary.recommended_foods || []).map((item, itemIndex) => (
                <View key={`${item.name}_${itemIndex}`} style={styles.personalizedItem}>
                  <Text style={styles.personalizedFood}>{item.name}</Text>
                  <Text style={styles.restaurantMeta}>{item.reason}</Text>
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
  metricRow: { flexDirection: 'row', gap: Spacing.sm, marginBottom: Spacing.xl },
  recommendSections: { gap: Spacing.xl },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xl },
  desktopPane: { flex: 1, minWidth: 0 },
  stateCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    alignItems: 'center',
    gap: Spacing.md,
    padding: Spacing['3xl'],
    ...Shadows.card,
  },
  emptyText: { ...Typography.body, color: Palette.text.tertiary, textAlign: 'center' },
  sourceSummary: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, marginBottom: Spacing.lg },
  recommendList: { gap: Spacing.md, marginTop: Spacing.lg },
  mealCard: {
    backgroundColor: Palette.bg.wash,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.lg,
    gap: Spacing.md,
  },
  mealTop: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.md },
  mealInfo: { flex: 1, gap: Spacing.sm },
  mealName: { ...Typography.bodyBold, color: Palette.text.primary },
  pillRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  scoreBox: { alignItems: 'center', minWidth: 48 },
  scoreValue: { ...Typography.h2, ...Typography.number, color: Palette.accent.green },
  scoreLabel: { ...Typography.small, color: Palette.text.tertiary },
  reasonBox: { backgroundColor: Palette.bg.mint, borderRadius: Radius.lg, padding: Spacing.md, gap: 2 },
  reasonText: { ...Typography.caption, color: Palette.text.secondary },
  nutritionRow: { flexDirection: 'row', gap: Spacing.sm },
  nutritionMini: { flex: 1, backgroundColor: Palette.bg.card, borderRadius: Radius.lg, padding: Spacing.sm },
  nutritionMiniLabel: { ...Typography.small, color: Palette.text.tertiary },
  nutritionMiniValue: { ...Typography.caption, ...Typography.number },
  feedbackRow: { flexDirection: 'row', gap: Spacing.sm },
  feedbackButton: {
    flex: 1,
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.card,
  },
  feedbackButtonActive: { borderColor: 'rgba(31,157,114,0.26)', backgroundColor: Palette.accent.greenDim },
  feedbackButtonText: { ...Typography.small, color: Palette.text.tertiary },
  feedbackButtonTextActive: { color: Palette.accent.green },
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
  importFormRow: { flexDirection: 'row', gap: Spacing.sm },
  apiSuccessBox: {
    marginTop: Spacing.sm,
    backgroundColor: Palette.bg.mint,
    borderColor: 'rgba(31,157,114,0.2)',
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.sm,
  },
  successText: { ...Typography.small, color: Palette.accent.green },
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


