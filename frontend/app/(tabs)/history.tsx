import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { WEEKLY_HISTORY, WEEKLY_SUMMARY } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';

export default function HistoryScreen() {
  const { rs, isSmall } = useResponsive();
  const { user } = useStore();
  const target = user.dailyCalorieTarget;
  const maxCal = Math.max(...WEEKLY_HISTORY.map((d) => d.calories), target);
  const summary = WEEKLY_SUMMARY;

  return (
    <AppContainer>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>飲食趨勢</Text>
        <Text style={[styles.subtitle, { fontSize: rs(13) }]}>追蹤長期營養攝取，掌握健康節奏</Text>
      </View>

      {/* Summary stats */}
      <View style={[styles.summaryCard, { padding: rs(16) }]}>
        {[
          { label: '本週均值', value: summary.avgCalories, unit: 'kcal/日', color: Palette.accent.green },
          { label: '達標天數', value: `${summary.calorieGoalHitDays}/${summary.totalDays}`, unit: '天', color: Palette.accent.cyan },
          { label: '趨勢', value: summary.trend === 'stable' ? '→' : summary.trend === 'improving' ? '↑' : '↓', unit: summary.trend === 'stable' ? '穩定' : summary.trend === 'improving' ? '改善中' : '下降', color: Palette.accent.orange },
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

      {/* Bar Chart */}
      <View style={[styles.chartCard, { padding: rs(16) }]}>
        <View style={styles.chartTitleRow}>
          <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0 }]}>每日熱量追蹤</Text>
          <View style={styles.targetBadge}>
            <Ionicons name="flag" size={rs(10)} color={Palette.accent.green} />
            <Text style={[styles.targetBadgeText, { fontSize: rs(10) }]}>目標 {target} kcal</Text>
          </View>
        </View>
        <View style={styles.barsContainer}>
          {WEEKLY_HISTORY.map((day, index) => {
            const barHeight = (day.calories / maxCal) * 100;
            const isToday = index === WEEKLY_HISTORY.length - 1;
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
                  {day.date}
                </Text>
              </View>
            );
          })}
        </View>
      </View>

      {/* Nutrient Averages */}
      <View style={[styles.sectionCard, { padding: rs(16) }]}>
        <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>營養素週均值</Text>
        {[
          { label: '蛋白質', avg: summary.avgProtein, target: 130, unit: 'g', color: Palette.accent.blue },
          { label: '碳水', avg: summary.avgCarbs, target: 250, unit: 'g', color: Palette.accent.orange },
          { label: '脂肪', avg: summary.avgFat, target: 70, unit: 'g', color: Palette.accent.purple },
          { label: '鈉', avg: summary.avgSodium, target: 2000, unit: 'mg', color: Palette.accent.pink },
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

      {/* AI Insights */}
      <View style={[styles.sectionCard, { padding: rs(16) }]}>
        <View style={styles.insightsHeader}>
          <Ionicons name="bulb" size={rs(16)} color={Palette.accent.cyan} />
          <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0 }]}>AI 洞察</Text>
        </View>
        {summary.insights.map((insight, i) => (
          <View key={i} style={[styles.insightRow, i < summary.insights.length - 1 && styles.insightRowBordered]}>
            <Text style={styles.insightIcon}>{insight.icon}</Text>
            <Text style={[styles.insightText, { fontSize: rs(13) }]}>{insight.text}</Text>
          </View>
        ))}
      </View>

      {/* Sodium Trend */}
      <View style={[styles.sectionCard, { padding: rs(16) }]}>
        <View style={styles.sodiumHeader}>
          <Ionicons name="medkit" size={rs(14)} color={Palette.accent.pink} />
          <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0, flex: 1 }]}>鈉攝取趨勢</Text>
          <View style={styles.sodiumLimitBadge}>
            <Text style={[styles.sodiumLimitText, { fontSize: rs(9) }]}>上限 2,000mg</Text>
          </View>
        </View>
        <View style={styles.sodiumBars}>
          {WEEKLY_HISTORY.map((day) => {
            const ratio = day.sodium / 2000;
            const isOver = ratio > 1;
            return (
              <View key={day.date} style={styles.sodiumBarCol}>
                <Text style={[styles.sodiumBarVal, { fontSize: rs(8), color: isOver ? Palette.status.error : Palette.accent.pink }]}>
                  {day.sodium}
                </Text>
                <View style={[styles.sodiumBarTrack, { height: rs(isSmall ? 50 : 60) }]}>
                  <View style={[
                    styles.sodiumBarFill,
                    { height: `${Math.min(ratio, 1) * 100}%` },
                    isOver && styles.sodiumBarOver,
                  ]} />
                </View>
                <Text style={[styles.sodiumBarLabel, { fontSize: rs(9) }]}>{day.date.slice(-2)}</Text>
              </View>
            );
          })}
        </View>
      </View>
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  header: { marginTop: Spacing.lg, marginBottom: Spacing.xl },
  title: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  subtitle: { ...Typography.body, color: Palette.text.tertiary },

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
