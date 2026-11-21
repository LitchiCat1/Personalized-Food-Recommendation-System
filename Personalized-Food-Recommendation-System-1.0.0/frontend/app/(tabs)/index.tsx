import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Link, useFocusEffect } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import CalorieRing from '@/components/dashboard/CalorieRing';
import NutrientBar from '@/components/dashboard/NutrientBar';
import MealCard from '@/components/dashboard/MealCard';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import DietaryRecordManager from '@/components/dashboard/DietaryRecordManager';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';
import { formatCalories } from '@/lib/calorie-target';
import { useStore } from '@/store/useStore';
import { DEFAULT_NUTRITION_GOAL_TYPES, fetchMedicalMetadata, fetchRecords, type MedicalConditionRule } from '@/lib/api';
import { buildNutrientSensitivityMap, type TrackedNutrientKey } from '@/lib/nutrient-sensitivity';
import { useResponsive } from '@/hooks/useResponsive';

function getLocalDateString(now: Date): string {
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export default function DashboardScreen() {
  const { isDesktop } = useResponsive();
  const { dailyNutrition, todayMeals, healthAlerts, apiBaseUrl, accessToken, dietaryRecordsRevision, replaceDashboardFromRecords, nutritionGoalTypes, nutritionTargetBasis, user, dashboardReady: storeReady } = useStore();
  const [today, setToday] = useState(() => getLocalDateString(new Date()));
  const scope = JSON.stringify([apiBaseUrl, user.userId, today]);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [syncState, setSyncState] = useState<{ scope: string; attempt: number; status: 'loading' | 'ready' | 'error' } | null>(null);
  const [reload, setReload] = useState(0);
  const dashboardReady = storeReady && loadedScope === scope;
  const syncStatus = syncState?.scope === scope && syncState.attempt === reload ? syncState.status : 'loading';
  const syncing = syncStatus === 'loading';
  const syncError = syncStatus === 'error';
  const [conditionRules, setConditionRules] = useState<MedicalConditionRule[]>([]);
  const [recordManagerVisible, setRecordManagerVisible] = useState(false);
  const { calories, protein, carbs, sugar, fat, saturated_fat, trans_fat, sodium, fiber } = dailyNutrition;
  const calorieBalance = calories.target - calories.current;
  const sodiumRisk = sodium.current > sodium.target
    ? '已超過每日上限'
    : sodium.target > 0 && sodium.current >= sodium.target * 0.8 ? '接近上限' : '正常';

  const nutrientSensitivities = useMemo(
    () => buildNutrientSensitivityMap(user.healthConditions, conditionRules),
    [conditionRules, user.healthConditions]
  );
  const sensitiveConditions = useMemo(
    () => Array.from(new Set(Object.values(nutrientSensitivities).flat())),
    [nutrientSensitivities]
  );

  const getAttentionLabel = (nutrient: TrackedNutrientKey) => {
    const conditions = nutrientSensitivities[nutrient];
    return conditions.length ? `${conditions.join('、')}需留意` : undefined;
  };

  // 目標方向由後端依疾病決定（腎臟病的蛋白質是上限，不是下限）。
  // 之前只有鈉在這裡自己判斷要不要變色，其他營養素超標時進度條滿了
  // 但顏色不變，使用者看不出來。
  const goalTypeOf = (nutrient: keyof typeof DEFAULT_NUTRITION_GOAL_TYPES) =>
    nutritionGoalTypes[nutrient] ?? DEFAULT_NUTRITION_GOAL_TYPES[nutrient];

  useFocusEffect(
    useCallback(() => {
      const refreshDate = () => setToday(getLocalDateString(new Date()));
      refreshDate();
      if (getLocalDateString(new Date()) !== today) return;
      const timer = setInterval(refreshDate, 30_000);
      let cancelled = false;
      const requestRevision = dietaryRecordsRevision;
      setSyncState({ scope, attempt: reload, status: 'loading' });

      fetchRecords(apiBaseUrl, user.userId, today, { accessToken })
        .then((data) => {
          const latest = useStore.getState();
          if (cancelled || requestRevision !== latest.dietaryRecordsRevision || latest.user.userId !== user.userId || latest.apiBaseUrl !== apiBaseUrl || latest.accessToken !== accessToken) return;
          if (getLocalDateString(new Date()) !== today) {
            refreshDate();
            return;
          }
          replaceDashboardFromRecords(data.records || [], data.nutrition_targets, data.nutrition_goal_types, data.nutrition_target_basis, data.meal_nutrient_limits);
          setLoadedScope(scope);
          setSyncState({ scope, attempt: reload, status: 'ready' });
        })
        .catch(() => {
          if (!cancelled) setSyncState({ scope, attempt: reload, status: 'error' });
        });

      return () => {
        cancelled = true;
        clearInterval(timer);
      };
    }, [accessToken, apiBaseUrl, dietaryRecordsRevision, reload, replaceDashboardFromRecords, scope, today, user.userId])
  );

  useEffect(() => {
    let cancelled = false;

    fetchMedicalMetadata(apiBaseUrl)
      .then((metadata) => {
        if (!cancelled) setConditionRules(metadata.disease_rules.conditions || []);
      })
      .catch(() => {
        if (!cancelled) setConditionRules([]);
      });

    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  const alertContent = dashboardReady && healthAlerts.length > 0 ? (
    <View style={styles.alertStack}>
      {healthAlerts.map((alert) => (
        <View key={alert.id} style={[styles.alertCard, alert.type === 'danger' && styles.alertDanger, alert.type === 'warning' && styles.alertWarning]}>
          <Ionicons name={alert.type === 'danger' ? 'alert-circle-outline' : alert.type === 'warning' ? 'warning-outline' : 'information-circle-outline'} size={18} color={alert.type === 'danger' ? Palette.status.error : alert.type === 'warning' ? Palette.status.warning : Palette.accent.blue} />
          <View style={styles.alertContent}>
            <Text style={styles.alertTitle}>{alert.title}</Text>
            <Text style={styles.alertMessage}>{alert.message}</Text>
          </View>
        </View>
      ))}
    </View>
  ) : null;

  const mealsContent = (
    <View>
      <View style={styles.mealsHeader}>
        <View style={styles.mealsHeading}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>今日餐點</Text>
          {dashboardReady ? <DataPill tone="info">{todayMeals.length} 筆</DataPill> : null}
        </View>
        <SecondaryButton label="查看／修改紀錄" onPress={() => setRecordManagerVisible(true)} />
      </View>
      {dashboardReady ? todayMeals.map((meal) => <MealCard key={meal.id} meal={meal} sodiumDailyTarget={nutritionTargetBasis?.default_sodium_target ?? sodium.target} />) : null}
      {dashboardReady && !syncing && !syncError && todayMeals.length === 0 ? (
        <View style={styles.emptyMealsCard}>
          <Ionicons name="restaurant-outline" size={26} color={Palette.text.tertiary} />
          <Text style={styles.emptyMealsTitle}>今天尚未新增餐點</Text>
        </View>
      ) : null}
    </View>
  );

  const nutritionContent = (
    <SectionBlock title="其他營養素">
      {dashboardReady && sensitiveConditions.length ? (
        <View style={styles.sensitivityNotice}>
          <Ionicons name="alert-circle-outline" size={18} color={Palette.status.warning} />
          <View style={styles.sensitivityCopy}>
            <Text style={styles.sensitivityTitle}>病症敏感營養素已標示</Text>
            <Text style={styles.sensitivityText}>{sensitiveConditions.join('、')}相關提醒；每日目標值已依疾病調整。</Text>
          </View>
        </View>
      ) : null}
      {!dashboardReady ? (
        <Text style={styles.syncText}>{syncError ? '今日營養進度暫不可用' : '—'}</Text>
      ) : (
      <View style={styles.nutrientStack}>
        <NutrientBar label={protein.label} current={protein.current} target={protein.target} unit={protein.unit} color={protein.color} goalType={goalTypeOf('protein')} attentionLabel={getAttentionLabel('protein')} />
        <NutrientBar label={carbs.label} current={carbs.current} target={carbs.target} unit={carbs.unit} color={carbs.color} goalType={goalTypeOf('carbs')} attentionLabel={getAttentionLabel('carbs')} />
        <NutrientBar label={sugar.label} current={sugar.current} target={sugar.target} unit={sugar.unit} color={sugar.color} goalType={goalTypeOf('sugar')} attentionLabel={getAttentionLabel('sugar')} />
        <NutrientBar label={fat.label} current={fat.current} target={fat.target} unit={fat.unit} color={fat.color} goalType={goalTypeOf('fat')} attentionLabel={getAttentionLabel('fat')} />
        <NutrientBar label={saturated_fat.label} current={saturated_fat.current} target={saturated_fat.target} unit={saturated_fat.unit} color={saturated_fat.color} goalType={goalTypeOf('saturated_fat')} attentionLabel={getAttentionLabel('saturated_fat')} />
        <NutrientBar label={trans_fat.label} current={trans_fat.current} target={trans_fat.target} unit={trans_fat.unit} color={trans_fat.color} goalType={goalTypeOf('trans_fat')} attentionLabel={getAttentionLabel('trans_fat')} />
        <NutrientBar label={fiber.label} current={fiber.current} target={fiber.target} unit={fiber.unit} color={fiber.color} goalType={goalTypeOf('fiber')} attentionLabel={getAttentionLabel('fiber')} />
      </View>
      )}
    </SectionBlock>
  );

  return (
    <AppContainer>
      <ScreenHeader
        title="今日營養狀態"
        badge={new Date().toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', weekday: 'short' })}
        badgeTone="success"
      />

      {syncing || syncError ? (
        <View style={[styles.syncBanner, syncError && styles.syncBannerWarning]}>
          <View style={styles.syncLine}>
            {syncing ? <ActivityIndicator size="small" color={Palette.accent.green} /> : <Ionicons name="cloud-offline-outline" size={18} color={Palette.status.warning} />}
            <Text style={styles.syncText} accessibilityLiveRegion="polite">
              {syncing ? '正在讀取今日紀錄' : dashboardReady ? '同步失敗，顯示上次讀取的今日資料' : '無法讀取今日紀錄'}
            </Text>
          </View>
          {syncError ? <SecondaryButton label="重試" onPress={() => setReload((value) => value + 1)} /> : null}
        </View>
      ) : null}

      <View style={styles.heroCard}>
        <View style={styles.heroTop}>
          <CalorieRing current={dashboardReady ? calories.current : null} target={dashboardReady ? calories.target : null} />
          <View style={styles.heroCopy}>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>{dashboardReady && calorieBalance < 0 ? '熱量超出目標' : '剩餘熱量'}</Text>
              <Text style={styles.summaryValue}>{dashboardReady ? `${formatCalories(Math.abs(calorieBalance))} kcal` : '—'}</Text>
            </View>
            <View style={[styles.summaryRow, styles.sodiumRow]}>
              <Text style={styles.summaryLabel}>鈉攝取／每日上限</Text>
              <Text style={styles.summaryValue}>{dashboardReady ? `${sodium.current.toLocaleString('zh-TW')} / ${sodium.target.toLocaleString('zh-TW')} mg` : '—'}</Text>
              {dashboardReady && sodiumRisk !== '正常' ? <DataPill tone="warning">{sodiumRisk}</DataPill> : null}
              {dashboardReady && getAttentionLabel('sodium') ? <Text style={styles.syncText}>{getAttentionLabel('sodium')}</Text> : null}
            </View>
          </View>
        </View>
        <View style={isDesktop ? styles.desktopAction : null}>
          <Link href="/scanner" asChild>
            <PrimaryButton label="拍照辨識" icon={<Ionicons name="scan-outline" size={18} color={Palette.text.inverse} />} />
          </Link>
        </View>
      </View>

      {alertContent}

      {isDesktop ? (
          <View style={styles.desktopColumns}>
            <View style={styles.desktopAside}>{nutritionContent}</View>
            <View style={styles.desktopMain}>{mealsContent}</View>
          </View>
      ) : (
        <>{nutritionContent}{mealsContent}</>
      )}

      <DietaryRecordManager visible={recordManagerVisible} onClose={() => setRecordManagerVisible(false)} />
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  syncBanner: {
    gap: Spacing.sm,
    marginBottom: Spacing.md,
  },
  syncLine: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  syncBannerWarning: { borderLeftWidth: 3, borderLeftColor: Palette.status.warning, padding: Spacing.md, backgroundColor: Palette.accent.orangeDim },
  syncText: { ...Typography.caption, color: Palette.text.secondary, flexShrink: 1 },
  heroCard: {
    borderBottomWidth: 1,
    borderBottomColor: Palette.border.subtle,
    paddingBottom: Spacing['2xl'],
    marginBottom: Spacing.xl,
    gap: Spacing.xl,
  },
  heroTop: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.lg, alignItems: 'center' },
  heroCopy: { flexGrow: 1, flexBasis: 138, minWidth: 0, gap: Spacing.md },
  summaryRow: { gap: Spacing.xs, alignItems: 'flex-start' },
  sodiumRow: { borderTopWidth: 1, borderTopColor: Palette.border.subtle, paddingTop: Spacing.md },
  summaryLabel: { ...Typography.caption, color: Palette.text.secondary },
  summaryValue: { ...Typography.h2, ...Typography.number, color: Palette.text.primary },
  desktopAction: { alignSelf: 'flex-start', minWidth: 180 },
  alertStack: { gap: Spacing.sm, marginBottom: Spacing.xl },
  alertCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  alertDanger: { backgroundColor: 'rgba(226,85,85,0.08)', borderColor: 'rgba(226,85,85,0.18)' },
  alertWarning: { backgroundColor: Palette.accent.orangeDim, borderColor: 'rgba(245,158,11,0.18)' },
  alertContent: { flex: 1 },
  alertTitle: { ...Typography.bodyBold, color: Palette.text.primary },
  alertMessage: { ...Typography.caption, color: Palette.text.secondary },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xl },
  desktopMain: { flex: 1.45, minWidth: 0 },
  desktopAside: { flex: 1, minWidth: 0 },
  sensitivityNotice: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm, backgroundColor: Palette.accent.orangeDim, padding: Spacing.md, marginBottom: Spacing.lg, borderLeftWidth: 3, borderLeftColor: Palette.status.warning },
  sensitivityCopy: { flex: 1, gap: 2 },
  sensitivityTitle: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  sensitivityText: { ...Typography.small, color: Palette.text.secondary },
  nutrientStack: { gap: Spacing.lg },
  mealsHeader: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg },
  mealsHeading: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: Spacing.sm },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  emptyMealsCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    padding: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    marginBottom: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.sm,
  },
  emptyMealsTitle: { ...Typography.bodyBold, color: Palette.text.primary },
});
