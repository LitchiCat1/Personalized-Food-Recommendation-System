import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import { Palette, Typography, Spacing } from '@/constants/theme';
import { useResponsive } from '@/hooks/useResponsive';

type Props = {
  current: number;
  target: number;
  size?: number;
  strokeWidth?: number;
};

export default function CalorieRing({ current, target, size: sizeProp, strokeWidth: swProp }: Props) {
  const { rs, isSmall } = useResponsive();
  const size = sizeProp ?? rs(isSmall ? 130 : 160);
  const strokeWidth = swProp ?? rs(10);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(current / target, 1);
  const strokeDashoffset = circumference * (1 - progress);
  const remaining = Math.max(target - current, 0);

  return (
    <View style={styles.container}>
      <Svg width={size} height={size}>
        <Defs>
          <LinearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <Stop offset="0%" stopColor="#4ADE80" />
            <Stop offset="100%" stopColor="#22D3EE" />
          </LinearGradient>
        </Defs>
        {/* Background ring */}
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={Palette.border.subtle}
          strokeWidth={strokeWidth}
          fill="none"
        />
        {/* Progress ring */}
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="url(#ringGrad)"
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </Svg>
      <View style={[styles.centerText, { width: size, height: size }]}>
        <Text style={[styles.currentValue, { fontSize: rs(28) }]}>{current.toLocaleString()}</Text>
        <Text style={[styles.unit, { fontSize: rs(12) }]}>kcal</Text>
        <Text style={[styles.remaining, { fontSize: rs(10) }]}>剩餘 {remaining.toLocaleString()}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  centerText: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
  },
  currentValue: {
    ...Typography.hero,
    color: Palette.text.primary,
  },
  unit: {
    ...Typography.caption,
    color: Palette.text.tertiary,
    marginTop: -2,
  },
  remaining: {
    ...Typography.small,
    color: Palette.accent.green,
    marginTop: Spacing.xs,
  },
});
