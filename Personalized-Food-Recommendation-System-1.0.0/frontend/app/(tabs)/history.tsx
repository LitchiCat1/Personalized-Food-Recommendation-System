import React, { useCallback, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Link, useFocusEffect } from 'expo-router';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import ProgressBar from '@/components/ui/progress-bar';
import PrimaryButton from '@/components/ui/primary-button';
import { DEFAULT_NUTRITION_GOAL_TYPES, fetchAllRecordsWithTargets, type NutritionGoalTypes, type NutritionTargets } from '@/lib/api';
import { buildDietaryTrend, type DietaryTrendData } from '@/lib/dietary-trends';
import { buildTrendChart, buildTrendInsights, classifyCalories, formatTrendDate } from '@/lib/trend-insights';

export default function HistoryScreen() {
  const { width, fontScale, isDesktop } = useResponsive();
  const accessibleRows = fontScale > 1.3 || width < 350;
  const { user, apiBaseUrl, accessToken, dietaryRecordsRevision } = useStore();
  const [trend, setTrend] = useState<DietaryTrendData | null>(null);
  // 目標要跟首頁同一份：後端依疾病條件調整過的值。之前這頁用使用者自填的
  // 熱量目標和一組寫死的通用成人數值，同一筆紀錄在兩頁會得到相反的結論。
  const [targets, setTargets] = useState<NutritionTargets | null>(null);
  const [goalTypes, setGoalTypes] = useState<NutritionGoalTypes>({});
  const target = targets?.calories ?? user.dailyCalorieTarget;
  // 鈉也要跟熱量一樣用後端依疾病調整過的目標。寫死 2000 會讓腎臟病患者
  // （每日上限 1500mg）在首頁看到「超標」、在這頁看到「沒有明顯超標日」。
  const sodiumTarget = targets?.sodium ?? 2000;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      const requestRevision = dietaryRecordsRevision;
      void reloadKey;
      setLoading(true);
      setError(null);

      fetchAllRecordsWithTargets(apiBaseUrl, user.userId, { accessToken })
        .then(({ records, targets: nextTargets, goalTypes: nextGoalTypes }) => {
          if (!cancelled && requestRevision === useStore.getState().dietaryRecordsRevision) {
            setTargets(nextTargets ?? null);
            setGoalTypes(nextGoalTypes ?? {});
            setTrend(buildDietaryTrend(records, { maxDays: 7, userId: user.userId }));
          }
        })
        .catch((err: Error) => {
          if (cancelled) return;
          setTrend(null);
          setError(err.message);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });

      return () => {
        cancelled = true;
      };
    }, [accessToken, apiBaseUrl, dietaryRecordsRevision, reloadKey, user.userId])
  );

  const daily = useMemo(() => trend?.daily || [], [trend]);
  const summary = useMemo(() => trend?.summary || {}, [trend]);
  const calorieChart = buildTrendChart(daily, 'calories', target);
  const sodiumChart = buildTrendChart(daily, 'sodium', sodiumTarget);
  const calorieGoalHitDays = daily.filter((d) => classifyCalories(d.calories, target) === 'on-target').length;
  const sodiumOverDays = sodiumChart.points.filter((point) => point.overLimit).length;
  const insights = useMemo(() => buildTrendInsights(summary, daily, target, sodiumTarget), [summary, daily, target, sodiumTarget]);
  const totalRecords = summary.total_records || daily.reduce((sum, day) => sum + (day.record_count || 0), 0);
  const recordedDays = summary.recorded_days || daily.length;

  return (
    <AppContainer>
      <ScreenHeader title="飲食趨勢" />

      {loading ? (
        <StateCard icon="bar-chart-outline" text="讀取歷史紀錄中..." loading />
      ) : error ? (
        <StateCard
          icon="cloud-offline-outline"
          text={`無法載入歷史資料：${error}`}
          tone="warning"
          action={<PrimaryButton label="重新讀取" onPress={() => setReloadKey((key) => key + 1)} icon={<Ionicons name="refresh-outline" size={18} color={Palette.text.inverse} />} />}
        />
      ) : daily.length === 0 ? (
        <View style={styles.stateCard}>
          <Ionicons name="bar-chart-outline" size={30} color={Palette.text.tertiary} />
          <Text style={styles.emptyText}>尚未建立飲食趨勢，先新增第一筆餐點。</Text>
          <Link href="/scanner" asChild>
            <PrimaryButton label="新增第一筆餐點" icon={<Ionicons name="scan-outline" size={18} color={Palette.text.inverse} />} />
          </Link>
        </View>
      ) : (
        <>
          <SectionBlock title="紀錄區間" subtitle={dateRange(daily[0].date, daily[daily.length - 1].date)} numericSubtitle>
            <View style={styles.summaryRow}>
              <SummaryMetric label="平均每日熱量" value={summary.avg_calories ?? 0} unit="kcal" />
              <SummaryMetric label="紀錄天數" value={recordedDays} unit="天" />
              <SummaryMetric label="餐點紀錄" value={totalRecords} unit="餐" />
            </View>
          </SectionBlock>

          <View style={isDesktop && styles.desktopColumns}>
            <View style={isDesktop && styles.desktopMain}>
              <SectionBlock title="每日熱量" subtitle={`目標 ${displayNumber.format(target)} kcal · 達標 ${calorieGoalHitDays}/${daily.length} 天`} numericSubtitle>
                <TrendChart chart={calorieChart} unit="kcal" riskLabel="偏高" targetLabel="目標" accessibleRows={accessibleRows} />
                <Text style={styles.legendNote}>達標區間為目標的 85%–115%</Text>
              </SectionBlock>
              <SectionBlock title="每日鈉攝取" subtitle={`每日上限 ${displayNumber.format(sodiumTarget)} mg · 超標 ${sodiumOverDays}/${daily.length} 天`} numericSubtitle>
                <TrendChart chart={sodiumChart} unit="mg" riskLabel="超標" targetLabel="每日上限" accessibleRows={accessibleRows} />
              </SectionBlock>
            </View>
            <View style={isDesktop && styles.desktopAside}>
              <SectionBlock title="近期洞察">
                <View style={styles.insightStack}>
                  {insights.slice(1).map((insight) => (
                    <View key={insight} style={styles.insightRow}>
                      <Ionicons name="information-circle-outline" size={18} color={Palette.text.secondary} />
                      <Text style={styles.insightText}>{insight}</Text>
                    </View>
                  ))}
                </View>
              </SectionBlock>
              <SectionBlock title="平均每日營養攝取">
                <View style={styles.progressStack}>
                  <ProgressBar label="蛋白質" current={summary.avg_protein || 0} target={targets?.protein ?? 130} unit="g" color={Palette.accent.blue} goalType={goalTypes['protein'] ?? DEFAULT_NUTRITION_GOAL_TYPES['protein']} />
                  <ProgressBar label="總碳水化合物" current={summary.avg_carbs || 0} target={targets?.carbs ?? 250} unit="g" color={Palette.accent.orange} goalType={goalTypes['carbs'] ?? DEFAULT_NUTRITION_GOAL_TYPES['carbs']} />
                  <ProgressBar label="精緻糖" current={summary.avg_sugar || 0} target={targets?.sugar ?? 25} unit="g" color={Palette.accent.orange} goalType={goalTypes['sugar'] ?? DEFAULT_NUTRITION_GOAL_TYPES['sugar']} />
                  <ProgressBar label="總脂肪" current={summary.avg_fat || 0} target={targets?.fat ?? 70} unit="g" color={Palette.accent.purple} goalType={goalTypes['fat'] ?? DEFAULT_NUTRITION_GOAL_TYPES['fat']} />
                  <ProgressBar label="飽和脂肪" current={summary.avg_saturated_fat || 0} target={targets?.saturated_fat ?? 20} unit="g" color={Palette.accent.purple} goalType={goalTypes['saturated_fat'] ?? DEFAULT_NUTRITION_GOAL_TYPES['saturated_fat']} />
                  <ProgressBar label="反式脂肪" current={summary.avg_trans_fat || 0} target={0} unit="g" color={Palette.status.error} goalType={goalTypes['trans_fat'] ?? DEFAULT_NUTRITION_GOAL_TYPES['trans_fat']} />
                  <ProgressBar label="膳食纖維" current={summary.avg_fiber || 0} target={targets?.fiber ?? 25} unit="g" color={Palette.accent.green} goalType={goalTypes['fiber'] ?? DEFAULT_NUTRITION_GOAL_TYPES['fiber']} />
                  <ProgressBar label="鈉" current={summary.avg_sodium || 0} target={sodiumTarget} unit="mg" color={(summary.avg_sodium || 0) > sodiumTarget * 0.9 ? Palette.status.warning : Palette.accent.pink} goalType={goalTypes['sodium'] ?? DEFAULT_NUTRITION_GOAL_TYPES['sodium']} />
                </View>
              </SectionBlock>
            </View>
          </View>
        </>
      )}
    </AppContainer>
  );
}

const displayNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });

function dateRange(first: string, last: string) {
  const start = first.replace(/-/g, '/');
  if (first === last) return start;
  const end = first.slice(0, 4) === last.slice(0, 4) ? last.slice(5) : last;
  return start + ' 至 ' + end.replace(/-/g, '/');
}

function SummaryMetric({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <View style={styles.summaryMetric}>
      <Text style={styles.seriesLabel}>{label}</Text>
      <Text style={styles.summaryValue}>{displayNumber.format(value)} <Text style={styles.seriesLabel}>{unit}</Text></Text>
    </View>
  );
}

function TrendChart({ chart, unit, riskLabel, targetLabel, accessibleRows }: {
  chart: ReturnType<typeof buildTrendChart>;
  unit: 'kcal' | 'mg';
  riskLabel: string;
  targetLabel: string;
  accessibleRows: boolean;
}) {
  const fill = unit === 'kcal' ? Palette.accent.blue : Palette.accent.cyan;
  const warning = unit === 'kcal' ? Palette.status.warning : Palette.status.error;
  return (
    <>
      <View style={accessibleRows ? styles.chartList : styles.chartRow}>
        {chart.points.map((point) => {
          const date = formatTrendDate(point.date);
          const value = displayNumber.format(point.value);
          const status = [point.overLimit ? riskLabel : '', point.latest ? '最新' : ''].filter(Boolean).join('、');
          return (
            <View key={point.date} accessible
              accessibilityLabel={[date, value + ' ' + unit, status].filter(Boolean).join('，')}
              style={accessibleRows ? styles.chartListRow : styles.chartColumn}
            >
              {accessibleRows ? <Text style={styles.seriesLabel}>{date}{status ? ' · ' + status : ''}</Text> : null}
              <Text style={styles.seriesValue}>{value}{accessibleRows ? ' ' + unit : ''}</Text>
              {!accessibleRows ? (
                <>
                  <View style={styles.track} aria-hidden>
                    <View testID={'trend-' + unit + '-bar-' + point.date} style={[styles.bar, { height: `${point.percent}%`, backgroundColor: point.overLimit ? warning : fill }]} />
                    <View style={[styles.referenceMark, { bottom: `${chart.targetPercent}%` }]} />
                  </View>
                  <Text style={[styles.seriesLabel, point.latest && styles.latestDate]}>{date}</Text>
                  <Text style={styles.riskLabel}>{point.overLimit ? riskLabel : point.latest ? '最新' : ''}</Text>
                </>
              ) : null}
            </View>
          );
        })}
      </View>
      {!accessibleRows ? (
        <View style={styles.legend}>
          <View style={styles.referenceKey} />
          <Text style={styles.seriesLabel}>{targetLabel}參考線</Text>
        </View>
      ) : null}
    </>
  );
}

