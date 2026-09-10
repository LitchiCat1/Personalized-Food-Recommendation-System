import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import DataPill from '@/components/ui/data-pill';
import type { MealEntry } from '@/constants/mock-data';
import { perMealBudget } from '@/lib/meal';

type Props = {
  meal: MealEntry;
  /** 使用者的每日鈉上限（後端已依疾病調整）。同 ScannerResults，不再寫死 800mg。 */
  sodiumDailyTarget?: number;
};

export default function MealCard({ meal, sodiumDailyTarget }: Props) {
  const warnings = meal.warnings ?? [];
  const hasWarnings = warnings.length > 0;
  const sodiumMealBudget = perMealBudget(sodiumDailyTarget, 2000);

  return (
    <Pressable style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}>
      <View style={styles.timeRail}>
        <View style={[styles.dot, hasWarnings && styles.warningDot]} />
        <Text style={styles.time}>{meal.time}</Text>
      </View>
      <View style={styles.content}>
        <View style={styles.header}>
          <View style={styles.nameWrap}>
            <Text style={styles.name} numberOfLines={1}>{meal.name}</Text>
            <View style={styles.metaRow}>
              <DataPill tone={hasWarnings ? 'warning' : 'success'}>{meal.mealType}</DataPill>
              <Text style={styles.source}>{meal.emoji} 來源紀錄</Text>
            </View>
          </View>
          <View style={styles.calorieBox}>
            <Text style={styles.calorieValue}>{meal.calories}</Text>
            <Text style={styles.calorieUnit}>kcal</Text>
          </View>
        </View>

        <View style={styles.macroRow}>
          <Text style={styles.macro}>P {meal.protein}g</Text>
          <Text style={styles.macro}>C {meal.carbs}g</Text>
          <Text style={styles.macro}>F {meal.fat}g</Text>
          <Text style={[styles.macro, meal.sodium > sodiumMealBudget && styles.sodiumWarning]}>Na {meal.sodium}mg</Text>
        </View>

        {hasWarnings ? (
          <View style={styles.warning}>
            <Ionicons name="warning-outline" size={14} color={Palette.status.warning} />
            <Text style={styles.warningText}>{warnings.join('；')}</Text>
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    padding: Spacing.lg,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.soft,
  },
  cardPressed: {
    backgroundColor: Palette.bg.cardHover,
  },
  timeRail: { width: 58, alignItems: 'flex-start', gap: Spacing.sm },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: Palette.accent.green, marginTop: 4 },
  warningDot: { backgroundColor: Palette.status.warning },
  time: { ...Typography.small, color: Palette.text.tertiary },
  content: { flex: 1, gap: Spacing.md },
  header: { flexDirection: 'row', gap: Spacing.md, alignItems: 'flex-start' },
  nameWrap: { flex: 1, gap: Spacing.sm },
  name: { ...Typography.bodyBold, color: Palette.text.primary },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, flexWrap: 'wrap' },
  source: { ...Typography.small, color: Palette.text.tertiary },
  calorieBox: { alignItems: 'flex-end' },
  calorieValue: { ...Typography.h3, ...Typography.number, color: Palette.text.primary },
  calorieUnit: { ...Typography.small, color: Palette.text.tertiary },
  macroRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  macro: { ...Typography.small, color: Palette.text.secondary, backgroundColor: Palette.bg.elevated, borderRadius: Radius.full, paddingHorizontal: Spacing.sm, paddingVertical: 3 },
  sodiumWarning: { color: Palette.status.warning },
  warning: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm, backgroundColor: Palette.accent.orangeDim, borderRadius: Radius.md, padding: Spacing.sm },
  warningText: { ...Typography.small, color: Palette.status.warning, flex: 1 },
});
