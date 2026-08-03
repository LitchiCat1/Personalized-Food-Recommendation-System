import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Radius, Spacing, Typography } from '@/constants/theme';

type FeedbackTone = 'success' | 'error';

type Props = {
  tone: FeedbackTone;
  title: string;
  message?: string;
  onDismiss?: () => void;
};

const toneConfig = {
  success: {
    icon: 'checkmark-circle' as const,
    color: Palette.status.success,
    backgroundColor: Palette.accent.greenDim,
    borderColor: 'rgba(31,157,114,0.24)',
  },
  error: {
    icon: 'alert-circle' as const,
    color: Palette.status.error,
    backgroundColor: Palette.accent.pinkDim,
    borderColor: 'rgba(226,85,85,0.24)',
  },
};

export default function FeedbackBanner({ tone, title, message, onDismiss }: Props) {
  const config = toneConfig[tone];

  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[
        styles.banner,
        { backgroundColor: config.backgroundColor, borderColor: config.borderColor },
      ]}
    >
      <Ionicons name={config.icon} size={20} color={config.color} />
      <View style={styles.copy}>
        <Text style={[styles.title, { color: config.color }]}>{title}</Text>
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </View>
      {onDismiss ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="關閉訊息"
          hitSlop={4}
          onPress={onDismiss}
          style={({ pressed }) => [styles.dismissButton, pressed && styles.dismissButtonPressed]}
        >
          <Ionicons name="close" size={19} color={Palette.text.secondary} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    borderWidth: 1,
    borderRadius: Radius.lg,
    paddingLeft: Spacing.md,
    paddingVertical: Spacing.sm,
    paddingRight: Spacing.xs,
    marginBottom: Spacing.lg,
  },
  copy: { flex: 1, minWidth: 0, gap: 2, paddingVertical: Spacing.xs },
  title: { ...Typography.bodyBold },
  message: { ...Typography.caption, color: Palette.text.secondary },
  dismissButton: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Radius.full,
  },
  dismissButtonPressed: { backgroundColor: Palette.bg.cardHover },
});
