import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TextInput, Pressable, Linking } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import MetricCard from '@/components/ui/metric-card';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import SegmentedControl from '@/components/ui/segmented-control';
import FoodMap from '@/components/maps/FoodMap';
import {
  fetchHealthyFoodRecommendations,
  fetchRestaurantAiSummary,
  fetchRecommendations,
  saveRecommendationFeedback,
  type HealthyFoodRestaurant,
  type RestaurantAiSummary,
  type RecommendationFeedbackAction,
  type HealthyFoodResponse,
  type RecommendationItem,
  type RecommendationResponse,
} from '@/lib/api';

function formatReason(item: RecommendationItem) {
  if (!item.reasons || item.reasons.length === 0) return '已由安全規則排除';
  return item.reasons.join('、');
}

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
  const filteredOut = data?.filtered_out || [];
  const totalFiltered = data?.total_filtered ?? filteredOut.length;
  const sourceCounts = data?.source_counts;
  const preferenceProfile = data?.preference_profile;
  const remaining = data?.remaining_calories ?? user.dailyCalorieTarget;
  const mapRestaurants = healthyData?.restaurants || [];
  const mapLocation = healthyData?.location || null;
  const selectedRestaurant = mapRestaurants.find((restaurant) => restaurant.restaurant_id === selectedRestaurantId) || mapRestaurants[0] || null;

  const handleHealthyFoodSearch = async () => {
    setHealthyLoading(true);
    setHealthyError(null);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) throw new Error('未授權定位權限');
      const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      setLocationLabel(`目前定位：${lat.toFixed(4)}, ${lng.toFixed(4)}`);
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
        subtitle="先看通過安全規則的餐點，再用定位找附近可行店家。"
        badge="安全過濾"
        badgeTone="success"
      />

      {loading ? (
        <StateCard icon="sparkles-outline" text="讀取推薦中..." loading />
      ) : error ? (
        <StateCard icon="cloud-offline-outline" text={`無法載入推薦資料：${error}`} tone="warning" />
      ) : (
        <>
          <View style={styles.metricRow}>
            <MetricCard label="剩餘熱量" value={remaining} unit="kcal" accent={Palette.accent.green} />
            <MetricCard label="已排除" value={totalFiltered} unit="項" accent={Palette.status.warning} />
            <MetricCard label="可推薦" value={recommended.length} unit="項" accent={Palette.accent.blue} />
          </View>

          <SectionBlock title="安全餐點推薦" subtitle="依熱量契合、疾病禁忌、過敏原和近期偏好排序。">
            <View style={styles.sourceSummary}>
              {sourceCounts ? <DataPill tone="info">TFDA {sourceCounts.tfda} · 自訂 {sourceCounts.custom_foods} · 基礎 {sourceCounts.manual_db}</DataPill> : null}
              {preferenceProfile && preferenceProfile.food_count > 0 ? <DataPill tone="success">參考 {preferenceProfile.record_count} 筆紀錄</DataPill> : null}
              <DataPill tone={user.healthConditions.length ? 'warning' : 'success'}>{user.healthConditions.length ? user.healthConditions.join('、') : '未設定疾病'}</DataPill>
            </View>

            <View style={styles.filteredSummary}>
              <Ionicons name="shield-checkmark-outline" size={18} color={Palette.accent.green} />
              <Text style={styles.filteredSummaryText}>安全過濾層已排除 {totalFiltered} 項不適合的餐點。</Text>
            </View>
            {filteredOut.slice(0, 3).map((item, i) => (
              <View key={`${item.label}_${i}`} style={styles.filteredExample}>
                <Text style={styles.filteredName}>{item.name_zh}</Text>
                <Text style={styles.filteredReason}>{formatReason(item)}</Text>
              </View>
            ))}

            <View style={styles.recommendList}>
              {recommended.length === 0 ? (
                <Text style={styles.emptyText}>目前找不到符合條件的推薦，請先調整個人條件或新增更多食品資料。</Text>
              ) : (
                recommended.map((meal, index) => (
                  <RecommendationCard
                    key={`${meal.label}_${index}`}
                    meal={meal}
                    feedbackStatus={feedbackStatus[meal.label]}
                    saving={feedbackSavingKey === meal.label}
                    onFeedback={(action) => handleRecommendationFeedback(meal, action)}
                  />
                ))
              )}
            </View>
          </SectionBlock>

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
                <Pressable key={option.value} onPress={() => setCategory(option.value)} style={[styles.categoryChip, category === option.value && styles.categoryChipActive]}>
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
                />
              ))}
            </>
          ) : null}
        </>
      )}
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
            <Pressable key={item.action} disabled={saving} onPress={() => onFeedback(item.action)} style={[styles.feedbackButton, active && styles.feedbackButtonActive]}>
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
}: {
  restaurant: HealthyFoodRestaurant;
  index: number;
  selected: boolean;
  summary?: RestaurantAiSummary;
  summaryLoading: boolean;
  onSelect: () => void;
  onSummary: () => void;
  onNavigate: () => void;
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
        <SecondaryButton label="地圖標示" onPress={onSelect} />
        <SecondaryButton label={summaryLoading ? '產生中' : 'AI 摘要'} onPress={onSummary} />
        <SecondaryButton label="導航" onPress={onNavigate} />
      </View>
      {summary ? (
        <View style={styles.aiSummaryBox}>
          <Text style={styles.itemName}>AI 推測：{summary.restaurant_type}</Text>
          <Text style={styles.restaurantMeta}>可能販售：{summary.likely_foods.join('、') || '不確定'}</Text>
          <Text style={styles.restaurantMeta}>價格：約 {summary.price_range_twd.min}-{summary.price_range_twd.max} 元 · 預算：{summary.budget_fit}</Text>
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
  filteredSummary: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.mint,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    marginBottom: Spacing.md,
  },
  filteredSummaryText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  filteredExample: { borderTopWidth: 1, borderTopColor: Palette.border.subtle, paddingVertical: Spacing.sm },
  filteredName: { ...Typography.caption, color: Palette.text.primary },
  filteredReason: { ...Typography.small, color: Palette.text.tertiary },
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
    minHeight: 40,
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
    minHeight: 38,
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
  restaurantActions: { flexDirection: 'row', gap: Spacing.sm },
  aiSummaryBox: {
    gap: Spacing.sm,
    backgroundColor: Palette.accent.blueDim,
    borderColor: 'rgba(47,128,237,0.18)',
    borderWidth: 1,
    borderRadius: Radius.lg,
    padding: Spacing.md,
  },
});