function StateCard({ icon, text, loading, tone, action }: { icon: keyof typeof Ionicons.glyphMap; text: string; loading?: boolean; tone?: 'warning'; action?: React.ReactNode }) {
  return (
    <View style={styles.stateCard}>
      {loading ? <ActivityIndicator size="large" color={Palette.accent.green} /> : <Ionicons name={icon} size={30} color={tone === 'warning' ? Palette.status.warning : Palette.text.tertiary} />}
      <Text style={styles.emptyText} selectable>{text}</Text>
      {action}
    </View>
  );
}

const styles = StyleSheet.create({
  summaryRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.md },
  summaryMetric: { flexGrow: 1, flexBasis: 84, gap: Spacing.xs, paddingTop: Spacing.sm, borderTopWidth: 1, borderTopColor: Palette.border.medium },
  summaryValue: { ...Typography.h2, ...Typography.number, color: Palette.text.primary },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xl },
  desktopMain: { flex: 1.25, minWidth: 0 },
  desktopAside: { flex: 1, minWidth: 0 },
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
  chartRow: { flexDirection: 'row' },
  chartColumn: { flex: 1, minWidth: 0, alignItems: 'center', gap: Spacing.xs },
  chartList: { gap: Spacing.sm },
  chartListRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: Spacing.sm },
  seriesLabel: { ...Typography.small, fontVariant: Typography.number.fontVariant, color: Palette.text.secondary },
  seriesValue: { ...Typography.small, ...Typography.number, color: Palette.text.primary },
  latestDate: { ...Typography.number, color: Palette.text.primary, textDecorationLine: 'underline' },
  riskLabel: { ...Typography.small, color: Palette.text.primary, minHeight: 15 },
  track: { height: 104, width: '100%', justifyContent: 'flex-end', alignItems: 'center', backgroundColor: Palette.bg.elevated },
  bar: { width: '60%', maxWidth: 44, borderTopLeftRadius: Radius.sm, borderTopRightRadius: Radius.sm },
  referenceMark: { position: 'absolute', left: 0, right: 0, borderTopWidth: 1, borderStyle: 'dashed', borderColor: Palette.text.secondary },
  referenceKey: { width: 18, borderTopWidth: 1, borderStyle: 'dashed', borderColor: Palette.text.secondary },
  legend: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginTop: Spacing.sm },
  legendNote: { ...Typography.small, color: Palette.text.secondary, marginTop: Spacing.sm },
  progressStack: { gap: Spacing.lg },
  insightStack: { gap: Spacing.md },
  insightRow: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm, paddingVertical: Spacing.sm, borderTopWidth: 1, borderTopColor: Palette.border.subtle },
  insightText: { ...Typography.body, color: Palette.text.secondary, flex: 1, fontVariant: Typography.number.fontVariant },
});
