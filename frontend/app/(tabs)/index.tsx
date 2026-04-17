import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import CalorieRing from '@/components/dashboard/CalorieRing';
import NutrientBar from '@/components/dashboard/NutrientBar';
import MealCard from '@/components/dashboard/MealCard';
import AppContainer from '@/components/AppContainer';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 6) return '深夜了 🌙';
  if (h < 12) return '早安 ☀️';
  if (h < 14) return '午安 🌤️';
  if (h < 18) return '下午好 ☕';
  return '晚安 🌆';
}

export default function DashboardScreen() {
  const { rs, isSmall } = useResponsive();
  const { dailyNutrition, todayMeals, healthAlerts, user } = useStore();
  const { calories, protein, carbs, fat, sodium, fiber } = dailyNutrition;

  return (
    <AppContainer>
      {/* Header */}
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.greeting, { fontSize: rs(11) }]}>{getGreeting()}</Text>
          <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>今日營養追蹤</Text>
        </View>
        <View style={styles.dateBadge}>
          <Text style={[styles.dateText, { fontSize: rs(11) }]}>
            {new Date().toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', weekday: 'short' })}
          </Text>
        </View>
      </View>

      {/* Health Alerts */}
      {healthAlerts.map((alert) => (
        <View
          key={alert.id}
          style={[
            styles.alertCard,
            alert.type === 'danger' && styles.alertDanger,
            alert.type === 'warning' && styles.alertWarning,
            alert.type === 'info' && styles.alertInfo,
          ]}
        >
          <Text style={styles.alertIcon}>{alert.icon}</Text>
          <View style={styles.alertContent}>
            <Text style={[styles.alertTitle, { fontSize: rs(14) }]}>{alert.title}</Text>
            <Text style={[styles.alertMessage, { fontSize: rs(12) }]}>{alert.message}</Text>
          </View>
        </View>
      ))}

      {/* BMR/TDEE */}
      <View style={styles.tdeeCard}>
        {[
          { label: 'BMR', value: user.bmr, color: Palette.text.primary },
          { label: 'TDEE', value: user.tdee, color: Palette.accent.cyan },
          { label: '目標', value: calories.target, color: Palette.accent.green },
        ].map((item, i) => (
          <React.Fragment key={item.label}>
            {i > 0 && <View style={styles.tdeeDivider} />}
            <View style={styles.tdeeItem}>
              <Text style={[styles.tdeeLabel, { fontSize: rs(10) }]}>{item.label}</Text>
              <Text style={[styles.tdeeValue, { fontSize: rs(16), color: item.color }]}>{item.value}</Text>
              <Text style={[styles.tdeeUnit, { fontSize: rs(10) }]}>kcal</Text>
            </View>
          </React.Fragment>
        ))}
      </View>

      {/* Calorie Ring */}
      <LinearGradient
        colors={['rgba(74, 222, 128, 0.10)', 'rgba(34, 211, 238, 0.04)', 'transparent']}
        style={styles.heroCard}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
      >
        <View style={[styles.heroInner, { paddingVertical: rs(24), paddingHorizontal: rs(16) }]}>
          <CalorieRing current={Math.round(calories.current)} target={calories.target} />
          <View style={styles.heroStats}>
            {[
              { label: '目標', value: calories.target, color: Palette.text.primary },
              { label: '已攝取', value: Math.round(calories.current), color: Palette.accent.green },
              { label: '剩餘', value: Math.max(0, Math.round(calories.target - calories.current)), color: Palette.accent.cyan },
            ].map((s, i) => (
              <React.Fragment key={s.label}>
                {i > 0 && <View style={styles.heroStatDivider} />}
                <View style={styles.heroStatItem}>
                  <Text style={[styles.heroStatLabel, { fontSize: rs(10) }]}>{s.label}</Text>
                  <Text style={[styles.heroStatValue, { fontSize: rs(18), color: s.color }]}>
                    {s.value.toLocaleString()}
                  </Text>
                  <Text style={[styles.heroStatUnit, { fontSize: rs(10) }]}>kcal</Text>
                </View>
              </React.Fragment>
            ))}
          </View>
        </View>
      </LinearGradient>

      {/* Nutrients */}
      <View style={styles.sectionCard}>
        <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>營養素分佈</Text>
        <NutrientBar label={protein.label} current={protein.current} target={protein.target} unit={protein.unit} color={protein.color} />
        <NutrientBar label={carbs.label} current={carbs.current} target={carbs.target} unit={carbs.unit} color={carbs.color} />
        <NutrientBar label={fat.label} current={fat.current} target={fat.target} unit={fat.unit} color={fat.color} />
        <NutrientBar label={sodium.label} current={sodium.current} target={sodium.target} unit={sodium.unit} color={sodium.color} />
        <NutrientBar label={fiber.label} current={fiber.current} target={fiber.target} unit={fiber.unit} color={fiber.color} />
      </View>

      {/* Meals */}
      <View style={styles.mealsHeader}>
        <Text style={[styles.sectionTitle, { fontSize: rs(16), marginBottom: 0 }]}>今日餐點</Text>
        <View style={styles.mealCountBadge}>
          <Text style={[styles.mealCountText, { fontSize: rs(11) }]}>{todayMeals.length} 筆</Text>
        </View>
      </View>

      {todayMeals.map((meal) => (
        <MealCard key={meal.id} meal={meal} />
      ))}
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'flex-start', marginTop: Spacing.lg, marginBottom: Spacing.lg,
  },
  greeting: { ...Typography.caption, color: Palette.text.tertiary, marginBottom: Spacing.xs },
  title: { ...Typography.h1, color: Palette.text.primary },
  dateBadge: {
    backgroundColor: Palette.bg.card, paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm,
    borderRadius: Radius.md, borderWidth: 1, borderColor: Palette.border.subtle,
  },
  dateText: { ...Typography.caption, color: Palette.text.secondary },

  alertCard: {
    flexDirection: 'row', alignItems: 'flex-start', backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg, padding: Spacing.lg, marginBottom: Spacing.md,
    borderWidth: 1, borderColor: Palette.border.subtle, gap: Spacing.md,
  },
  alertDanger: { borderColor: 'rgba(248,113,113,0.3)', backgroundColor: 'rgba(248,113,113,0.06)' },
  alertWarning: { borderColor: 'rgba(251,191,36,0.3)', backgroundColor: 'rgba(251,191,36,0.06)' },
  alertInfo: { borderColor: 'rgba(96,165,250,0.2)', backgroundColor: 'rgba(96,165,250,0.04)' },
  alertIcon: { fontSize: 20, marginTop: 2 },
  alertContent: { flex: 1 },
  alertTitle: { ...Typography.bodyBold, color: Palette.text.primary, marginBottom: 4 },
  alertMessage: { ...Typography.caption, color: Palette.text.secondary, lineHeight: 20 },

  tdeeCard: {
    flexDirection: 'row', backgroundColor: Palette.bg.card, borderRadius: Radius.lg,
    padding: Spacing.lg, marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle,
  },
  tdeeItem: { flex: 1, alignItems: 'center' },
  tdeeLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  tdeeValue: { ...Typography.h3, color: Palette.text.primary },
  tdeeUnit: { ...Typography.small, color: Palette.text.tertiary },
  tdeeDivider: { width: 1, backgroundColor: Palette.border.subtle },

  heroCard: {
    borderRadius: Radius.xl, borderWidth: 1, borderColor: Palette.border.subtle,
    marginBottom: Spacing.xl, ...Shadows.card,
  },
  heroInner: { alignItems: 'center' },
  heroStats: {
    flexDirection: 'row', justifyContent: 'space-around', width: '100%',
    marginTop: Spacing['2xl'], paddingTop: Spacing.xl, borderTopWidth: 1, borderTopColor: Palette.border.subtle,
  },
  heroStatItem: { alignItems: 'center', flex: 1 },
  heroStatLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: Spacing.xs },
  heroStatValue: { ...Typography.h2, color: Palette.text.primary },
  heroStatUnit: { ...Typography.small, color: Palette.text.tertiary, marginTop: -2 },
  heroStatDivider: { width: 1, backgroundColor: Palette.border.subtle },

  sectionCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, padding: Spacing.xl,
    marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary, marginBottom: Spacing.lg },

  mealsHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg,
  },
  mealCountBadge: {
    backgroundColor: Palette.accent.greenDim, paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.xs, borderRadius: Radius.full,
  },
  mealCountText: { ...Typography.small, color: Palette.accent.green },
});
