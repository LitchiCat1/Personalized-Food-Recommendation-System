import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';

export type NutrientGoalType = 'upper_limit' | 'minimum_target';

type Props = {
  label: string;
  current: number;
  target: number;
  unit: string;
  color: string;
  attentionLabel?: string;
  /**
   * 這個營養素的目標方向。給了才會依超標狀態換色——之前只有鈉在呼叫端
   * 自己判斷，碳水／糖／脂肪超標時進度條滿了但顏色不變，看不出來。
   * 不給則維持呼叫端指定的顏色。
   */
  goalType?: NutrientGoalType;
};

/** 反式脂肪這種小數值營養素，四捨五入到整數會把 0.5g 顯示成 0。 */
function formatAmount(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  if (Math.abs(safe) < 10 && !Number.isInteger(safe)) return safe.toFixed(1);
  return String(Math.round(safe));
}

export default function ProgressBar({ label, current, target, unit, color, attentionLabel, goalType }: Props) {
  const progress = target <= 0 ? (current > 0 ? 1 : 0) : Math.min(current / target, 1);
  // 目標為 0 的營養素（反式脂肪）只要吃到就是超標。
  const isOver = target <= 0 ? current > 0 : current > target;
  const isNearLimit = target > 0 && current >= target * 0.8;
  const fillColor = goalType !== 'upper_limit'
    ? color
    : isOver
      ? Palette.status.error
      : isNearLimit
        ? Palette.status.warning
        : color;
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
          <Text style={{ color: fillColor }}>{formatAmount(current)}</Text>
          {/* 目標 0 顯示成「0 / 0 g」讀不出任何訊息，改成講清楚上限是 0。 */}
          <Text>{target <= 0 ? `${unit}（上限 0）` : ` / ${formatAmount(target)}${unit}`}</Text>
        </Text>
      </View>
      {attentionLabel ? (
        <View style={styles.attentionRow}>
          <Ionicons name="warning-outline" size={15} color={Palette.status.warning} />
          <Text style={styles.attentionText}>{attentionLabel}</Text>
        </View>
      ) : null}
      <View style={[styles.track, { backgroundColor: `${color}22` }]}>
        <Animated.View style={[styles.fill, { backgroundColor: fillColor }, fillStyle]} />
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
  values: { ...Typography.caption, ...Typography.number, color: Palette.text.secondary },
  attentionRow: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xs },
  attentionText: { ...Typography.small, color: Palette.status.warning, flex: 1 },
  track: { height: 8, borderRadius: Radius.full, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: Radius.full },
});
