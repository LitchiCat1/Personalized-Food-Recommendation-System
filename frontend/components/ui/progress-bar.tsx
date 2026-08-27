import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';

type Props = {
  label: string;
  current: number;
  target: number;
  unit: string;
  color: string;
  attentionLabel?: string;
};

export default function ProgressBar({ label, current, target, unit, color, attentionLabel }: Props) {
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
    <View style={[styles.wrap, attentionLabel && styles.attentionWrap]}>
      <View style={styles.row}>
        <Text style={[styles.label, attentionLabel && styles.attentionNutrientLabel]}>{label}</Text>
        <Text style={styles.values}>
          <Text style={{ color }}>{current % 1 !== 0 ? (Math.round(current * 10) / 10) : current}</Text>
          <Text> / {target}{unit}</Text>
        </Text>
      </View>
      {attentionLabel ? (
        <View style={styles.attentionRow}>
          <Ionicons name="warning-outline" size={15} color={Palette.status.warning} />
          <Text style={styles.attentionText}>{attentionLabel}</Text>
        </View>
      ) : null}
      <View style={[styles.track, { backgroundColor: `${color}22` }]}>
        <Animated.View style={[styles.fill, { backgroundColor: color }, fillStyle]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: Spacing.xs + 2 },
  attentionWrap: {
    borderLeftWidth: 3,
    borderLeftColor: Palette.status.warning,
    backgroundColor: Palette.accent.orangeDim,
    paddingLeft: Spacing.md,
    paddingVertical: Spacing.xs,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  label: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  attentionNutrientLabel: { color: Palette.text.primary, fontWeight: '700' },
  values: { ...Typography.caption, color: Palette.text.secondary },
  attentionRow: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xs },
  attentionText: { ...Typography.small, color: Palette.status.warning, flex: 1 },
  track: { height: 8, borderRadius: Radius.full, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.full },
});
