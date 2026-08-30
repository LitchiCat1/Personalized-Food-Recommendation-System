import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Link, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import CalorieRing from '@/components/dashboard/CalorieRing';
import NutrientBar from '@/components/dashboard/NutrientBar';
import MealCard from '@/components/dashboard/MealCard';
import HealthScoreCard from '@/components/dashboard/HealthScoreCard';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import MetricCard from '@/components/ui/metric-card';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import DietaryRecordManager from '@/components/dashboard/DietaryRecordManager';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { fetchMedicalMetadata, fetchRecords, type MedicalConditionRule } from '@/lib/api';
import { buildNutrientSensitivityMap, type TrackedNutrientKey } from '@/lib/nutrient-sensitivity';
import { useResponsive } from '@/hooks/useResponsive';

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 6) return '夜間紀錄';
  if (h < 12) return '早安';
  if (h < 14) return '午餐時段';
  if (h < 18) return '下午補給';
  return '晚餐檢查';
}

function getLocalDateString(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export default function DashboardScreen() {
  const { isDesktop } = useResponsive();
  const { dailyNutrition, todayMeals, healthAlerts, apiBaseUrl, accessToken, dietaryRecordsRevision, replaceDashboardFromRecords, user } = useStore();
  const [syncing, setSyncing] = useState(true);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [conditionRules, setConditionRules] = useState<MedicalConditionRule[]>([]);
  const [recordManagerVisible, setRecordManagerVisible] = useState(false);
  const { calories, protein, carbs, sugar, fat, saturated_fat, trans_fat, sodium, fiber, calcium, iron } = dailyNutrition;
  const remaining = Math.max(0, Math.round(calories.target - calories.current));
  const sodiumRisk = sodium.current >= sodium.target ? '超標' : sodium.current >= sodium.target * 0.8 ? '接近上限' : '正常';
  const nutrientSensitivities = useMemo(
    () => buildNutrientSensitivityMap(user.healthConditions, conditionRules),
    [conditionRules, user.healthConditions]
  );
  const sensitiveConditions = useMemo(
    () => Array.from(new Set(Object.values(nutrientSensitivities).flat())),
    [nutrientSensitivities]
  );
  const hasFriedFood = todayMeals.some((meal) => meal.is_fried === true);

  const getAttentionLabel = (nutrient: TrackedNutrientKey) => {
    const conditions = nutrientSensitivities[nutrient];
    return conditions.length ? `${conditions.join('、')}需留意` : undefined;
  };

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      const requestRevision = dietaryRecordsRevision;
      setSyncing(true);
      setSyncError(null);

      fetchRecords(apiBaseUrl, user.userId, getLocalDateString(), { accessToken })
        .then((data) => {
          if (cancelled || requestRevision !== useStore.getState().dietaryRecordsRevision) return;
          replaceDashboardFromRecords(data.records || []);
        })
        .catch((err: Error) => {
          if (!cancelled) setSyncError(err.message);
        })
        .finally(() => {
          if (!cancelled) setSyncing(false);
        });

      return () => {
        cancelled = true;
      };
    }, [accessToken, apiBaseUrl, dietaryRecordsRevision, replaceDashboardFromRecords, user.userId])
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

  const alertContent = healthAlerts.length > 0 ? (
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
  ) : (
    <View style={styles.safeBanner}>
      <Ionicons name="shield-checkmark-outline" size={18} color={Palette.accent.green} />
      <Text style={styles.safeBannerText}>目前沒有需要優先處理的飲食警示</Text>
    </View>
  );

  const mealsContent = (
    <View>
      <View style={styles.mealsHeader}>
        <View>
          <Text style={styles.sectionTitle}>今日餐點</Text>
          <Text style={styles.sectionSubtitle}>依時間排列，快速回看已吃內容</Text>
        </View>
        <DataPill tone="info">{todayMeals.length} 筆</DataPill>
      </View>
      {todayMeals.map((meal) => <MealCard key={meal.id} meal={meal} />)}
      {!syncing && !syncError && todayMeals.length === 0 ? (
        <View style={styles.emptyMealsCard}>
          <Ionicons name="restaurant-outline" size={26} color={Palette.text.tertiary} />
          <Text style={styles.emptyMealsTitle}>今天尚未新增餐點</Text>
          <Text style={styles.emptyMealsText}>拍照辨識或手動搜尋後，餐點會同步顯示在這裡。</Text>
          <Link href="/scanner" asChild>
            <PrimaryButton label="新增第一筆餐點" icon={<Ionicons name="add-circle-outline" size={18} color={Palette.text.inverse} />} />
          </Link>
        </View>
      ) : null}
    </View>
  );

  const nutritionContent = (
    <SectionBlock title="營養素進度" subtitle="依每日目標檢查下一餐需要補足或控制的項目。">
      {sensitiveConditions.length ? (
        <View style={styles.sensitivityNotice}>
          <Ionicons name="alert-circle-outline" size={18} color={Palette.status.warning} />
          <View style={styles.sensitivityCopy}>
            <Text style={styles.sensitivityTitle}>病症敏感營養素已標示</Text>
            <Text style={styles.sensitivityText}>{sensitiveConditions.join('、')}相關提醒；每日目標值維持原設定。</Text>
          </View>
        </View>
      ) : null}
      <View style={styles.nutrientStack}>
        <NutrientBar label={protein.label} current={protein.current} target={protein.target} unit={protein.unit} color={protein.color} attentionLabel={getAttentionLabel('protein')} />
        <NutrientBar label={carbs.label} current={carbs.current} target={carbs.target} unit={carbs.unit} color={carbs.color} attentionLabel={getAttentionLabel('carbs')} />
        <NutrientBar label={sugar.label} current={sugar.current} target={sugar.target} unit={sugar.unit} color={sugar.color} attentionLabel={getAttentionLabel('sugar')} />
        <NutrientBar label={fat.label} current={fat.current} target={fat.target} unit={fat.unit} color={fat.color} attentionLabel={getAttentionLabel('fat')} />
        <NutrientBar label={saturated_fat.label} current={saturated_fat.current} target={saturated_fat.target} unit={saturated_fat.unit} color={saturated_fat.color} attentionLabel={getAttentionLabel('saturated_fat')} />
        <NutrientBar label={trans_fat.label} current={trans_fat.current} target={trans_fat.target} unit={trans_fat.unit} color={trans_fat.color} attentionLabel={getAttentionLabel('trans_fat')} />
        <NutrientBar label={sodium.label} current={sodium.current} target={sodium.target} unit={sodium.unit} color={sodium.current >= sodium.target * 0.8 ? Palette.status.warning : sodium.color} attentionLabel={getAttentionLabel('sodium')} />
        <NutrientBar label={fiber.label} current={fiber.current} target={fiber.target} unit={fiber.unit} color={fiber.color} attentionLabel={getAttentionLabel('fiber')} />
        <NutrientBar label={calcium.label} current={calcium.current} target={calcium.target} unit={calcium.unit} color={calcium.color} attentionLabel={getAttentionLabel('calcium')} />
        <NutrientBar label={iron.label} current={iron.current} target={iron.target} unit={iron.unit} color={iron.color} attentionLabel={getAttentionLabel('iron')} />
      </View>
    </SectionBlock>
  );

  return (
    <AppContainer>
      <ScreenHeader
        title="今日營養狀態"
        subtitle={`${getGreeting()}，先確認熱量、鈉與蛋白質是否在安全範圍。`}
        badge={new Date().toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', weekday: 'short' })}
        badgeTone="success"
      />

      <View style={[styles.syncBanner, syncError && styles.syncBannerWarning]}>
        {syncing ? <ActivityIndicator size="small" color={Palette.accent.green} /> : <Ionicons name={syncError ? 'cloud-offline-outline' : 'cloud-done-outline'} size={16} color={syncError ? Palette.status.warning : Palette.accent.green} />}
        <Text style={[styles.syncText, syncError && styles.syncWarningText]} selectable>
          {syncing
            ? '正在同步今日後端飲食紀錄'
            : syncError
              ? `使用本機暫存資料：${syncError}`
              : `已同步今日 ${todayMeals.length} 筆後端紀錄`}
        </Text>
      </View>

      <View style={styles.heroCard}>
        <View style={styles.heroTop}>
          <View style={styles.heroCopy}>
            <DataPill tone={sodiumRisk === '正常' ? 'success' : 'warning'}>鈉風險：{sodiumRisk}</DataPill>
            <Text style={styles.heroTitle}>今天還能吃 {remaining.toLocaleString()} kcal</Text>
            <Text style={styles.heroSubtitle}>目標 {calories.target.toLocaleString()} kcal，目前已紀錄 {todayMeals.length} 筆餐點。</Text>
          </View>
          <CalorieRing current={Math.round(calories.current)} target={calories.target} />
        </View>
        <View style={styles.heroActions}>
          <Link href="/scanner" asChild>
            <PrimaryButton label="掃描下一餐" icon={<Ionicons name="scan-outline" size={18} color={Palette.text.inverse} />} />
          </Link>
          <PrimaryButton
            tone="ghost"
            label="修改飲食紀錄"
            onPress={() => setRecordManagerVisible(true)}
            icon={<Ionicons name="create-outline" size={18} color={Palette.accent.green} />}
          />
        </View>
      </View>

      <HealthScoreCard
        calories={calories}
        protein={protein}
        carbs={carbs}
        sugar={sugar}
        fat={fat}
        saturated_fat={saturated_fat}
        trans_fat={trans_fat}
        sodium={sodium}
        fiber={fiber}
        calcium={calcium}
        iron={iron}
        hasMeals={todayMeals.length > 0}
        hasFriedFood={hasFriedFood}
      />

      {isDesktop ? (
        <>
          <View style={styles.metricGrid}>
            <MetricCard label="剩餘熱量" value={remaining} unit="kcal" accent={Palette.accent.green} />
            <MetricCard label="已攝取" value={Math.round(calories.current)} unit="kcal" accent={Palette.accent.blue} />
            <MetricCard label="鈉攝取" value={Math.round(sodium.current)} unit="mg" accent={sodiumRisk === '正常' ? Palette.accent.green : Palette.status.warning} />
          </View>
          <View style={styles.desktopColumns}>
            <View style={styles.desktopMain}>{alertContent}{mealsContent}</View>
            <View style={styles.desktopAside}>{nutritionContent}</View>
          </View>
        </>
      ) : (
        <>{alertContent}{mealsContent}{nutritionContent}</>
      )}

      <DietaryRecordManager visible={recordManagerVisible} onClose={() => setRecordManagerVisible(false)} />
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  syncBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  syncBannerWarning: { borderColor: 'rgba(245,158,11,0.24)', backgroundColor: Palette.accent.orangeDim },
  syncText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  syncWarningText: { color: Palette.status.warning },
  heroCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.xl,
    marginBottom: Spacing.xl,
    gap: Spacing.xl,
    ...Shadows.card,
  },
  heroTop: { flexDirection: 'row', gap: Spacing.lg, alignItems: 'center' },
  heroCopy: { flex: 1, gap: Spacing.sm },
  heroTitle: { ...Typography.h1, color: Palette.text.primary },
  heroSubtitle: { ...Typography.caption, color: Palette.text.secondary },
  heroActions: { gap: Spacing.sm },
  alertStack: { gap: Spacing.sm, marginBottom: Spacing.xl },
  safeBanner: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, backgroundColor: Palette.accent.greenDim, borderRadius: Radius.lg, padding: Spacing.md, marginBottom: Spacing.xl },
  safeBannerText: { ...Typography.caption, color: Palette.accent.green, flex: 1 },
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
  metricGrid: { flexDirection: 'row', gap: Spacing.sm, marginBottom: Spacing.xl },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xl },
  desktopMain: { flex: 1.45, minWidth: 0 },
  desktopAside: { flex: 1, minWidth: 0 },
  sensitivityNotice: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm, backgroundColor: Palette.accent.orangeDim, padding: Spacing.md, marginBottom: Spacing.lg, borderLeftWidth: 3, borderLeftColor: Palette.status.warning },
  sensitivityCopy: { flex: 1, gap: 2 },
  sensitivityTitle: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  sensitivityText: { ...Typography.small, color: Palette.text.secondary },
  nutrientStack: { gap: Spacing.lg },
  mealsHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  sectionSubtitle: { ...Typography.caption, color: Palette.text.tertiary, marginTop: 2 },
  emptyMealsCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    padding: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    marginBottom: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.sm,
    ...Shadows.soft,
  },
  emptyMealsTitle: { ...Typography.bodyBold, color: Palette.text.primary },
  emptyMealsText: { ...Typography.caption, color: Palette.text.tertiary, textAlign: 'center' },
});
