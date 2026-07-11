import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';

type Props = {
  label: string;
  current: number;
  target: number;
  unit: string;
  color: string;
};

export default function ProgressBar({ label, current, target, unit, color }: Props) {
  const progress = Math.min(current / Math.max(target, 1), 1);
  const width = useSharedValue(0);

  React.useEffect(() => {
    width.value = withTiming(progress, {
      duration: 520,
      easing: Easing.out(Easing.cubic),
    });
  }, [progress, width]);

  const fillStyle = useAnimatedStyle(() => ({
    width: `${width.value * 100}%`,
  }));

  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.values}>
          <Text style={{ color }}>{Math.round(current)}</Text>
          <Text> / {target}{unit}</Text>
        </Text>
      </View>
      <View style={[styles.track, { backgroundColor: `${color}22` }]}>
        <Animated.View style={[styles.fill, { backgroundColor: color }, fillStyle]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: Spacing.xs + 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  label: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  values: { ...Typography.caption, color: Palette.text.secondary },
  track: { height: 8, borderRadius: Radius.full, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.full },
});
