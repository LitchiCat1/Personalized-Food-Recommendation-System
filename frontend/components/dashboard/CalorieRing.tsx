import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import Animated, { Easing, useAnimatedProps, useSharedValue, withTiming } from 'react-native-reanimated';
import { Palette, Typography, Spacing } from '@/constants/theme';
import { useResponsive } from '@/hooks/useResponsive';

type Props = {
  current: number;
  target: number;
  size?: number;
  strokeWidth?: number;
};

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

export default function CalorieRing({ current, target, size: sizeProp, strokeWidth: swProp }: Props) {
  const { rs, isSmall } = useResponsive();
  const size = sizeProp ?? rs(isSmall ? 126 : 146);
  const strokeWidth = swProp ?? rs(9);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(current / Math.max(target, 1), 1);
  const animatedProgress = useSharedValue(0);
  const remaining = Math.max(target - current, 0);

  React.useEffect(() => {
    animatedProgress.value = withTiming(progress, {
      duration: 720,
      easing: Easing.out(Easing.cubic),
    });
  }, [animatedProgress, progress]);

  const animatedProps = useAnimatedProps(() => ({
    strokeDashoffset: circumference * (1 - animatedProgress.value),
  }));

  return (
    <View style={styles.container}>
      <Svg width={size} height={size}>
        <Circle cx={size / 2} cy={size / 2} r={radius} stroke={Palette.bg.elevated} strokeWidth={strokeWidth} fill="none" />
        <AnimatedCircle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={current > target ? Palette.status.warning : Palette.accent.green}
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          animatedProps={animatedProps}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </Svg>
      <View style={[styles.centerText, { width: size, height: size }]}>
        <Text style={[styles.currentValue, { fontSize: rs(26) }]}>{current.toLocaleString()}</Text>
        <Text style={[styles.unit, { fontSize: rs(11) }]}>kcal eaten</Text>
        <Text style={[styles.remaining, { fontSize: rs(11) }]}>剩餘 {remaining.toLocaleString()}</Text>
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
    ...Typography.small,
    color: Palette.text.tertiary,
    marginTop: -2,
  },
  remaining: {
    ...Typography.small,
    color: Palette.accent.green,
    marginTop: Spacing.xs,
  },
});
