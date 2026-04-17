import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { RECOMMENDED_MEALS, FILTERED_UNSAFE_MEALS } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';

export default function RecommendScreen() {
  const { rs, isSmall } = useResponsive();
  const { user, dailyNutrition } = useStore();
  const remaining = Math.max(0, Math.round(dailyNutrition.calories.target - dailyNutrition.calories.current));

  return (
    <AppContainer>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>智慧推薦</Text>
        <Text style={[styles.subtitle, { fontSize: rs(13) }]}>
          基於你的健康檔案與口味偏好，AI 為你篩選安全且美味的餐點
        </Text>
      </View>

      {/* Summary */}
      <View style={[styles.summaryCard, { padding: rs(16) }]}>
        <View style={styles.summaryRow}>
          <View style={styles.summaryItem}>
            <Text style={[styles.summaryLabel, { fontSize: rs(10) }]}>剩餘熱量</Text>
            <Text style={[styles.summaryValue, { fontSize: rs(18), color: Palette.accent.green }]}>
              {remaining} kcal
            </Text>
          </View>
          <View style={styles.summaryDivider} />
          <View style={styles.summaryItem}>
            <Text style={[styles.summaryLabel, { fontSize: rs(10) }]}>健康狀況</Text>
            <View style={styles.conditionTags}>
              {user.healthConditions.length > 0 ? user.healthConditions.map((c) => (
                <View key={c} style={styles.conditionTag}>
                  <Text style={[styles.conditionTagText, { fontSize: rs(10) }]}>{c}</Text>
                </View>
              )) : (
                <Text style={[styles.noCondText, { fontSize: rs(11) }]}>無設定</Text>
              )}
            </View>
          </View>
        </View>
        <View style={styles.filterNotice}>
          <Ionicons name="shield-checkmark" size={rs(14)} color={Palette.accent.green} />
          <Text style={[styles.filterNoticeText, { fontSize: rs(11) }]}>
            已自動排除 {FILTERED_UNSAFE_MEALS.length} 項不適合的餐點
          </Text>
        </View>
      </View>

      {/* Filtered out section */}
      <View style={[styles.filteredCard, { padding: rs(16) }]}>
        <View style={styles.filteredHeader}>
          <Ionicons name="close-circle" size={rs(16)} color={Palette.status.error} />
          <Text style={[styles.filteredTitle, { fontSize: rs(13) }]}>安全過濾層已排除</Text>
        </View>
        {FILTERED_UNSAFE_MEALS.map((item, i) => (
          <View key={i} style={[styles.filteredRow, i < FILTERED_UNSAFE_MEALS.length - 1 && styles.filteredRowBordered]}>
            <Text style={styles.filteredEmoji}>{item.icon}</Text>
            <View style={styles.filteredInfo}>
              <Text style={[styles.filteredName, { fontSize: rs(14) }]}>{item.name}</Text>
              <Text style={[styles.filteredReason, { fontSize: rs(11) }]}>{item.reason}</Text>
            </View>
          </View>
        ))}
      </View>

      {/* Recommended list */}
      <View style={styles.recHeader}>
        <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>為你推薦</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          <Ionicons name="heart" size={rs(12)} color={Palette.accent.pink} />
          <Text style={[styles.recSort, { fontSize: rs(10) }]}>口味匹配度排序</Text>
        </View>
      </View>

      {RECOMMENDED_MEALS.map((meal) => (
        <View key={meal.id} style={[styles.mealCard, { padding: rs(16) }]}>
          <View style={styles.mealTop}>
            <View style={[styles.mealEmoji, { width: rs(40), height: rs(40), borderRadius: rs(12) }]}>
              <Text style={{ fontSize: rs(20) }}>{meal.emoji}</Text>
            </View>
            <View style={styles.mealInfo}>
              <Text style={[styles.mealName, { fontSize: rs(15) }]}>{meal.name}</Text>
              <View style={styles.mealMeta}>
                <Ionicons name="restaurant-outline" size={rs(10)} color={Palette.text.tertiary} />
                <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>{meal.restaurant}</Text>
                <Ionicons name="location-outline" size={rs(10)} color={Palette.text.tertiary} />
                <Text style={[styles.mealMetaText, { fontSize: rs(10) }]}>{meal.distance}</Text>
              </View>
            </View>
            <View style={styles.scoreContainer}>
              <Text style={[styles.scoreValue, { fontSize: rs(20), color: Palette.accent.pink }]}>{meal.matchScore}</Text>
              <Text style={[styles.scoreLabel, { fontSize: rs(9) }]}>匹配</Text>
            </View>
          </View>

          <View style={styles.badgesRow}>
            {meal.safetyBadges.map((badge) => (
              <View key={badge} style={styles.safetyBadge}>
                <Ionicons name="checkmark-circle" size={rs(10)} color={Palette.accent.green} />
                <Text style={[styles.safetyBadgeText, { fontSize: rs(10) }]}>{badge}</Text>
              </View>
            ))}
          </View>

          <View style={styles.mealNutritionRow}>
            {[
              { label: '熱量', value: `${meal.calories} kcal`, color: Palette.accent.green },
              { label: '蛋白質', value: `${meal.protein} g`, color: Palette.accent.blue },
              { label: '碳水', value: `${meal.carbs} g`, color: Palette.accent.orange },
              { label: '鈉', value: `${meal.sodium} mg`, color: Palette.accent.pink },
            ].map((n) => (
              <View key={n.label} style={styles.mealNutritionItem}>
                <Text style={[styles.mealNutritionLabel, { fontSize: rs(9) }]}>{n.label}</Text>
                <Text style={[styles.mealNutritionValue, { fontSize: rs(12), color: n.color }]}>{n.value}</Text>
              </View>
            ))}
          </View>
        </View>
      ))}
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  header: { marginTop: Spacing.lg, marginBottom: Spacing.xl },
  title: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  subtitle: { ...Typography.body, color: Palette.text.tertiary, lineHeight: 22 },

  summaryCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  summaryRow: { flexDirection: 'row', marginBottom: Spacing.md },
  summaryItem: { flex: 1, alignItems: 'center' },
  summaryLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  summaryValue: { ...Typography.h2 },
  summaryDivider: { width: 1, backgroundColor: Palette.border.subtle },
  conditionTags: { flexDirection: 'row', gap: 4, flexWrap: 'wrap', justifyContent: 'center' },
  conditionTag: { backgroundColor: 'rgba(248,113,113,0.12)', paddingHorizontal: 8, paddingVertical: 2, borderRadius: Radius.sm },
  conditionTagText: { ...Typography.small, color: Palette.status.error },
  noCondText: { ...Typography.caption, color: Palette.text.tertiary },
  filterNotice: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, paddingTop: Spacing.md, borderTopWidth: 1, borderTopColor: Palette.border.subtle },
  filterNoticeText: { ...Typography.caption, color: Palette.accent.green },

  filteredCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle,
  },
  filteredHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.md },
  filteredTitle: { ...Typography.bodyBold, color: Palette.status.error },
  filteredRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, paddingVertical: Spacing.md },
  filteredRowBordered: { borderBottomWidth: 1, borderBottomColor: Palette.border.subtle },
  filteredEmoji: { fontSize: 24 },
  filteredInfo: { flex: 1 },
  filteredName: { ...Typography.bodyBold, color: Palette.text.primary, marginBottom: 2 },
  filteredReason: { ...Typography.caption, color: Palette.text.tertiary },

  recHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: Spacing.lg },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  recSort: { ...Typography.small, color: Palette.accent.pink },

  mealCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.md,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  mealTop: { flexDirection: 'row', alignItems: 'center', marginBottom: Spacing.md },
  mealEmoji: { backgroundColor: Palette.bg.elevated, alignItems: 'center', justifyContent: 'center', marginRight: Spacing.md },
  mealInfo: { flex: 1 },
  mealName: { ...Typography.bodyBold, color: Palette.text.primary, marginBottom: 4 },
  mealMeta: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  mealMetaText: { ...Typography.small, color: Palette.text.tertiary },
  scoreContainer: { alignItems: 'center' },
  scoreValue: { ...Typography.h2, fontWeight: '800' },
  scoreLabel: { ...Typography.small, color: Palette.text.tertiary },

  badgesRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, marginBottom: Spacing.md },
  safetyBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: Palette.accent.greenDim, paddingHorizontal: 8, paddingVertical: 3, borderRadius: Radius.full,
  },
  safetyBadgeText: { ...Typography.small, color: Palette.accent.green },

  mealNutritionRow: {
    flexDirection: 'row', backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, overflow: 'hidden',
  },
  mealNutritionItem: {
    flex: 1, alignItems: 'center', paddingVertical: Spacing.md,
    borderRightWidth: 1, borderRightColor: Palette.border.subtle,
  },
  mealNutritionLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  mealNutritionValue: { ...Typography.bodyBold },
});
