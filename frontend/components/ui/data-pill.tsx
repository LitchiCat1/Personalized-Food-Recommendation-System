import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Palette, Typography, Spacing, Radius } from '@/constants/theme';

type Props = {
  children: React.ReactNode;
  tone?: 'default' | 'success' | 'warning' | 'info' | 'danger';
};

export default function DataPill({ children, tone = 'default' }: Props) {
  return (
    <View style={[styles.base, toneStyles[tone]]}>
      <Text style={[styles.text, toneTextStyles[tone]]}>{children}</Text>
    </View>
  );
}

const toneStyles = {
  default: { backgroundColor: Palette.bg.elevated, borderColor: Palette.border.subtle },
  success: { backgroundColor: Palette.accent.greenDim, borderColor: 'rgba(31,157,114,0.18)' },
  warning: { backgroundColor: Palette.accent.orangeDim, borderColor: 'rgba(245,158,11,0.18)' },
  info: { backgroundColor: Palette.accent.blueDim, borderColor: 'rgba(47,128,237,0.18)' },
  danger: { backgroundColor: 'rgba(226,85,85,0.10)', borderColor: 'rgba(226,85,85,0.18)' },
} as const;

const toneTextStyles = {
  default: { color: Palette.text.secondary },
  success: { color: Palette.accent.green },
  warning: { color: Palette.accent.orange },
  info: { color: Palette.accent.blue },
  danger: { color: Palette.status.error },
} as const;

const styles = StyleSheet.create({
  base: {
    alignSelf: 'flex-start',
    borderRadius: Radius.full,
    borderWidth: 1,
    paddingHorizontal: Spacing.md,
    paddingVertical: 4,
  },
  text: { ...Typography.small },
});
