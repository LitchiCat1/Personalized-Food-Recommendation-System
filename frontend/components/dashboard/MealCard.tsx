import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import type { MealEntry } from '@/constants/mock-data';

type Props = {
  meal: MealEntry;
};

export default function MealCard({ meal }: Props) {
  return (
    <Pressable style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}>
      {/* Emoji thumbnail */}
      <View style={styles.emojiContainer}>
        <Text style={styles.emoji}>{meal.emoji}</Text>
      </View>

      {/* Info */}
      <View style={styles.info}>
        <Text style={styles.name} numberOfLines={1}>{meal.name}</Text>
        <View style={styles.metaRow}>
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{meal.mealType}</Text>
          </View>
          <Text style={styles.time}>{meal.time}</Text>
        </View>
      </View>

      {/* Calories */}
      <View style={styles.calorieContainer}>
        <Text style={styles.calorieValue}>{meal.calories}</Text>
        <Text style={styles.calorieUnit}>kcal</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg,
    padding: Spacing.lg,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.card,
  },
  cardPressed: {
    backgroundColor: Palette.bg.cardHover,
    transform: [{ scale: 0.98 }],
  },
  emojiContainer: {
    width: 48,
    height: 48,
    borderRadius: Radius.md,
    backgroundColor: Palette.bg.elevated,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Spacing.md,
  },
  emoji: {
    fontSize: 24,
  },
  info: {
    flex: 1,
    marginRight: Spacing.sm,
  },
  name: {
    ...Typography.bodyBold,
    color: Palette.text.primary,
    marginBottom: Spacing.xs,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  badge: {
    backgroundColor: Palette.accent.greenDim,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: Radius.sm,
  },
  badgeText: {
    ...Typography.small,
    color: Palette.accent.green,
  },
  time: {
    ...Typography.small,
    color: Palette.text.tertiary,
  },
  calorieContainer: {
    alignItems: 'flex-end',
  },
  calorieValue: {
    ...Typography.h3,
    color: Palette.text.primary,
  },
  calorieUnit: {
    ...Typography.small,
    color: Palette.text.tertiary,
    marginTop: -2,
  },
});
