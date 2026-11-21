import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { Palette, Typography, Spacing } from '@/constants/theme';
import { formatCalories } from '@/lib/calorie-target';

type Props = {
  current: number | null;
  target: number | null;
};

const size = 124;
const strokeWidth = 8;
const radius = (size - strokeWidth) / 2;
const circumference = 2 * Math.PI * radius;

export default function CalorieRing({ current, target }: Props) {
  const over = current !== null && target !== null && current > target;
  const progress = current === null || target === null ? 0 : target <= 0 ? Number(over) : Math.min(Math.max(current / target, 0), 1);

  return (
    <View style={styles.container}>
      <Svg width={size} height={size} style={styles.ring} aria-hidden>
        <Circle cx={size / 2} cy={size / 2} r={radius} stroke={Palette.bg.elevated} strokeWidth={strokeWidth} fill="none" />
        {progress > 0 ? <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={over ? Palette.status.warning : Palette.accent.green}
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        /> : null}
      </Svg>
      <View style={styles.centerText}>
        <Text style={styles.label}>已攝取</Text>
        <Text style={styles.currentValue}>{current === null ? '—' : formatCalories(current)}</Text>
        <Text style={styles.label}>kcal</Text>
      </View>
      <Text style={styles.target}>目標 {target === null ? '—' : formatCalories(target)} kcal</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    width: size,
    maxWidth: '100%',
  },
  ring: {
    position: 'absolute',
    top: 0,
  },
  centerText: {
    minHeight: size,
    paddingHorizontal: Spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  currentValue: {
    ...Typography.h1,
    ...Typography.number,
    color: Palette.text.primary,
    textAlign: 'center',
  },
  label: {
    ...Typography.caption,
    color: Palette.text.secondary,
  },
  target: {
    ...Typography.caption,
    color: Palette.text.secondary,
    marginTop: Spacing.xs,
    textAlign: 'center',
  },
});
