import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TextInput, Pressable, Linking } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import FoodMap from '@/components/maps/FoodMap';
import {
  fetchHealthyFoodRecommendations,
  fetchRecommendations,
  saveRecommendationFeedback,
  type HealthyFoodRestaurant,
  type RecommendationFeedbackAction,
  type HealthyFoodResponse,
  type RecommendationItem,
  type RecommendationResponse,
} from '@/lib/api';

function formatReason(item: RecommendationItem) {
  if (!item.reasons || item.reasons.length === 0) return '已由安全規則排除';
  return item.reasons.join('、');
}

const RADIUS_OPTIONS = [1, 3, 5];
const CATEGORY_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: '便當', label: '便當' },
  { value: '小吃', label: '小吃' },
  { value: '早餐', label: '早餐' },
  { value: '飲料', label: '飲料' },
  { value: '沙拉', label: '沙拉' },
];

export default function RecommendScreen() {
  const { rs, isSmall } = useResponsive();
  const { user, apiBaseUrl, accessToken } = useStore();
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [healthyData, setHealthyData] = useState<HealthyFoodResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [healthyLoading, setHealthyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [healthyError, setHealthyError] = useState<string | null>(null);
  const [feedbackStatus, setFeedbackStatus] = useState<Record<string, RecommendationFeedbackAction>>({});
  const [feedbackSavingKey, setFeedbackSavingKey] = useState<string | null>(null);
  const [budget, setBudget] = useState('150');
  const [radiusKm, setRadiusKm] = useState(3);
  const [category, setCategory] = useState('all');
  const [selectedRestaurantId, setSelectedRestaurantId] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState('尚未取得定位');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchRecommendations(apiBaseUrl, user.userId, { accessToken })
      .then((result) => {
        if (!cancelled) {
          setData(result);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiBaseUrl, user.userId]);

  const recommended = data?.recommended || [];
  const filteredOut = data?.filtered_out || [];
  const totalFiltered = data?.total_filtered ?? filteredOut.length;
  const sourceCounts = data?.source_counts;
  const preferenceProfile = data?.preference_profile;
  const remaining = data?.remaining_calories ?? user.dailyCalorieTarget;

  const handleHealthyFoodSearch = async () => {
    setHealthyLoading(true);
    setHealthyError(null);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) {
        throw new Error('未授權定位權限');
      }
      const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      setLocationLabel(`目前定位：${lat.toFixed(4)}, ${lng.toFixed(4)}`);
      const result = await fetchHealthyFoodRecommendations(
        apiBaseUrl,
        user.userId,
        {
          budget: Number(budget) || 150,
          lat,
          lng,
          radiusKm,
          category,
        },
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

  const mapRestaurants = healthyData?.restaurants || [];
  const mapLocation = healthyData?.location || null;
  const selectedRestaurant = mapRestaurants.find((restaurant) => restaurant.restaurant_id === selectedRestaurantId) || mapRestaurants[0] || null;

  const handleOpenNavigation = async (restaurant: HealthyFoodRestaurant) => {
    try {
      await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${restaurant.lat},${restaurant.lng}&travelmode=walking`);
    } catch (err: any) {
      setHealthyError(err?.message || '無法開啟 Google Maps 導航');
    }
  };

  return (
    <AppContainer>
      <View style={styles.header}>
        <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>智慧推薦</Text>
        <Text style={[styles.subtitle, { fontSize: rs(13) }]}>基於健康條件與今日剩餘熱量，篩選更安全的餐點</Text>
      </View>

      {loading ? (
        <View style={[styles.emptyCard, { padding: rs(24) }]}> 
          <ActivityIndicator size="large" color={Palette.accent.cyan} />
          <Text style={[styles.emptyText, { fontSize: rs(13) }]}>讀取推薦中...</Text>
        </View>
      ) : error ? (
        <View style={[styles.emptyCard, { padding: rs(24) }]}> 
          <Ionicons name="cloud-offline-outline" size={rs(30)} color={Palette.status.warning} />
          <Text style={[styles.emptyText, { fontSize: rs(13) }]}>無法載入推薦資料：{error}</Text>
        </View>
      ) : (
        <>
          <View style={[styles.summaryCard, { padding: rs(16) }]}> 
            <View style={styles.summaryRow}>
              <View style={styles.summaryItem}>
                <Text style={[styles.summaryLabel, { fontSize: rs(10) }]}>剩餘熱量</Text>
                <Text style={[styles.summaryValue, { fontSize: rs(18), color: Palette.accent.green }]}>{remaining} kcal</Text>
              </View>
              <View style={styles.summaryDivider} />
              <View style={styles.summaryItem}>
                <Text style={[styles.summaryLabel, { fontSize: rs(10) }]}>健康狀況</Text>
                <View style={styles.conditionTags}>
                  {user.healthConditions.length > 0 ? user.healthConditions.map((c) => (
                    <View key={c} style={styles.conditionTag}>
                      <Text style={[styles.conditionTagText, { fontSize: rs(10) }]}>{c}</Text>
                    </View>
                  )) : (
                    <Text style={[styles.noCondText, { fontSize: rs(11) }]}>無設定</Text>
                  )}
                </View>
              </View>
            </View>
            <View style={styles.filterNotice}>
              <Ionicons name="shield-checkmark" size={rs(14)} color={Palette.accent.green} />
              <Text style={[styles.filterNoticeText, { fontSize: rs(11) }]}>已自動排除 {totalFiltered} 項不適合的餐點</Text>
            </View>
          </View>

          {sourceCounts ? (
            <View style={[styles.sourceCard, { padding: rs(12) }]}> 
              <Ionicons name="layers-outline" size={rs(14)} color={Palette.accent.cyan} />
              <Text style={[styles.sourceText, { fontSize: rs(11) }]}>推薦池：TFDA {sourceCounts.tfda} 筆、自訂食品 {sourceCounts.custom_foods} 筆、基礎資料 {sourceCounts.manual_db} 筆</Text>
            </View>
          ) : null}

          {preferenceProfile && preferenceProfile.food_count > 0 ? (
            <View style={[styles.sourceCard, { padding: rs(12), borderColor: 'rgba(244,114,182,0.22)' }]}> 
              <Ionicons name="heart-outline" size={rs(14)} color={Palette.accent.pink} />
              <Text style={[styles.sourceText, { fontSize: rs(11) }]}>已參考近期 {preferenceProfile.record_count} 筆紀錄、{preferenceProfile.food_count} 個食品與 {preferenceProfile.feedback_count || 0} 筆推薦回饋建立偏好分數</Text>
            </View>
          ) : null}

          <View style={[styles.filteredCard, { padding: rs(16) }]}> 
            <View style={styles.filteredHeader}>
              <Ionicons name="close-circle" size={rs(16)} color={Palette.status.error} />
              <Text style={[styles.filteredTitle, { fontSize: rs(13) }]}>安全過濾層已排除</Text>
            </View>
            {filteredOut.length === 0 ? (
              <Text style={[styles.filteredReason, { fontSize: rs(11) }]}>目前沒有額外被排除的餐點。</Text>
            ) : (
              filteredOut.slice(0, 6).map((item, i) => (
                <View key={`${item.label}_${i}`} style={[styles.filteredRow, i < Math.min(filteredOut.length, 6) - 1 && styles.filteredRowBordered]}>
                  <Text style={styles.filteredEmoji}>🚫</Text>
                  <View style={styles.filteredInfo}>
                    <Text style={[styles.filteredName, { fontSize: rs(14) }]}>{item.name_zh}</Text>
                    <Text style={[styles.filteredReason, { fontSize: rs(11) }]}>{formatReason(item)}</Text>
                  </View>
                </View>
              ))
            )}
            {totalFiltered > filteredOut.length ? (
              <Text style={[styles.filteredReason, { fontSize: rs(10), marginTop: rs(8) }]}>僅顯示前 {filteredOut.length} 筆排除範例，完整排除數已計入上方統計。</Text>
            ) : null}
          </View>

          <View style={styles.recHeader}>
            <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>為你推薦</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Ionicons name="sparkles" size={rs(12)} color={Palette.accent.pink} />
              <Text style={[styles.recSort, { fontSize: rs(10) }]}>依熱量契合與安全規則排序</Text>
            </View>
          </View>

          {recommended.length === 0 ? (
            <View style={[styles.emptyCard, { padding: rs(24) }]}> 
              <Ionicons name="restaurant-outline" size={rs(30)} color={Palette.text.tertiary} />
              <Text style={[styles.emptyText, { fontSize: rs(13) }]}>目前找不到符合條件的推薦，請先調整個人條件或新增更多食品資料。</Text>
            </View>
          ) : (
            recommended.map((meal, index) => (
              <View key={`${meal.label}_${index}`} style={[styles.mealCard, { padding: rs(16) }]}> 
                <View style={styles.mealTop}>
                  <View style={[styles.mealEmoji, { width: rs(40), height: rs(40), borderRadius: rs(12) }]}>
                    <Text style={{ fontSize: rs(18) }}>🍽️</Text>
                  </View>
                  <View style={styles.mealInfo}>
                    <Text style={[styles.mealName, { fontSize: rs(15) }]}>{meal.name_zh}</Text>
                    <View style={styles.mealMeta}>
                      <Ionicons name="shield-checkmark-outline" size={rs(10)} color={Palette.text.tertiary} />
                      <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>{meal.source === 'TFDA' ? 'TFDA 官方資料' : meal.source === 'manual-db' ? '基礎資料庫' : '自訂食品'}</Text>
                      {(meal.preference_score || 0) > 0 ? <Text style={[styles.mealMetaText, { fontSize: rs(10), color: Palette.accent.pink }]}>偏好 +{meal.preference_score}</Text> : null}
                      {(meal.feedback_adjustment || 0) !== 0 ? <Text style={[styles.mealMetaText, { fontSize: rs(10), color: (meal.feedback_adjustment || 0) > 0 ? Palette.accent.green : Palette.status.warning }]}>回饋 {meal.feedback_adjustment! > 0 ? '+' : ''}{meal.feedback_adjustment}</Text> : null}
                      {meal.gi ? <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>GI {meal.gi === 'low' ? '低' : meal.gi === 'medium' ? '中' : '高'}</Text> : null}
                    </View>
                  </View>
                  <View style={styles.scoreContainer}>
                    <Text style={[styles.scoreValue, { fontSize: rs(20), color: Palette.accent.pink }]}>{meal.match_score}</Text>
                    <Text style={[styles.scoreLabel, { fontSize: rs(9) }]}>契合</Text>
                  </View>
                </View>

                <View style={styles.badgesRow}>
                  {(meal.safety_badges || []).length > 0 ? (meal.safety_badges || []).map((badge) => (
                    <View key={badge} style={styles.safetyBadge}>
                      <Ionicons name="checkmark-circle" size={rs(10)} color={Palette.accent.green} />
                      <Text style={[styles.safetyBadgeText, { fontSize: rs(10) }]}>{badge}</Text>
                    </View>
                  )) : (
                    <View style={styles.safetyBadge}>
                      <Ionicons name="checkmark-circle" size={rs(10)} color={Palette.accent.green} />
                      <Text style={[styles.safetyBadgeText, { fontSize: rs(10) }]}>已通過安全篩選</Text>
                    </View>
                  )}
                </View>

                {(meal.preference_reasons || []).length > 0 ? (
                  <View style={styles.preferenceReasonWrap}>
                    {(meal.preference_reasons || []).map((reason) => (
                      <Text key={reason} style={[styles.preferenceReasonText, { fontSize: rs(10) }]}>因為 {reason}</Text>
                    ))}
                  </View>
                ) : null}

                <View style={styles.mealNutritionRow}>
                  {[
                    { label: '熱量', value: `${meal.calories} kcal`, color: Palette.accent.green },
                    { label: '蛋白質', value: `${meal.protein} g`, color: Palette.accent.blue },
                    { label: '碳水', value: `${meal.carbs} g`, color: Palette.accent.orange },
                    { label: '鈉', value: `${meal.sodium} mg`, color: Palette.accent.pink },
                  ].map((n) => (
                    <View key={n.label} style={styles.mealNutritionItem}>
                      <Text style={[styles.mealNutritionLabel, { fontSize: rs(9) }]}>{n.label}</Text>
                      <Text style={[styles.mealNutritionValue, { fontSize: rs(12), color: n.color }]}>{n.value}</Text>
                    </View>
                  ))}
                </View>

                <View style={styles.feedbackRow}>
                  {[
                    { action: 'accepted' as const, label: '採納', icon: 'checkmark-circle-outline' as const },
                    { action: 'skipped' as const, label: '略過', icon: 'play-skip-forward-outline' as const },
                    { action: 'disliked' as const, label: '不喜歡', icon: 'thumbs-down-outline' as const },
                  ].map((item) => {
                    const active = feedbackStatus[meal.label] === item.action;
                    const saving = feedbackSavingKey === meal.label;
                    return (
                      <Pressable
                        key={item.action}
                        disabled={saving}
                        onPress={() => handleRecommendationFeedback(meal, item.action)}
                        style={({ pressed }) => [
                          styles.feedbackButton,
                          active && styles.feedbackButtonActive,
                          (pressed || saving) && { opacity: 0.72 },
                        ]}
                      >
                        {saving && item.action === 'accepted' ? (
                          <ActivityIndicator size="small" color={Palette.accent.cyan} />
                        ) : (
                          <Ionicons name={item.icon} size={rs(12)} color={active ? Palette.accent.green : Palette.text.tertiary} />
                        )}
                        <Text style={[styles.feedbackButtonText, { fontSize: rs(10) }, active && styles.feedbackButtonTextActive]}>{item.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))
          )}

          <View style={[styles.summaryCard, { padding: rs(16) }]}> 
            <View style={styles.filteredHeader}>
              <Ionicons name="navigate" size={rs(16)} color={Palette.accent.cyan} />
              <Text style={[styles.filteredTitle, { fontSize: rs(13), color: Palette.accent.cyan }]}>附近餐廳地圖推薦</Text>
            </View>
            <Text style={[styles.filteredReason, { fontSize: rs(11), marginBottom: rs(12) }]}>輸入本餐預算與搜尋半徑後，會透過 Google Places 搜尋附近真實店家；Google 不提供可靠菜單營養，餐點營養請到店後用掃描或手動搜尋確認。</Text>
            <View style={styles.budgetRow}>
              <TextInput
                value={budget}
                onChangeText={setBudget}
                keyboardType="numeric"
                placeholder="預算"
                placeholderTextColor={Palette.text.tertiary}
                style={[styles.budgetInput, { fontSize: rs(13) }]}
              />
              <Pressable onPress={handleHealthyFoodSearch} style={styles.locateButton}>
                {healthyLoading ? (
                  <ActivityIndicator size="small" color={Palette.text.inverse} />
                ) : (
                  <Text style={[styles.locateButtonText, { fontSize: rs(12) }]}>更新地圖</Text>
                )}
              </Pressable>
            </View>
            <View style={styles.optionGroup}>
              <Text style={[styles.optionLabel, { fontSize: rs(10) }]}>搜尋半徑</Text>
              <View style={styles.optionRow}>
                {RADIUS_OPTIONS.map((option) => (
                  <Pressable
                    key={option}
                    onPress={() => setRadiusKm(option)}
                    style={[styles.optionChip, radiusKm === option && styles.optionChipActive]}
                  >
                    <Text style={[styles.optionChipText, { fontSize: rs(10) }, radiusKm === option && styles.optionChipTextActive]}>{option} km</Text>
                  </Pressable>
                ))}
              </View>
            </View>
            <View style={styles.optionGroup}>
              <Text style={[styles.optionLabel, { fontSize: rs(10) }]}>店家類型</Text>
              <View style={styles.optionRow}>
                {CATEGORY_OPTIONS.map((option) => (
                  <Pressable
                    key={option.value}
                    onPress={() => setCategory(option.value)}
                    style={[styles.optionChip, category === option.value && styles.optionChipActive]}
                  >
                    <Text style={[styles.optionChipText, { fontSize: rs(10) }, category === option.value && styles.optionChipTextActive]}>{option.label}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
            <Text style={[styles.filteredReason, { fontSize: rs(10), marginTop: 8 }]}>{locationLabel}</Text>
            {healthyError ? (
              <View style={styles.apiErrorBox}>
                <Text style={[styles.filteredReason, { fontSize: rs(10), color: Palette.status.warning }]}>{healthyError}</Text>
                <Text style={[styles.filteredReason, { fontSize: rs(9), marginTop: 4 }]}>API：{apiBaseUrl}</Text>
                <Text style={[styles.filteredReason, { fontSize: rs(9), marginTop: 2 }]}>登入狀態：{accessToken ? 'Bearer token 已載入' : '尚未載入 Bearer token'}</Text>
              </View>
            ) : null}
          </View>

          {mapRestaurants.length && mapLocation ? (
            <>
              <View style={styles.recHeader}>
                <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>地圖上的推薦店家</Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                  <Ionicons name="location" size={rs(12)} color={Palette.accent.cyan} />
                  <Text style={[styles.recSort, { fontSize: rs(10), color: Palette.accent.cyan }]}>Google Places 真實店家，依距離、評分與預算估計排序</Text>
                </View>
              </View>

              <View style={[styles.mapCard, { padding: rs(12) }]}>
                <FoodMap
                  location={mapLocation}
                  restaurants={mapRestaurants}
                  selectedRestaurantId={selectedRestaurant?.restaurant_id || null}
                  onSelectRestaurant={setSelectedRestaurantId}
                />
                {selectedRestaurant ? (
                  <View style={styles.selectedMapInfo}>
                    <View style={styles.selectedMapTitleRow}>
                      <Text style={[styles.mealName, { fontSize: rs(15) }]}>{selectedRestaurant.name}</Text>
                      <Text style={[styles.scorePill, { fontSize: rs(10) }]}>推薦 {selectedRestaurant.match_score}</Text>
                    </View>
                    <Text style={[styles.filteredReason, { fontSize: rs(10) }]}>{selectedRestaurant.address || '尚無地址'} · {selectedRestaurant.distance_km} km</Text>
                    <Pressable onPress={() => handleOpenNavigation(selectedRestaurant)} style={styles.navigationButton}>
                      <Ionicons name="navigate-circle-outline" size={rs(14)} color={Palette.text.inverse} />
                      <Text style={[styles.navigationButtonText, { fontSize: rs(11) }]}>開啟 Google Maps 導航</Text>
                    </Pressable>
                  </View>
                ) : null}
              </View>

              {mapRestaurants.map((restaurant, index) => (
                <View key={restaurant.restaurant_id} style={[styles.mealCard, selectedRestaurantId === restaurant.restaurant_id && styles.mealCardSelected, { padding: rs(16) }]}>
                  <View style={styles.mealTop}>
                    <View style={[styles.mealEmoji, { width: rs(40), height: rs(40), borderRadius: rs(12) }]}>
                      <Text style={{ fontSize: rs(18) }}>{index + 1}</Text>
                    </View>
                    <View style={styles.mealInfo}>
                      <Text style={[styles.mealName, { fontSize: rs(15) }]}>{restaurant.name}</Text>
                      <View style={styles.mealMeta}>
                        <Ionicons name="storefront-outline" size={rs(10)} color={Palette.text.tertiary} />
                        <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>{restaurant.tags.slice(0, 2).join('、')}</Text>
                        <Ionicons name="location-outline" size={rs(10)} color={Palette.text.tertiary} />
                        <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>{restaurant.distance_km} km</Text>
                        <Ionicons name="time-outline" size={rs(10)} color={Palette.text.tertiary} />
                        <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>{restaurant.is_open ? '營業中' : '未營業'}</Text>
                        {restaurant.rating ? <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>評分 {restaurant.rating}</Text> : null}
                      </View>
                    </View>
                    <View style={styles.scoreContainer}>
                      <Text style={[styles.scoreValue, { fontSize: rs(20), color: Palette.accent.cyan }]}>{restaurant.match_score}</Text>
                      <Text style={[styles.scoreLabel, { fontSize: rs(9) }]}>推薦</Text>
                    </View>
                  </View>

                  <View style={styles.badgesRow}>
                    {restaurant.tags.map((badge) => (
                      <View key={badge} style={styles.safetyBadge}>
                        <Ionicons name="leaf-outline" size={rs(10)} color={Palette.accent.green} />
                        <Text style={[styles.safetyBadgeText, { fontSize: rs(10) }]}>{badge}</Text>
                      </View>
                    ))}
                  </View>

                  {restaurant.recommended_items.slice(0, 2).map((item) => (
                    <View key={`${restaurant.restaurant_id}_${item.item_id || item.item_name}`} style={styles.recommendedItemBlock}>
                      <View style={styles.selectedMapTitleRow}>
                        <Text style={[styles.mealName, { fontSize: rs(13), flex: 1 }]}>{item.item_name}</Text>
                        <Text style={[styles.priceText, { fontSize: rs(12) }]}>{restaurant.price_level != null ? `$${restaurant.price_level}` : '價格待確認'}</Text>
                      </View>
                      {item.nutrition_available ? (
                        <View style={styles.mealNutritionRow}>
                          {[
                            { label: '熱量', value: `${item.calories} kcal`, color: Palette.accent.green },
                            { label: '蛋白質', value: `${item.protein} g`, color: Palette.accent.blue },
                            { label: '鈉', value: `${item.sodium} mg`, color: Palette.accent.pink },
                            { label: '分數', value: `${item.match_score}`, color: Palette.accent.orange },
                          ].map((n) => (
                            <View key={n.label} style={styles.mealNutritionItem}>
                              <Text style={[styles.mealNutritionLabel, { fontSize: rs(9) }]}>{n.label}</Text>
                              <Text style={[styles.mealNutritionValue, { fontSize: rs(12), color: n.color }]}>{n.value}</Text>
                            </View>
                          ))}
                        </View>
                      ) : (
                        <View style={styles.nutritionUnavailableBox}>
                          <Ionicons name="information-circle-outline" size={rs(13)} color={Palette.status.warning} />
                          <Text style={[styles.filteredReason, { fontSize: rs(10), flex: 1 }]}>Google Places 已提供真實店家位置；菜單價格與營養資料需到店後用掃描或手動搜尋確認。</Text>
                        </View>
                      )}
                      <View style={styles.reasonWrap}>
                        {item.reasons.map((reason) => (
                          <Text key={reason} style={[styles.filteredReason, { fontSize: rs(10) }]}>{reason}</Text>
                        ))}
                      </View>
                    </View>
                  ))}

                  <View style={styles.restaurantActionRow}>
                    <Pressable onPress={() => setSelectedRestaurantId(restaurant.restaurant_id)} style={styles.secondaryButton}>
                      <Ionicons name="map-outline" size={rs(13)} color={Palette.accent.cyan} />
                      <Text style={[styles.secondaryButtonText, { fontSize: rs(11) }]}>在地圖標示</Text>
                    </Pressable>
                    <Pressable onPress={() => handleOpenNavigation(restaurant)} style={styles.secondaryButton}>
                      <Ionicons name="navigate-outline" size={rs(13)} color={Palette.accent.green} />
                      <Text style={[styles.secondaryButtonText, { fontSize: rs(11), color: Palette.accent.green }]}>導航</Text>
                    </Pressable>
                  </View>
                </View>
              ))}
            </>
          ) : null}
        </>
      )}
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  header: { marginTop: Spacing.lg, marginBottom: Spacing.xl },
  title: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  subtitle: { ...Typography.body, color: Palette.text.tertiary, lineHeight: 22 },

  emptyCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    alignItems: 'center',
    gap: Spacing.md,
    ...Shadows.card,
  },
  emptyText: { ...Typography.body, color: Palette.text.tertiary, textAlign: 'center' },

  summaryCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  summaryRow: { flexDirection: 'row', marginBottom: Spacing.md },
  summaryItem: { flex: 1, alignItems: 'center' },
  summaryLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  summaryValue: { ...Typography.h2 },
  summaryDivider: { width: 1, backgroundColor: Palette.border.subtle },
  conditionTags: { flexDirection: 'row', gap: 4, flexWrap: 'wrap', justifyContent: 'center' },
  conditionTag: { backgroundColor: 'rgba(248,113,113,0.12)', paddingHorizontal: 8, paddingVertical: 2, borderRadius: Radius.sm },
  conditionTagText: { ...Typography.small, color: Palette.status.error },
  noCondText: { ...Typography.caption, color: Palette.text.tertiary },
  filterNotice: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, paddingTop: Spacing.md, borderTopWidth: 1, borderTopColor: Palette.border.subtle },
  filterNoticeText: { ...Typography.caption, color: Palette.accent.green },

  filteredCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle,
  },
  sourceCard: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.sm,
    backgroundColor: Palette.bg.card, borderRadius: Radius.lg,
    marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle,
  },
  sourceText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  filteredHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.md },
  filteredTitle: { ...Typography.bodyBold, color: Palette.status.error },
  filteredRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, paddingVertical: Spacing.md },
  filteredRowBordered: { borderBottomWidth: 1, borderBottomColor: Palette.border.subtle },
  filteredEmoji: { fontSize: 24 },
  filteredInfo: { flex: 1 },
  filteredName: { ...Typography.bodyBold, color: Palette.text.primary, marginBottom: 2 },
  filteredReason: { ...Typography.caption, color: Palette.text.tertiary },

  recHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: Spacing.lg },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  recSort: { ...Typography.small, color: Palette.accent.pink },

  mealCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.md,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  mealCardSelected: { borderColor: 'rgba(34,211,238,0.45)' },
  mealTop: { flexDirection: 'row', alignItems: 'center', marginBottom: Spacing.md },
  mealEmoji: { backgroundColor: Palette.bg.elevated, alignItems: 'center', justifyContent: 'center', marginRight: Spacing.md },
  mealInfo: { flex: 1 },
  mealName: { ...Typography.bodyBold, color: Palette.text.primary, marginBottom: 4 },
  mealMeta: { flexDirection: 'row', alignItems: 'center', gap: 4, flexWrap: 'wrap' },
  mealMetaText: { ...Typography.small, color: Palette.text.tertiary },
  scoreContainer: { alignItems: 'center' },
  scoreValue: { ...Typography.h2, fontWeight: '800' },
  scoreLabel: { ...Typography.small, color: Palette.text.tertiary },

  badgesRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, marginBottom: Spacing.md },
  safetyBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: Palette.accent.greenDim, paddingHorizontal: 8, paddingVertical: 3, borderRadius: Radius.full,
  },
  safetyBadgeText: { ...Typography.small, color: Palette.accent.green },
  preferenceReasonWrap: {
    backgroundColor: 'rgba(244,114,182,0.08)',
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    marginBottom: Spacing.md,
    gap: 2,
  },
  preferenceReasonText: { ...Typography.small, color: Palette.accent.pink },

  feedbackRow: { flexDirection: 'row', gap: Spacing.sm, marginTop: Spacing.md },
  feedbackButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.elevated,
    paddingVertical: Spacing.sm,
  },
  feedbackButtonActive: { borderColor: 'rgba(74,222,128,0.35)', backgroundColor: Palette.accent.greenDim },
  feedbackButtonText: { ...Typography.small, color: Palette.text.tertiary },
  feedbackButtonTextActive: { color: Palette.accent.green },

  mealNutritionRow: {
    flexDirection: 'row', backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, overflow: 'hidden',
  },
  mealNutritionItem: {
    flex: 1, alignItems: 'center', paddingVertical: Spacing.md,
    borderRightWidth: 1, borderRightColor: Palette.border.subtle,
  },
  mealNutritionLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  mealNutritionValue: { ...Typography.bodyBold },
  budgetRow: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'center' },
  budgetInput: {
    flex: 1,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
  },
  locateButton: {
    minWidth: 96,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.accent.cyan,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
  },
  locateButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
  reasonWrap: { marginTop: Spacing.md, gap: 4 },
  apiErrorBox: {
    marginTop: Spacing.sm,
    backgroundColor: 'rgba(251,191,36,0.08)',
    borderColor: 'rgba(251,191,36,0.2)',
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.sm,
  },
  optionGroup: { marginTop: Spacing.md, gap: Spacing.sm },
  optionLabel: { ...Typography.small, color: Palette.text.tertiary },
  optionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  optionChip: {
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  optionChipActive: { borderColor: 'rgba(34,211,238,0.45)', backgroundColor: Palette.accent.cyanDim },
  optionChipText: { ...Typography.small, color: Palette.text.tertiary },
  optionChipTextActive: { color: Palette.accent.cyan },
  mapCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.card,
  },
  selectedMapInfo: {
    marginTop: Spacing.md,
    gap: Spacing.sm,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    padding: Spacing.md,
  },
  selectedMapTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm },
  scorePill: {
    ...Typography.small,
    color: Palette.accent.green,
    backgroundColor: Palette.accent.greenDim,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
  },
  navigationButton: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: Palette.accent.cyan,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  navigationButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
  recommendedItemBlock: {
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    marginTop: Spacing.sm,
    gap: Spacing.sm,
  },
  nutritionUnavailableBox: {
    flexDirection: 'row',
    gap: Spacing.sm,
    alignItems: 'flex-start',
    backgroundColor: 'rgba(251,191,36,0.08)',
    borderColor: 'rgba(251,191,36,0.18)',
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.sm,
  },
  priceText: { ...Typography.bodyBold, color: Palette.accent.orange },
  restaurantActionRow: { flexDirection: 'row', gap: Spacing.sm, marginTop: Spacing.md },
  secondaryButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.elevated,
    paddingVertical: Spacing.sm,
  },
  secondaryButtonText: { ...Typography.small, color: Palette.accent.cyan },
});
