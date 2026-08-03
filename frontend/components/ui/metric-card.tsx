import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';

type Props = {
  label: string;
  value: string | number;
  unit?: string;
  accent: string;
  tone?: 'default' | 'soft';
};

export default function MetricCard({ label, value, unit, accent, tone = 'default' }: Props) {
  return (
    <View style={[styles.card, tone === 'soft' && styles.softCard]}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={[styles.value, { color: accent }]}>{value}</Text>
        {unit ? <Text style={[styles.unit, { color: accent }]}>{unit}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    minWidth: 0,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.lg,
    gap: Spacing.xs,
    ...Shadows.soft,
  },
  softCard: {
    backgroundColor: Palette.bg.mint,
  },
  label: { ...Typography.small, color: Palette.text.secondary },
  valueRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', gap: 4 },
  value: { ...Typography.h2, ...Typography.number },
  unit: { ...Typography.caption, ...Typography.number },
});
