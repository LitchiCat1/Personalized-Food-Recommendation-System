import React from 'react';
import { Pressable, Text, StyleSheet, View } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';

type Props = {
  label: string;
  onPress?: () => void;
  icon?: React.ReactNode;
  active?: boolean;
};

export default function SecondaryButton({ label, onPress, icon, active }: Props) {
  const scale = useSharedValue(1);
  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const setPressed = (pressed: boolean) => {
    scale.value = withTiming(pressed ? 0.98 : 1, {
      duration: pressed ? 90 : 160,
      easing: Easing.out(Easing.cubic),
    });
  };

  return (
    <Animated.View style={animatedStyle}>
      <Pressable
        onPress={onPress}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        style={({ pressed }) => [styles.button, active && styles.active, pressed && { opacity: 0.86 }]}
      >
        <View style={styles.content}>
          {icon}
          <Text style={[styles.label, active && styles.activeLabel]}>{label}</Text>
        </View>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 44,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.card,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
  },
  active: {
    borderColor: 'rgba(31,157,114,0.24)',
    backgroundColor: Palette.accent.greenDim,
  },
  content: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  label: { ...Typography.bodyBold, color: Palette.text.secondary },
  activeLabel: { color: Palette.accent.green },
});
