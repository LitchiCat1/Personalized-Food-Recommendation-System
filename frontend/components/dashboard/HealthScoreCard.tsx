import React, { useMemo } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';

type NutrientEntry = { current: number; target: number };

type Props = {
  calories: NutrientEntry;
  protein: NutrientEntry;
  carbs: NutrientEntry;
  sugar: NutrientEntry;
  fat: NutrientEntry;
  saturated_fat: NutrientEntry;
  sodium: NutrientEntry;
  fiber: NutrientEntry;
  calcium: NutrientEntry;
  iron: NutrientEntry;
  hasMeals: boolean;
  hasFriedFood?: boolean;
};

type Deduction = { label: string; points: number; color: string };

function computeHealthScore(props: Props): { score: number; deductions: Deduction[] } {
  if (!props.hasMeals) return { score: 0, deductions: [] };

  let score = 100;
  const deductions: Deduction[] = [];

  const addDeduction = (label: string, points: number, color: string) => {
    score -= points;
    deductions.push({ label, points, color });
  };

  // Upper-limit nutrients: penalise if over target
  const upperLimits: [keyof Props, string][] = [
    ['calories', '熱量超標'],
    ['carbs', '碳水超標'],
    ['sugar', '精緻糖超標'],
    ['fat', '脂肪超標'],
    ['saturated_fat', '飽和脂肪超標'],
  ];
  for (const [key, label] of upperLimits) {
    const n = props[key] as NutrientEntry;
    if (n.target > 0 && n.current > n.target) {
      addDeduction(label, 10, Palette.status.error);
    }
  }

  // Sodium: over 80% = warning, over 100% = error
  if (props.sodium.target > 0) {
    const ratio = props.sodium.current / props.sodium.target;
    if (ratio > 1) addDeduction('鈉攝取超標', 12, Palette.status.error);
    else if (ratio > 0.8) addDeduction('鈉攝取接近上限', 6, Palette.status.warning);
  }

  // Minimum-target nutrients: penalise if below 50%
  const minTargets: [keyof Props, string][] = [
    ['fiber', '膳食纖維不足'],
    ['calcium', '鈣攝取不足'],
    ['iron', '鐵攝取不足'],
    ['protein', '蛋白質不足'],
  ];
  for (const [key, label] of minTargets) {
    const n = props[key] as NutrientEntry;
    if (n.target > 0 && n.current < n.target * 0.5) {
      addDeduction(label, 5, Palette.accent.orange);
    }
  }

  // Fried food penalty
  if (props.hasFriedFood) {
    addDeduction('含油炸食物', 5, Palette.accent.orange);
  }

  return { score: Math.max(0, Math.min(100, score)), deductions };
}

function getGrade(score: number, hasMeals: boolean): { label: string; color: string; icon: string } {
  if (!hasMeals) return { label: '等待記錄', color: Palette.text.tertiary, icon: 'time-outline' };
  if (score >= 85) return { label: '優秀', color: '#22C55E', icon: 'checkmark-circle-outline' };
  if (score >= 70) return { label: '良好', color: Palette.accent.green, icon: 'thumbs-up-outline' };
  if (score >= 50) return { label: '需注意', color: Palette.status.warning, icon: 'alert-circle-outline' };
  return { label: '高風險', color: Palette.status.error, icon: 'warning-outline' };
}

export default function HealthScoreCard(props: Props) {
  const { score, deductions } = useMemo(() => computeHealthScore(props), [props]);
  const grade = useMemo(() => getGrade(score, props.hasMeals), [score, props.hasMeals]);

  const ringColor = grade.color;
  const circumference = 2 * Math.PI * 28; // r=28
  const strokeDash = props.hasMeals ? (score / 100) * circumference : 0;

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        {/* Score ring */}
        <View style={styles.ringWrapper}>
          <View style={[styles.ringBg, { borderColor: Palette.bg.elevated }]}>
            <View style={[styles.ringFill, { borderColor: ringColor, borderWidth: 5, opacity: props.hasMeals ? 1 : 0.2 }]} />
          </View>
          <View style={styles.ringCenter}>
            <Text style={[styles.scoreText, { color: ringColor }]}>
              {props.hasMeals ? score : '—'}
            </Text>
            <Text style={styles.scoreLabel}>/ 100</Text>
          </View>
        </View>

        {/* Grade + deductions */}
        <View style={styles.infoCol}>
          <View style={styles.gradeRow}>
            <Ionicons name={grade.icon as any} size={18} color={grade.color} />
            <Text style={[styles.gradeText, { color: grade.color }]}>{grade.label}</Text>
          </View>
          <Text style={styles.subtitle}>今日健康評分</Text>
          {deductions.slice(0, 3).map((d) => (
            <View key={d.label} style={styles.deductionRow}>
              <Text style={[styles.deductionDot, { color: d.color }]}>●</Text>
              <Text style={styles.deductionText}>{d.label}</Text>
              <Text style={[styles.deductionPoints, { color: d.color }]}>-{d.points}</Text>
            </View>
          ))}
          {deductions.length === 0 && props.hasMeals && (
            <Text style={styles.perfectText}>🎉 今日飲食沒有扣分項</Text>
          )}
          {!props.hasMeals && (
            <Text style={styles.noDataText}>記錄第一餐後自動計算</Text>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.lg,
    marginBottom: Spacing.xl,
    ...Shadows.card,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.lg },
  ringWrapper: { position: 'relative', width: 80, height: 80, alignItems: 'center', justifyContent: 'center' },
  ringBg: {
    position: 'absolute',
    width: 80,
    height: 80,
    borderRadius: 40,
    borderWidth: 8,
  },
  ringFill: {
    width: 80,
    height: 80,
    borderRadius: 40,
  },
  ringCenter: { position: 'absolute', alignItems: 'center' },
  scoreText: { fontSize: 22, fontWeight: '800', ...Typography.number },
  scoreLabel: { ...Typography.small, color: Palette.text.tertiary },
  infoCol: { flex: 1, gap: 4 },
  gradeRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.xs, marginBottom: 2 },
  gradeText: { ...Typography.bodyBold },
  subtitle: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  deductionRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  deductionDot: { fontSize: 8, lineHeight: 16 },
  deductionText: { ...Typography.small, color: Palette.text.secondary, flex: 1 },
  deductionPoints: { ...Typography.small, fontWeight: '700' },
  perfectText: { ...Typography.small, color: '#22C55E' },
  noDataText: { ...Typography.small, color: Palette.text.tertiary },
});
