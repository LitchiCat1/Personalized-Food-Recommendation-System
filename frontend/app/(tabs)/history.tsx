import React, { useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import { fetchHistory, type HistoryDay, type HistoryResponse } from '@/lib/api';

function buildInsights(summary: HistoryResponse['summary'], daily: HistoryDay[], target: number) {
  if (daily.length === 0) {
    return [
      { icon: 'ℹ️', text: '尚無歷史紀錄，先從掃描或手動加入餐點開始建立趨勢。' },
    ];
  }

  const overSodiumDay = daily.find((day) => day.sodium > 2000);
  const avgCalories = summary.avg_calories || 0;
  const latest = daily[daily.length - 1];

  return [
    { icon: '📊', text: `近 ${daily.length} 天平均熱量 ${avgCalories} kcal/日` },
    overSodiumDay
      ? { icon: '⚠️', text: `${overSodiumDay.date} 的鈉攝取超過 2,000mg，建議檢查加工食品比例` }
      : { icon: '✅', text: '近期待鈉攝取控制穩定，沒有明顯超標日' },
    latest.calories < target * 0.75
      ? { icon: '📉', text: `最近一天熱量偏低，距離目標仍差 ${Math.max(0, target - latest.calories)} kcal` }
      : { icon: '🎯', text: '最近一天的熱量接近個人目標，維持得不錯' },
  ];
}

export default function HistoryScreen() {
  const { rs, isSmall } = useResponsive();
  const { user, apiBaseUrl } = useStore();
  const target = user.dailyCalorieTarget;
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchHistory(apiBaseUrl, user.userId, 7)
      .then((data) => {
        if (!cancelled) {
          setHistory(data);
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
  }, [apiBaseUrl, user.userId]);

  const daily = useMemo(() => history?.daily || [], [history]);
  const summary = useMemo(() => history?.summary || {}, [history]);
  const maxCal = Math.max(target, ...daily.map((d) => d.calories), 1);
  const calorieGoalHitDays = daily.filter((d) => d.calories >= target * 0.85 && d.calories <= target * 1.15).length;
  const trend = daily.length >= 2 && daily[daily.length - 1].calories > daily[0].calories + 100
    ? 'improving'
    : daily.length >= 2 && daily[daily.length - 1].calories < daily[0].calories - 100
      ? 'declining'
      : 'stable';
  const insights = useMemo(() => buildInsights(summary, daily, target), [summary, daily, target]);
  const totalRecords = summary.total_records || daily.reduce((sum, day) => sum + (day.record_count || 0), 0);
  const recordedDays = summary.recorded_days || daily.length;

  return (
    <AppContainer>
      <View style={styles.header}>
        <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>飲食趨勢</Text>
        <Text style={[styles.subtitle, { fontSize: rs(13) }]}>追蹤長期營養攝取，掌握健康節奏</Text>
      </View>

      {loading ? (
        <View style={[styles.emptyCard, { padding: rs(24) }]}> 
          <ActivityIndicator size="large" color={Palette.accent.cyan} />
          <Text style={[styles.emptyText, { fontSize: rs(13) }]}>讀取歷史紀錄中...</Text>
        </View>
      ) : error ? (
        <View style={[styles.emptyCard, { padding: rs(24) }]}> 
          <Ionicons name="cloud-offline-outline" size={rs(30)} color={Palette.status.warning} />
          <Text style={[styles.emptyText, { fontSize: rs(13) }]}>無法載入歷史資料：{error}</Text>
        </View>
      ) : daily.length === 0 ? (
        <View style={[styles.emptyCard, { padding: rs(24) }]}> 
          <Ionicons name="bar-chart-outline" size={rs(30)} color={Palette.text.tertiary} />
          <Text style={[styles.emptyText, { fontSize: rs(13) }]}>尚未建立足夠的飲食紀錄，先加入幾筆餐點吧。</Text>
        </View>
      ) : (
        <>
          <View style={[styles.summaryCard, { padding: rs(16) }]}> 
            {[
              { label: '本週均值', value: summary.avg_calories || 0, unit: 'kcal/日', color: Palette.accent.green },
              { label: '紀錄餐數', value: totalRecords, unit: `筆 / ${recordedDays} 天`, color: Palette.accent.cyan },
              { label: '達標天數', value: `${calorieGoalHitDays}/${daily.length}`, unit: '天', color: Palette.accent.blue },
              { label: '趨勢', value: trend === 'stable' ? '→' : trend === 'improving' ? '↑' : '↓', unit: trend === 'stable' ? '穩定' : trend === 'improving' ? '改善中' : '下降', color: Palette.accent.orange },
            ].map((item, i) => (
              <React.Fragment key={item.label}>
                {i > 0 && <View style={styles.summaryDivider} />}
                <View style={styles.summaryItem}>
                  <Text style={[styles.summaryLabel, { fontSize: rs(10) }]}>{item.label}</Text>
                  <Text style={[styles.summaryValue, { fontSize: rs(18), color: item.color }]}>{item.value}</Text>
                  <Text style={[styles.summaryUnit, { fontSize: rs(9) }]}>{item.unit}</Text>
                </View>
              </React.Fragment>
            ))}
          </View>

          <View style={[styles.chartCard, { padding: rs(16) }]}> 
            <View style={styles.chartTitleRow}>
              <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0 }]}>每日熱量追蹤</Text>
              <View style={styles.targetBadge}>
                <Ionicons name="flag" size={rs(10)} color={Palette.accent.green} />
                <Text style={[styles.targetBadgeText, { fontSize: rs(10) }]}>目標 {target} kcal</Text>
              </View>
            </View>
            <View style={styles.barsContainer}>
              {daily.map((day, index) => {
                const barHeight = (day.calories / maxCal) * 100;
                const isToday = index === daily.length - 1;
                const overTarget = day.calories > target;
                return (
                  <View key={day.date} style={styles.barColumn}>
                    <Text style={[styles.barValue, { fontSize: rs(9), color: overTarget ? Palette.status.warning : Palette.text.tertiary }]}> 
                      {day.calories}
                    </Text>
                    <View style={[styles.barTrack, { height: rs(isSmall ? 100 : 130) }]}> 
                      <View
                        style={[
                          styles.barFill,
                          { height: `${barHeight}%` },
                          overTarget && styles.barFillOver,
                          isToday && styles.barFillToday,
                        ]}
                      />
                    </View>
                    <Text style={[styles.barLabel, { fontSize: rs(10), color: isToday ? Palette.accent.green : Palette.text.tertiary }]}> 
                      {day.date.slice(5)}
                    </Text>
                  </View>
                );
              })}
            </View>
          </View>

          <View style={[styles.sectionCard, { padding: rs(16) }]}> 
            <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>營養素週均值</Text>
            {[
              { label: '蛋白質', avg: summary.avg_protein || 0, target: 130, unit: 'g', color: Palette.accent.blue },
              { label: '碳水', avg: summary.avg_carbs || 0, target: 250, unit: 'g', color: Palette.accent.orange },
              { label: '脂肪', avg: summary.avg_fat || 0, target: 70, unit: 'g', color: Palette.accent.purple },
              { label: '鈉', avg: summary.avg_sodium || 0, target: 2000, unit: 'mg', color: Palette.accent.pink },
            ].map((item) => {
              const progress = Math.min(item.avg / item.target, 1);
              return (
                <View key={item.label} style={styles.avgRow}>
                  <View style={styles.avgLabelRow}>
                    <View style={[styles.avgDot, { backgroundColor: item.color }]} />
                    <Text style={[styles.avgLabel, { fontSize: rs(12) }]}>{item.label}</Text>
                    <Text style={[styles.avgValue, { fontSize: rs(13), color: item.color }]}>{item.avg} {item.unit}</Text>
                  </View>
                  <View style={[styles.avgTrack, { backgroundColor: item.color + '22' }]}> 
                    <View style={[styles.avgFill, { width: `${progress * 100}%`, backgroundColor: item.color }]} />
                  </View>
                  <Text style={[styles.avgTarget, { fontSize: rs(9) }]}>目標 {item.target}{item.unit}</Text>
                </View>
              );
            })}
          </View>

          <View style={[styles.sectionCard, { padding: rs(16) }]}> 
            <View style={styles.insightsHeader}>
              <Ionicons name="bulb" size={rs(16)} color={Palette.accent.cyan} />
              <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0 }]}>趨勢洞察</Text>
            </View>
            {insights.map((insight, i) => (
              <View key={i} style={[styles.insightRow, i < insights.length - 1 && styles.insightRowBordered]}>
                <Text style={styles.insightIcon}>{insight.icon}</Text>
                <Text style={[styles.insightText, { fontSize: rs(13) }]}>{insight.text}</Text>
              </View>
            ))}
          </View>

          <View style={[styles.sectionCard, { padding: rs(16) }]}> 
            <View style={styles.sodiumHeader}>
              <Ionicons name="medkit" size={rs(14)} color={Palette.accent.pink} />
              <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0, flex: 1 }]}>鈉攝取趨勢</Text>
              <View style={styles.sodiumLimitBadge}>
                <Text style={[styles.sodiumLimitText, { fontSize: rs(9) }]}>上限 2,000mg</Text>
              </View>
            </View>
            <View style={styles.sodiumBars}>
              {daily.map((day) => {
                const ratio = day.sodium / 2000;
                const isOver = ratio > 1;
                return (
                  <View key={day.date} style={styles.sodiumBarCol}>
                    <Text style={[styles.sodiumBarVal, { fontSize: rs(8), color: isOver ? Palette.status.error : Palette.accent.pink }]}> 
                      {day.sodium}
                    </Text>
                    <View style={[styles.sodiumBarTrack, { height: rs(isSmall ? 50 : 60) }]}> 
                      <View
                        style={[
                          styles.sodiumBarFill,
                          { height: `${Math.min(ratio, 1) * 100}%` },
                          isOver && styles.sodiumBarOver,
                        ]}
                      />
                    </View>
                    <Text style={[styles.sodiumBarLabel, { fontSize: rs(9) }]}>{day.date.slice(-2)}</Text>
                  </View>
                );
              })}
            </View>
          </View>
        </>
      )}
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  header: { marginTop: Spacing.lg, marginBottom: Spacing.xl },
  title: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  subtitle: { ...Typography.body, color: Palette.text.tertiary },

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
    flexDirection: 'row', backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  summaryItem: { flex: 1, alignItems: 'center' },
  summaryLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  summaryValue: { ...Typography.h2 },
  summaryUnit: { ...Typography.small, color: Palette.text.tertiary },
  summaryDivider: { width: 1, backgroundColor: Palette.border.subtle },

  chartCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary, marginBottom: Spacing.lg },
  chartTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg },
  targetBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: Palette.accent.greenDim, paddingHorizontal: 10, paddingVertical: 4, borderRadius: Radius.full,
  },
  targetBadgeText: { ...Typography.small, color: Palette.accent.green, fontWeight: '600' },
  barsContainer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  barColumn: { flex: 1, alignItems: 'center' },
  barValue: { ...Typography.small, marginBottom: 4 },
  barTrack: {
    width: '65%', backgroundColor: Palette.bg.elevated, borderRadius: Radius.sm,
    overflow: 'hidden', justifyContent: 'flex-end',
  },
  barFill: { width: '100%', backgroundColor: Palette.accent.blue, borderRadius: Radius.sm, opacity: 0.7 },
  barFillOver: { backgroundColor: Palette.status.warning },
  barFillToday: { backgroundColor: Palette.accent.green, opacity: 1 },
  barLabel: { ...Typography.small, marginTop: 6 },

  sectionCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  avgRow: { marginBottom: Spacing.lg },
  avgLabelRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  avgDot: { width: 8, height: 8, borderRadius: 4, marginRight: Spacing.sm },
  avgLabel: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  avgValue: { ...Typography.bodyBold },
  avgTrack: { height: 8, borderRadius: Radius.full, overflow: 'hidden', marginBottom: 4 },
  avgFill: { height: '100%', borderRadius: Radius.full },
  avgTarget: { ...Typography.small, color: Palette.text.tertiary, textAlign: 'right' },

  insightsHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.lg },
  insightRow: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.md, paddingVertical: Spacing.md },
  insightRowBordered: { borderBottomWidth: 1, borderBottomColor: Palette.border.subtle },
  insightIcon: { fontSize: 16, marginTop: 2 },
  insightText: { ...Typography.body, color: Palette.text.secondary, flex: 1, lineHeight: 22 },

  sodiumHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.lg },
  sodiumLimitBadge: { backgroundColor: 'rgba(244,114,182,0.12)', paddingHorizontal: 8, paddingVertical: 2, borderRadius: Radius.full },
  sodiumLimitText: { ...Typography.small, color: Palette.accent.pink },
  sodiumBars: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  sodiumBarCol: { flex: 1, alignItems: 'center' },
  sodiumBarVal: { ...Typography.small, marginBottom: 4 },
  sodiumBarTrack: {
    width: '55%', backgroundColor: Palette.bg.elevated, borderRadius: Radius.sm,
    overflow: 'hidden', justifyContent: 'flex-end',
  },
  sodiumBarFill: { width: '100%', backgroundColor: Palette.accent.pink, borderRadius: Radius.sm, opacity: 0.6 },
  sodiumBarOver: { backgroundColor: Palette.status.error, opacity: 1 },
  sodiumBarLabel: { ...Typography.small, color: Palette.text.tertiary, marginTop: 4 },
});
