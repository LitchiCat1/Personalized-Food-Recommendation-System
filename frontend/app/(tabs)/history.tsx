import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import MetricCard from '@/components/ui/metric-card';
import DataPill from '@/components/ui/data-pill';
import ProgressBar from '@/components/ui/progress-bar';
import { fetchHistory, type HistoryDay, type HistoryResponse } from '@/lib/api';

function buildInsights(summary: HistoryResponse['summary'], daily: HistoryDay[], target: number) {
  if (daily.length === 0) {
    return ['尚無歷史紀錄，先從掃描或手動加入餐點開始建立趨勢。'];
  }

  const overSodiumDay = daily.find((day) => day.sodium > 2000);
  const avgCalories = summary.avg_calories || 0;
  const latest = daily[daily.length - 1];

  return [
    `近 ${daily.length} 天平均熱量 ${avgCalories} kcal/日。`,
    overSodiumDay
      ? `${overSodiumDay.date} 的鈉攝取超過 2,000mg，建議檢查加工食品與外食比例。`
      : '近期鈉攝取沒有明顯超標日，維持目前記錄習慣。',
    latest.calories < target * 0.75
      ? `最近一天熱量偏低，距離目標仍差 ${Math.max(0, target - latest.calories)} kcal。`
      : '最近一天的熱量接近個人目標，可觀察蛋白質與纖維是否同步達標。',
  ];
}

