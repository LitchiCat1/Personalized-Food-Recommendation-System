import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { Palette, Typography, Radius } from '@/constants/theme';

type Option = {
  label: string;
  value: string;
};

type Props = {
  options: Option[];
  value: string;
  onChange: (value: string) => void;
};

export default function SegmentedControl({ options, value, onChange }: Props) {
  return (
    <View style={styles.wrap}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Segment key={option.value} label={option.label} active={active} onPress={() => onChange(option.value)} />
        );
      })}
    </View>
  );
}

function Segment({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  const scale = useSharedValue(active ? 1 : 0.98);
  const opacity = useSharedValue(active ? 1 : 0.78);

  React.useEffect(() => {
    scale.value = withTiming(active ? 1 : 0.98, { duration: 180, easing: Easing.out(Easing.cubic) });
    opacity.value = withTiming(active ? 1 : 0.78, { duration: 180 });
  }, [active, opacity, scale]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ scale: scale.value }],
  }));

  return (
    <Pressable onPress={onPress} style={styles.segment}>
      <Animated.View style={[styles.segmentInner, active && styles.active, animatedStyle]}>
        <Text style={[styles.label, active && styles.activeLabel]}>{label}</Text>
      </Animated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.full,
    padding: 4,
    gap: 4,
  },
  segment: {
    flex: 1,
    minHeight: 40,
  },
  segmentInner: {
    minHeight: 40,
    borderRadius: Radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  active: { backgroundColor: Palette.bg.card, borderWidth: 1, borderColor: Palette.border.subtle },
  label: { ...Typography.small, color: Palette.text.secondary },
  activeLabel: { color: Palette.text.primary },
});
