import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';

type Props = {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
};

export default function SectionBlock({ title, subtitle, children }: Props) {
  return (
    <View style={styles.card}>
      {title || subtitle ? (
        <View style={styles.header}>
          {title ? <Text style={styles.title}>{title}</Text> : null}
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
      ) : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.xl,
    marginBottom: Spacing.xl,
    ...Shadows.card,
  },
  header: { gap: Spacing.xs, marginBottom: Spacing.lg },
  title: { ...Typography.h3, color: Palette.text.primary },
  subtitle: { ...Typography.caption, color: Palette.text.secondary },
});