export default function HistoryScreen() {
  const { rs, isSmall } = useResponsive();
  const { user, apiBaseUrl, accessToken } = useStore();
  const target = user.dailyCalorieTarget;
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchHistory(apiBaseUrl, user.userId, 7, { accessToken })
      .then((data) => {
        if (!cancelled) setHistory(data);
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

  const daily = useMemo(() => history?.daily || [], [history]);
  const summary = useMemo(() => history?.summary || {}, [history]);
  const maxCal = Math.max(target, ...daily.map((d) => d.calories), 1);
  const calorieGoalHitDays = daily.filter((d) => d.calories >= target * 0.85 && d.calories <= target * 1.15).length;
  const sodiumOverDays = daily.filter((d) => d.sodium > 2000).length;
  const insights = useMemo(() => buildInsights(summary, daily, target), [summary, daily, target]);
  const totalRecords = summary.total_records || daily.reduce((sum, day) => sum + (day.record_count || 0), 0);
  const recordedDays = summary.recorded_days || daily.length;

  return (
    <AppContainer>
      <ScreenHeader title="飲食趨勢" subtitle="用 7 日資料檢查熱量、營養素和鈉攝取風險。" badge="7 日摘要" badgeTone="info" />

      {loading ? (
        <StateCard icon="bar-chart-outline" text="讀取歷史紀錄中..." loading />
      ) : error ? (
        <StateCard icon="cloud-offline-outline" text={`無法載入歷史資料：${error}`} tone="warning" />
      ) : daily.length === 0 ? (
        <StateCard icon="bar-chart-outline" text="尚未建立足夠的飲食紀錄，先加入幾筆餐點吧。" />
      ) : (
        <>
          <View style={styles.metricRow}>
            <MetricCard label="本週均值" value={summary.avg_calories || 0} unit="kcal" accent={Palette.accent.green} />
            <MetricCard label="紀錄餐數" value={totalRecords} unit={`/${recordedDays}天`} accent={Palette.accent.blue} />
            <MetricCard label="鈉超標" value={sodiumOverDays} unit="天" accent={sodiumOverDays > 0 ? Palette.status.warning : Palette.accent.green} />
          </View>

          <SectionBlock title="每日熱量追蹤" subtitle={`目標 ${target} kcal，達標 ${calorieGoalHitDays}/${daily.length} 天。`}>
            <View style={styles.chartTitleRow}>
              <DataPill tone="success">目標 {target} kcal</DataPill>
              <DataPill tone={calorieGoalHitDays >= Math.ceil(daily.length / 2) ? 'success' : 'warning'}>達標 {calorieGoalHitDays} 天</DataPill>
            </View>
            <View style={styles.barsContainer}>
              {daily.map((day, index) => {
                const barHeight = (day.calories / maxCal) * 100;
                const isToday = index === daily.length - 1;
                const overTarget = day.calories > target * 1.15;
                return (
                  <View key={day.date} style={styles.barColumn}>
                    <Text style={[styles.barValue, { color: overTarget ? Palette.status.warning : Palette.text.tertiary }]}>{day.calories}</Text>
                    <View style={[styles.barTrack, { height: rs(isSmall ? 108 : 132) }]}>
                      <View style={[styles.barFill, { height: `${barHeight}%` }, overTarget && styles.barFillOver, isToday && styles.barFillToday]} />
                    </View>
                    <Text style={[styles.barLabel, isToday && styles.barLabelToday]}>{day.date.slice(5)}</Text>
                  </View>
                );
              })}
            </View>
          </SectionBlock>

          <SectionBlock title="營養素週均值" subtitle="比對週平均與建議目標，找出長期偏差。">
            <View style={styles.progressStack}>
              <ProgressBar label="蛋白質" current={summary.avg_protein || 0} target={130} unit="g" color={Palette.accent.blue} />
              <ProgressBar label="碳水" current={summary.avg_carbs || 0} target={250} unit="g" color={Palette.accent.orange} />
              <ProgressBar label="脂肪" current={summary.avg_fat || 0} target={70} unit="g" color={Palette.accent.purple} />
              <ProgressBar label="鈉" current={summary.avg_sodium || 0} target={2000} unit="mg" color={(summary.avg_sodium || 0) > 1800 ? Palette.status.warning : Palette.accent.pink} />
            </View>
          </SectionBlock>

          <SectionBlock title="鈉攝取風險" subtitle="以 2,000mg 作為健康管理提醒上限。">
            <View style={styles.sodiumBars}>
              {daily.map((day) => {
                const ratio = day.sodium / 2000;
                const isOver = ratio > 1;
                return (
                  <View key={day.date} style={styles.sodiumBarCol}>
                    <Text style={[styles.sodiumBarVal, { color: isOver ? Palette.status.error : Palette.accent.pink }]}>{day.sodium}</Text>
                    <View style={[styles.sodiumBarTrack, { height: rs(isSmall ? 58 : 68) }]}>
                      <View style={[styles.sodiumBarFill, { height: `${Math.min(ratio, 1) * 100}%` }, isOver && styles.sodiumBarOver]} />
                    </View>
                    <Text style={styles.sodiumBarLabel}>{day.date.slice(-2)}</Text>
                  </View>
                );
              })}
            </View>
          </SectionBlock>

          <SectionBlock title="Clinical notes" subtitle="客觀整理近期飲食資料，協助下一餐選擇。">
            <View style={styles.insightStack}>
              {insights.map((insight, i) => (
                <View key={i} style={styles.insightRow}>
                  <View style={styles.noteIndex}><Text style={styles.noteIndexText}>{i + 1}</Text></View>
                  <Text style={styles.insightText}>{insight}</Text>
                </View>
              ))}
            </View>
          </SectionBlock>
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
  chartTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm, marginBottom: Spacing.lg },
  barsContainer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  barColumn: { flex: 1, alignItems: 'center' },
  barValue: { ...Typography.small, marginBottom: 4 },
  barTrack: {
    width: '62%',
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.full,
    overflow: 'hidden',
    justifyContent: 'flex-end',
  },
  barFill: { width: '100%', backgroundColor: Palette.accent.blue, borderRadius: Radius.full, opacity: 0.68 },
  barFillOver: { backgroundColor: Palette.status.warning },
  barFillToday: { backgroundColor: Palette.accent.green, opacity: 1 },
  barLabel: { ...Typography.small, color: Palette.text.tertiary, marginTop: 6 },
  barLabelToday: { color: Palette.accent.green },
  progressStack: { gap: Spacing.lg },
  sodiumBars: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  sodiumBarCol: { flex: 1, alignItems: 'center' },
  sodiumBarVal: { ...Typography.small, marginBottom: 4 },
  sodiumBarTrack: {
    width: '55%',
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.full,
    overflow: 'hidden',
    justifyContent: 'flex-end',
  },
  sodiumBarFill: { width: '100%', backgroundColor: Palette.accent.pink, borderRadius: Radius.full, opacity: 0.62 },
  sodiumBarOver: { backgroundColor: Palette.status.error, opacity: 1 },
  sodiumBarLabel: { ...Typography.small, color: Palette.text.tertiary, marginTop: 4 },
  insightStack: { gap: Spacing.md },
  insightRow: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.md, backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md },
  noteIndex: { width: 24, height: 24, borderRadius: 12, backgroundColor: Palette.bg.card, alignItems: 'center', justifyContent: 'center' },
  noteIndexText: { ...Typography.small, color: Palette.accent.green },
  insightText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
});
