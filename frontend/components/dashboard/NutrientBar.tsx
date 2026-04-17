import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';

type Props = {
  label: string;
  current: number;
  target: number;
  unit: string;
  color: string;
};

export default function NutrientBar({ label, current, target, unit, color }: Props) {
  const progress = Math.min(current / target, 1);
  const dimColor = color + '22';

  return (
    <View style={styles.container}>
      <View style={styles.labelRow}>
        <View style={[styles.dot, { backgroundColor: color }]} />
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.values}>
          <Text style={{ color }}>{Math.round(current)}</Text>
          <Text style={styles.separator}> / </Text>
          <Text>{target}{unit}</Text>
        </Text>
      </View>
      <View style={[styles.trackBg, { backgroundColor: dimColor }]}>
        <View
          style={[
            styles.trackFill,
            {
              backgroundColor: color,
              width: `${progress * 100}%`,
            },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: Spacing.md,
  },
  labelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.xs + 2,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: Spacing.sm,
  },
  label: {
    ...Typography.caption,
    color: Palette.text.secondary,
    flex: 1,
  },
  values: {
    ...Typography.caption,
    color: Palette.text.secondary,
  },
  separator: {
    color: Palette.text.tertiary,
  },
  trackBg: {
    height: 8,
    borderRadius: Radius.full,
    overflow: 'hidden',
  },
  trackFill: {
    height: '100%',
    borderRadius: Radius.full,
  },
});
