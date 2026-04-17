import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { AVAILABLE_CONDITIONS, AVAILABLE_ALLERGENS, DIET_GOALS } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';

export default function ProfileScreen() {
  const { rs, isSmall, gridCol2 } = useResponsive();
  const { user, toggleCondition, toggleAllergen } = useStore();

  return (
    <AppContainer>
      {/* Profile Header */}
      <View style={styles.profileHeader}>
        <LinearGradient
          colors={['rgba(167, 139, 250, 0.15)', 'rgba(244, 114, 182, 0.08)', 'transparent']}
          style={[styles.avatarGlow, { width: rs(110), height: rs(110), borderRadius: rs(55) }]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
        >
          <View style={styles.avatarContainer}>
            <View style={[styles.avatar, { width: rs(88), height: rs(88), borderRadius: rs(44) }]}>
              <Text style={[styles.avatarEmoji, { fontSize: rs(36) }]}>👤</Text>
            </View>
            <View style={[styles.avatarBadge, { width: rs(26), height: rs(26), borderRadius: rs(13) }]}>
              <Ionicons name="camera" size={rs(11)} color={Palette.text.primary} />
            </View>
          </View>
        </LinearGradient>

        <Text style={[styles.userName, { fontSize: rs(isSmall ? 22 : 26) }]}>{user.name}</Text>
        <Text style={[styles.userEmail, { fontSize: rs(13) }]}>{user.email}</Text>

        <View style={styles.streakRow}>
          <View style={styles.streakBadge}>
            <Text style={styles.streakEmoji}>🔥</Text>
            <Text style={[styles.streakText, { fontSize: rs(11) }]}>連續 {user.streak} 天</Text>
          </View>
          <View style={styles.streakBadge}>
            <Text style={styles.streakEmoji}>📊</Text>
            <Text style={[styles.streakText, { fontSize: rs(11) }]}>共 {user.totalMeals} 餐</Text>
          </View>
        </View>
      </View>

      {/* BMR/TDEE */}
      <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>代謝數據</Text>
      <View style={[styles.metabolismCard, { padding: rs(20) }]}>
        <View style={styles.metabRow}>
          <View style={styles.metabItem}>
            <Text style={[styles.metabLabel, { fontSize: rs(10) }]}>BMR</Text>
            <Text style={[styles.metabValue, { fontSize: rs(22), color: Palette.accent.blue }]}>{user.bmr}</Text>
            <Text style={[styles.metabUnit, { fontSize: rs(10) }]}>kcal/日</Text>
          </View>
          <View style={styles.metabDivider} />
          <View style={styles.metabItem}>
            <Text style={[styles.metabLabel, { fontSize: rs(10) }]}>TDEE</Text>
            <Text style={[styles.metabValue, { fontSize: rs(22), color: Palette.accent.cyan }]}>{user.tdee}</Text>
            <Text style={[styles.metabUnit, { fontSize: rs(10) }]}>kcal/日</Text>
          </View>
        </View>
        <View style={styles.metabFormula}>
          <Ionicons name="calculator-outline" size={rs(13)} color={Palette.text.tertiary} />
          <Text style={[styles.metabFormulaText, { fontSize: rs(10) }]}>
            Mifflin-St Jeor · {user.gender === 'male' ? '男性' : '女性'} · 活動量 ×{user.activityMultiplier}
          </Text>
        </View>
      </View>

      {/* Body Stats Grid */}
      <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>身體數據</Text>
      <View style={styles.statsGrid}>
        {[
          { label: '身高', value: `${user.height}`, unit: 'cm', icon: '📏', color: Palette.accent.blue },
          { label: '體重', value: `${user.weight}`, unit: 'kg', icon: '⚖️', color: Palette.accent.orange },
          { label: 'BMI', value: `${user.bmi}`, unit: '', icon: '💪', color: Palette.accent.green },
          { label: '年齡', value: `${user.age}`, unit: '歲', icon: '🎂', color: Palette.accent.purple },
        ].map((stat) => (
          <View key={stat.label} style={[styles.statCard, { width: gridCol2(Spacing.md), padding: rs(14) }]}>
            <View style={[styles.statIconBg, { backgroundColor: stat.color + '18', width: rs(32), height: rs(32), borderRadius: rs(8) }]}>
              <Text style={{ fontSize: rs(16) }}>{stat.icon}</Text>
            </View>
            <Text style={[styles.statLabel, { fontSize: rs(10) }]}>{stat.label}</Text>
            <View style={styles.statValueRow}>
              <Text style={[styles.statValue, { fontSize: rs(20), color: stat.color }]}>{stat.value}</Text>
              {stat.unit ? <Text style={[styles.statUnit, { fontSize: rs(11) }]}> {stat.unit}</Text> : null}
            </View>
          </View>
        ))}
      </View>

      {/* Gender + Activity */}
      <View style={styles.infoRow}>
        <View style={[styles.infoCard, { padding: rs(14) }]}>
          <Ionicons name={user.gender === 'male' ? 'male' : 'female'} size={rs(18)}
            color={user.gender === 'male' ? Palette.accent.blue : Palette.accent.pink} />
          <Text style={[styles.infoLabel, { fontSize: rs(10) }]}>性別</Text>
          <Text style={[styles.infoValue, { fontSize: rs(14) }]}>{user.gender === 'male' ? '男性' : '女性'}</Text>
        </View>
        <View style={[styles.infoCard, { padding: rs(14) }]}>
          <Ionicons name="walk-outline" size={rs(18)} color={Palette.accent.cyan} />
          <Text style={[styles.infoLabel, { fontSize: rs(10) }]}>活動量</Text>
          <Text style={[styles.infoValue, { fontSize: rs(isSmall ? 11 : 14) }]}>{user.activityLevel}</Text>
        </View>
      </View>

      {/* Disease Conditions */}
      <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>健康狀況管理</Text>
      <View style={[styles.conditionsCard, { padding: rs(16) }]}>
        <View style={styles.conditionsHeader}>
          <Ionicons name="shield-checkmark" size={rs(14)} color={Palette.accent.orange} />
          <Text style={[styles.conditionsSubtitle, { fontSize: rs(11) }]}>點擊切換疾病配置，影響推薦過濾規則</Text>
        </View>
        <View style={styles.conditionsGrid}>
          {AVAILABLE_CONDITIONS.map((cond) => {
            const isActive = user.healthConditions.includes(cond.label);
            return (
              <Pressable
                key={cond.id}
                onPress={() => toggleCondition(cond.label)}
                style={({ pressed }) => [
                  styles.conditionChip,
                  { padding: rs(14) },
                  isActive && { backgroundColor: cond.color + '20', borderColor: cond.color + '40' },
                  pressed && { opacity: 0.8 },
                ]}
              >
                <Text style={{ fontSize: rs(20) }}>{cond.icon}</Text>
                <View style={styles.conditionInfo}>
                  <Text style={[styles.conditionLabel, { fontSize: rs(14) }, isActive && { color: cond.color }]}>
                    {cond.label}
                  </Text>
                  <Text style={[styles.conditionDesc, { fontSize: rs(10) }]}>{cond.description}</Text>
                </View>
                <View style={[
                  styles.conditionToggle,
                  { width: rs(26), height: rs(26), borderRadius: rs(13) },
                  isActive && { backgroundColor: cond.color, borderColor: cond.color },
                ]}>
                  <Ionicons
                    name={isActive ? 'checkmark' : 'add'}
                    size={rs(13)}
                    color={isActive ? '#fff' : Palette.text.tertiary}
                  />
                </View>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Allergens */}
      <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>過敏原設定</Text>
      <View style={[styles.allergensCard, { padding: rs(16) }]}>
        <View style={styles.allergensHeader}>
          <Ionicons name="alert-circle" size={rs(14)} color={Palette.status.warning} />
          <Text style={[styles.allergensSubtitle, { fontSize: rs(11) }]}>標記的過敏原將從推薦中自動排除</Text>
        </View>
        <View style={styles.allergenChipsWrap}>
          {AVAILABLE_ALLERGENS.map((allergen) => {
            const isActive = user.allergens.includes(allergen);
            return (
              <Pressable
                key={allergen}
                onPress={() => toggleAllergen(allergen)}
                style={({ pressed }) => [
                  styles.allergenChip,
                  { paddingHorizontal: rs(12), paddingVertical: rs(6) },
                  isActive && styles.allergenChipActive,
                  pressed && { opacity: 0.7 },
                ]}
              >
                <Text style={[styles.allergenChipText, { fontSize: rs(12) }, isActive && styles.allergenChipTextActive]}>
                  {allergen}
                </Text>
                {isActive && <Ionicons name="close-circle" size={rs(13)} color={Palette.status.error} />}
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Diet Goals */}
      <Text style={[styles.sectionTitle, { fontSize: rs(16) }]}>飲食目標設定</Text>
      <View style={styles.goalsContainer}>
        {DIET_GOALS.map((goal) => (
          <Pressable
            key={goal.id}
            style={({ pressed }) => [styles.goalItem, { padding: rs(14) }, pressed && styles.goalItemPressed]}
          >
            <View style={[styles.goalIconBg, { backgroundColor: goal.color + '18', width: rs(36), height: rs(36), borderRadius: rs(10) }]}>
              <Text style={{ fontSize: rs(16) }}>{goal.icon}</Text>
            </View>
            <View style={styles.goalInfo}>
              <Text style={[styles.goalLabel, { fontSize: rs(11) }]}>{goal.label}</Text>
              <Text style={[styles.goalValue, { fontSize: rs(14), color: goal.color }]}>{goal.value}</Text>
            </View>
            <Ionicons name="chevron-forward" size={rs(16)} color={Palette.text.tertiary} />
          </Pressable>
        ))}
      </View>

      {/* Settings */}
      <Pressable style={({ pressed }) => [styles.settingsButton, { padding: rs(14) }, pressed && { opacity: 0.7 }]}>
        <Ionicons name="settings-outline" size={rs(18)} color={Palette.text.secondary} />
        <Text style={[styles.settingsText, { fontSize: rs(14) }]}>應用程式設定</Text>
        <Ionicons name="chevron-forward" size={rs(16)} color={Palette.text.tertiary} />
      </Pressable>
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  profileHeader: { alignItems: 'center', marginTop: Spacing.xl, marginBottom: Spacing['2xl'] },
  avatarGlow: { alignItems: 'center', justifyContent: 'center', marginBottom: Spacing.lg },
  avatarContainer: { position: 'relative' },
  avatar: {
    backgroundColor: Palette.bg.card, borderWidth: 2, borderColor: Palette.accent.purple,
    alignItems: 'center', justifyContent: 'center',
  },
  avatarEmoji: {},
  avatarBadge: {
    position: 'absolute', bottom: 2, right: 2,
    backgroundColor: Palette.accent.purple, alignItems: 'center', justifyContent: 'center',
    borderWidth: 2, borderColor: Palette.bg.primary,
  },
  userName: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  userEmail: { ...Typography.body, color: Palette.text.tertiary, marginBottom: Spacing.lg },
  streakRow: { flexDirection: 'row', gap: Spacing.md },
  streakBadge: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: Palette.bg.card, paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm,
    borderRadius: Radius.full, borderWidth: 1, borderColor: Palette.border.subtle, gap: Spacing.xs,
  },
  streakEmoji: { fontSize: 14 },
  streakText: { ...Typography.caption, color: Palette.text.secondary },

  sectionTitle: { ...Typography.h3, color: Palette.text.primary, marginBottom: Spacing.lg },

  metabolismCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  metabRow: { flexDirection: 'row', marginBottom: Spacing.lg },
  metabItem: { flex: 1, alignItems: 'center' },
  metabLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: Spacing.xs },
  metabValue: { ...Typography.h1 },
  metabUnit: { ...Typography.small, color: Palette.text.tertiary, marginTop: 2 },
  metabDivider: { width: 1, backgroundColor: Palette.border.subtle },
  metabFormula: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.xs,
    paddingTop: Spacing.md, borderTopWidth: 1, borderTopColor: Palette.border.subtle,
  },
  metabFormulaText: { ...Typography.small, color: Palette.text.tertiary },

  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.md, marginBottom: Spacing.xl },
  statCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  statIconBg: { alignItems: 'center', justifyContent: 'center', marginBottom: Spacing.md },
  statLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: Spacing.xs },
  statValueRow: { flexDirection: 'row', alignItems: 'baseline' },
  statValue: { ...Typography.h2 },
  statUnit: { ...Typography.caption, color: Palette.text.tertiary },

  infoRow: { flexDirection: 'row', gap: Spacing.md, marginBottom: Spacing['2xl'] },
  infoCard: {
    flex: 1, flexDirection: 'row', alignItems: 'center',
    backgroundColor: Palette.bg.card, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Palette.border.subtle, gap: Spacing.sm,
  },
  infoLabel: { ...Typography.small, color: Palette.text.tertiary },
  infoValue: { ...Typography.bodyBold, color: Palette.text.primary, flex: 1, textAlign: 'right' },

  conditionsCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  conditionsHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.lg },
  conditionsSubtitle: { ...Typography.small, color: Palette.text.tertiary, flex: 1 },
  conditionsGrid: { gap: Spacing.md },
  conditionChip: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.md,
    backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Palette.border.subtle,
  },
  conditionInfo: { flex: 1 },
  conditionLabel: { ...Typography.bodyBold, color: Palette.text.secondary, marginBottom: 2 },
  conditionDesc: { ...Typography.small, color: Palette.text.tertiary },
  conditionToggle: {
    backgroundColor: Palette.bg.card, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: Palette.border.subtle,
  },

  allergensCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    marginBottom: Spacing.xl, borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  allergensHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.lg },
  allergensSubtitle: { ...Typography.small, color: Palette.text.tertiary, flex: 1 },
  allergenChipsWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  allergenChip: {
    borderRadius: Radius.full, backgroundColor: Palette.bg.elevated,
    borderWidth: 1, borderColor: Palette.border.subtle,
    flexDirection: 'row', alignItems: 'center', gap: Spacing.xs,
  },
  allergenChipActive: { backgroundColor: 'rgba(248, 113, 113, 0.10)', borderColor: 'rgba(248, 113, 113, 0.30)' },
  allergenChipText: { ...Typography.caption, color: Palette.text.secondary },
  allergenChipTextActive: { color: Palette.status.error },

  goalsContainer: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, overflow: 'hidden', marginBottom: Spacing.xl, ...Shadows.card,
  },
  goalItem: {
    flexDirection: 'row', alignItems: 'center',
    borderBottomWidth: 1, borderBottomColor: Palette.border.subtle,
  },
  goalItemPressed: { backgroundColor: Palette.bg.cardHover },
  goalIconBg: { alignItems: 'center', justifyContent: 'center', marginRight: Spacing.md },
  goalInfo: { flex: 1 },
  goalLabel: { ...Typography.caption, color: Palette.text.tertiary, marginBottom: 2 },
  goalValue: { ...Typography.bodyBold },

  settingsButton: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: Palette.bg.card, borderRadius: Radius.lg,
    borderWidth: 1, borderColor: Palette.border.subtle, gap: Spacing.sm,
  },
  settingsText: { ...Typography.body, color: Palette.text.secondary, flex: 1 },
});
