import React, { useRef } from 'react';
import { Pressable, Text, StyleSheet, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';

type Props = {
  label: string;
  onPress?: () => void;
  tone?: 'green' | 'blue' | 'ghost';
  icon?: React.ReactNode;
  disabled?: boolean;
  fullWidth?: boolean;
};

export default function PrimaryButton({ label, onPress, tone = 'green', icon, disabled, fullWidth = true }: Props) {
  const scale = useSharedValue(1);
  const pressOutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const setPressed = (pressed: boolean) => {
    if (pressOutTimer.current) {
      clearTimeout(pressOutTimer.current);
      pressOutTimer.current = null;
    }
    scale.value = withTiming(pressed ? 0.97 : 1, {
      duration: pressed ? 90 : 180,
      easing: Easing.out(Easing.cubic),
    });
  };

  const content = (
    <View style={styles.content}>
      {icon}
      <Text style={[styles.label, tone === 'ghost' && styles.ghostLabel]}>{label}</Text>
    </View>
  );

  return (
    <Animated.View style={[fullWidth && styles.fullWidth, animatedStyle]}>
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled: Boolean(disabled) }}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        disabled={disabled}
        style={({ pressed }) => [fullWidth && styles.fullWidth, pressed && { opacity: 0.92 }, disabled && { opacity: 0.6 }]}
      >
        {tone === 'ghost' ? (
          <View style={[styles.ghost, fullWidth && styles.fullWidth]}>
            {content}
          </View>
        ) : (
          <LinearGradient colors={tone === 'blue' ? ['#2F80ED', '#1496A6'] : ['#1F9D72', '#1496A6']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[styles.button, fullWidth && styles.fullWidth]}>
            {content}
          </LinearGradient>
        )}
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  fullWidth: { width: '100%' },
  button: {
    minHeight: 48,
    borderRadius: Radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
    ...Shadows.card,
  },
  ghost: {
    minHeight: 48,
    borderRadius: Radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
    backgroundColor: Palette.bg.card,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  content: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  label: { ...Typography.bodyBold, color: Palette.text.inverse },
  ghostLabel: { color: Palette.text.primary },
});
