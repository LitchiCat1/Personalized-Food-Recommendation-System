import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';

type Props = {
  title: string;
  subtitle?: string;
  badge?: string;
  badgeTone?: 'default' | 'success' | 'warning' | 'info';
};

export default function ScreenHeader({ title, subtitle, badge, badgeTone = 'default' }: Props) {
  return (
    <View style={styles.wrap}>
      <View style={styles.copy}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {badge ? (
        <View style={[styles.badge, badgeToneStyles[badgeTone]]}>
          <Text style={styles.badgeText}>{badge}</Text>
        </View>
      ) : null}
    </View>
  );
}

const badgeToneStyles = {
  default: { backgroundColor: Palette.bg.elevated, borderColor: Palette.border.subtle },
  success: { backgroundColor: Palette.accent.greenDim, borderColor: 'rgba(31,157,114,0.18)' },
  warning: { backgroundColor: Palette.accent.orangeDim, borderColor: 'rgba(245,158,11,0.18)' },
  info: { backgroundColor: Palette.accent.blueDim, borderColor: 'rgba(47,128,237,0.18)' },
} as const;

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: Spacing.md,
    marginTop: Spacing.lg,
    marginBottom: Spacing.xl,
  },
  copy: { flex: 1, gap: Spacing.xs },
  title: { ...Typography.h1, color: Palette.text.primary },
  subtitle: { ...Typography.body, color: Palette.text.secondary },
  badge: {
    alignSelf: 'flex-start',
    borderRadius: Radius.full,
    borderWidth: 1,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.xs,
    ...Shadows.soft,
  },
  badgeText: { ...Typography.small, color: Palette.text.secondary },
});
