import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Link } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import CalorieRing from '@/components/dashboard/CalorieRing';
import NutrientBar from '@/components/dashboard/NutrientBar';
import MealCard from '@/components/dashboard/MealCard';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import MetricCard from '@/components/ui/metric-card';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { fetchRecords } from '@/lib/api';

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
  const { dailyNutrition, todayMeals, healthAlerts, user, apiBaseUrl, accessToken, replaceDashboardFromRecords } = useStore();
  const [syncing, setSyncing] = useState(true);
  const [syncError, setSyncError] = useState<string | null>(null);
  const { calories, protein, carbs, fat, sodium, fiber } = dailyNutrition;
  const remaining = Math.max(0, Math.round(calories.target - calories.current));
  const sodiumRisk = sodium.current >= sodium.target ? '超標' : sodium.current >= sodium.target * 0.8 ? '接近上限' : '正常';

  useEffect(() => {
    let cancelled = false;
    setSyncing(true);
    setSyncError(null);

    fetchRecords(apiBaseUrl, user.userId, getLocalDateString(), { accessToken })
      .then((data) => {
        if (cancelled) return;
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
  }, [accessToken, apiBaseUrl, replaceDashboardFromRecords, user.userId]);

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
        <Link href="/scanner" asChild>
          <PrimaryButton label="掃描下一餐" icon={<Ionicons name="scan-outline" size={18} color={Palette.text.inverse} />} />
        </Link>
      </View>

      {healthAlerts.length > 0 ? (
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
      ) : null}

      <View style={styles.metricGrid}>
        <MetricCard label="BMR" value={user.bmr} unit="kcal" accent={Palette.text.primary} />
        <MetricCard label="TDEE" value={user.tdee} unit="kcal" accent={Palette.accent.blue} />
        <MetricCard label="已攝取" value={Math.round(calories.current)} unit="kcal" accent={Palette.accent.green} />
      </View>

      <SectionBlock title="營養素分佈" subtitle="用每日目標檢查是否偏離健康範圍。">
        <View style={styles.nutrientStack}>
          <NutrientBar label={protein.label} current={protein.current} target={protein.target} unit={protein.unit} color={protein.color} />
          <NutrientBar label={carbs.label} current={carbs.current} target={carbs.target} unit={carbs.unit} color={carbs.color} />
          <NutrientBar label={fat.label} current={fat.current} target={fat.target} unit={fat.unit} color={fat.color} />
          <NutrientBar label={sodium.label} current={sodium.current} target={sodium.target} unit={sodium.unit} color={sodium.current >= sodium.target * 0.8 ? Palette.status.warning : sodium.color} />
          <NutrientBar label={fiber.label} current={fiber.current} target={fiber.target} unit={fiber.unit} color={fiber.color} />
        </View>
      </SectionBlock>

      <View style={styles.mealsHeader}>
        <View>
          <Text style={styles.sectionTitle}>今日餐點時間軸</Text>
          <Text style={styles.sectionSubtitle}>依後端紀錄同步顯示</Text>
        </View>
        <DataPill tone="info">{todayMeals.length} 筆</DataPill>
      </View>

      {todayMeals.map((meal) => (
        <MealCard key={meal.id} meal={meal} />
      ))}

      {!syncing && !syncError && todayMeals.length === 0 ? (
        <View style={styles.emptyMealsCard}>
          <Ionicons name="restaurant-outline" size={26} color={Palette.text.tertiary} />
          <Text style={styles.emptyMealsTitle}>今天尚未新增餐點</Text>
          <Text style={styles.emptyMealsText}>到「辨識」頁拍照、手動搜尋或使用營養標示 OCR 後，這裡會從後端同步顯示。</Text>
        </View>
      ) : null}
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
  metricGrid: { flexDirection: 'row', gap: Spacing.sm, marginBottom: Spacing.xl },
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
