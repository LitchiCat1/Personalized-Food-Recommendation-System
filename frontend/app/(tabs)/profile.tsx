import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, TextInput, Alert, Platform, Modal, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { AVAILABLE_CONDITIONS, AVAILABLE_ALLERGENS, DIET_GOALS } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import MetricCard from '@/components/ui/metric-card';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import SegmentedControl from '@/components/ui/segmented-control';
import { fetchMedicalMetadata, fetchUserProfile, saveUserProfile } from '@/lib/api';
import { isSupabaseAuthConfigured, supabase } from '@/lib/supabase';

type MedicalMetadata = Awaited<ReturnType<typeof fetchMedicalMetadata>>;

const PROFILE_SECTIONS = [
  { value: 'personal', label: '個人資料' },
  { value: 'safety', label: '安全條件' },
  { value: 'goals', label: '飲食目標' },
];

export default function ProfileScreen() {
  const { gridCol2, isDesktop } = useResponsive();
  const { user, toggleCondition, toggleAllergen, apiBaseUrl, accessToken, replaceUser } = useStore();
  const initialUserRef = useRef(user);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [profileModalVisible, setProfileModalVisible] = useState(false);
  const [activeSection, setActiveSection] = useState('personal');
  const [medicalMetadata, setMedicalMetadata] = useState<MedicalMetadata | null>(null);
  const [profileDraft, setProfileDraft] = useState({
    name: user.name,
    height: String(user.height),
    weight: String(user.weight),
    age: String(user.age),
    dailyCalorieTarget: String(user.dailyCalorieTarget),
    targetWeight: String(user.targetWeight || ''),
    dietType: user.dietType,
  });

  useEffect(() => {
    let cancelled = false;
    const seedUser = initialUserRef.current;

    fetchMedicalMetadata(apiBaseUrl)
      .then((metadata) => {
        if (!cancelled) setMedicalMetadata(metadata);
      })
      .catch(() => {
        if (!cancelled) setMedicalMetadata(null);
      });

    fetchUserProfile(apiBaseUrl, user.userId, { accessToken })
      .catch((err: Error) => {
        if (!err.message.includes('使用者不存在')) throw err;
        return saveUserProfile(apiBaseUrl, {
          user_id: seedUser.userId,
          name: seedUser.name,
          gender: seedUser.gender,
          weight: seedUser.weight,
          height: seedUser.height,
          age: seedUser.age,
          activity_level: seedUser.activityLevel,
          activity_multiplier: seedUser.activityMultiplier,
          daily_calorie_target: seedUser.dailyCalorieTarget,
          health_conditions: seedUser.healthConditions,
          allergens: seedUser.allergens,
          target_weight: seedUser.targetWeight,
          diet_type: seedUser.dietType,
        }, { accessToken }).then((response) => response.user);
      })
      .then((data) => {
        if (cancelled) return;
        replaceUser({
          userId: data.user_id,
          name: data.name,
          email: seedUser.email,
          gender: data.gender,
          height: data.height,
          weight: data.weight,
          age: data.age,
          bmi: data.bmi,
          activityLevel: data.activity_level,
          activityMultiplier: data.activity_multiplier,
          bmr: data.bmr,
          tdee: data.tdee,
          healthConditions: data.health_conditions,
          allergens: data.allergens,
          dailyCalorieTarget: data.daily_calorie_target,
          targetWeight: data.target_weight || seedUser.targetWeight,
          dietType: data.diet_type,
          streak: seedUser.streak,
          totalMeals: seedUser.totalMeals,
        });
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiBaseUrl, replaceUser, user.userId]);

  useEffect(() => {
    setProfileDraft({
      name: user.name,
      height: String(user.height),
      weight: String(user.weight),
      age: String(user.age),
      dailyCalorieTarget: String(user.dailyCalorieTarget),
      targetWeight: String(user.targetWeight || ''),
      dietType: user.dietType,
    });
  }, [user.name, user.height, user.weight, user.age, user.dailyCalorieTarget, user.targetWeight, user.dietType]);

  const syncProfile = async (nextUser = user) => {
    setSaving(true);
    try {
      const response = await saveUserProfile(apiBaseUrl, {
        user_id: nextUser.userId,
        name: nextUser.name,
        gender: nextUser.gender,
        weight: nextUser.weight,
        height: nextUser.height,
        age: nextUser.age,
        activity_level: nextUser.activityLevel,
        activity_multiplier: nextUser.activityMultiplier,
        daily_calorie_target: nextUser.dailyCalorieTarget,
        health_conditions: nextUser.healthConditions,
        allergens: nextUser.allergens,
        target_weight: nextUser.targetWeight,
        diet_type: nextUser.dietType,
      }, { accessToken });

      replaceUser({
        ...nextUser,
        bmi: response.user.bmi,
        bmr: response.user.bmr,
        tdee: response.user.tdee,
        dailyCalorieTarget: response.user.daily_calorie_target,
      });
      setError(null);
    } catch (err: any) {
      setError(err?.message || '儲存失敗');
    } finally {
      setSaving(false);
    }
  };

  const updateDraft = (key: keyof typeof profileDraft, value: string) => {
    setProfileDraft((draft) => ({ ...draft, [key]: value }));
  };

  const parsePositiveNumber = (value: string, fallback: number) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };

  const isPositiveDraftNumber = (value: string) => {
    const parsed = Number(value);
    return value.trim().length > 0 && Number.isFinite(parsed) && parsed > 0;
  };

  const isProfileDraftValid =
    profileDraft.name.trim().length > 0 &&
    isPositiveDraftNumber(profileDraft.height) &&
    isPositiveDraftNumber(profileDraft.weight) &&
    isPositiveDraftNumber(profileDraft.age) &&
    isPositiveDraftNumber(profileDraft.dailyCalorieTarget) &&
    isPositiveDraftNumber(profileDraft.targetWeight) &&
    (profileDraft.dietType === '葷食' || profileDraft.dietType === '素食');

  const conditionCatalog = useMemo(() => {
    if (medicalMetadata?.disease_rules.conditions?.length) return medicalMetadata.disease_rules.conditions;
    return AVAILABLE_CONDITIONS.map((cond) => ({
      id: cond.id,
      condition: cond.id,
      label_zh: cond.label,
      aliases: [cond.label],
      category: null,
      description: cond.description,
      screening_focus: [],
      severity_options: [],
      rule_version: null,
      review_status: null,
      last_reviewed: null,
      reviewed_by: null,
      evidence_level: null,
      references: [],
      medical_disclaimer: medicalMetadata?.medical_disclaimer || '',
      limits: {},
      risk_nutrients: {},
    }));
  }, [medicalMetadata]);

  const allergenCatalog = useMemo(() => {
    if (medicalMetadata?.allergen_taxonomy.groups?.length) return medicalMetadata.allergen_taxonomy.groups;
    return AVAILABLE_ALLERGENS.map((label, index) => ({
      id: `legacy-${index}`,
      label_zh: label,
      severity: 'medium',
      aliases: [label],
      keywords: [label],
    }));
  }, [medicalMetadata]);

  const handleSaveProfileFields = async () => {
    if (!isProfileDraftValid) return;

    const nextUser = {
      ...user,
      name: profileDraft.name.trim() || user.name,
      height: parsePositiveNumber(profileDraft.height, user.height),
      weight: parsePositiveNumber(profileDraft.weight, user.weight),
      age: Math.round(parsePositiveNumber(profileDraft.age, user.age)),
      dailyCalorieTarget: Math.round(parsePositiveNumber(profileDraft.dailyCalorieTarget, user.dailyCalorieTarget)),
      targetWeight: parsePositiveNumber(profileDraft.targetWeight, user.targetWeight),
      dietType: profileDraft.dietType,
    };

    await syncProfile(nextUser);
    setProfileModalVisible(false);
    Alert.alert('健康檔案已更新', '個人資料已同步到後端。');
  };

  const performSignOut = async () => {
    if (!isSupabaseAuthConfigured || !supabase) {
      Alert.alert('Demo 模式', '目前未啟用 Supabase Auth。');
      return;
    }
    const supabaseClient = supabase;

    setSigningOut(true);
    try {
      const { error: signOutError } = await supabaseClient.auth.signOut();
      if (signOutError) throw signOutError;
      useStore.getState().setAuthSession(null);
    } catch (err: any) {
      Alert.alert('登出失敗', err?.message || '無法登出。');
    } finally {
      setSigningOut(false);
    }
  };

  const handleSignOut = () => {
    if (!isSupabaseAuthConfigured || !supabase) {
      Alert.alert('Demo 模式', '目前未啟用 Supabase Auth。');
      return;
    }

    if (Platform.OS === 'web') {
      const confirmed = typeof window === 'undefined' ? true : window.confirm('確定要登出嗎？');
      if (confirmed) void performSignOut();
      return;
    }

    Alert.alert('登出 NutriLens', '確定要登出嗎？', [
      { text: '取消', style: 'cancel' },
      { text: '登出', style: 'destructive', onPress: () => { void performSignOut(); } },
    ]);
  };

  const savingMessage = useMemo(() => {
    if (loading) return '載入健康檔案中';
    if (saving) return '同步中';
    if (error) return `同步失敗：${error}`;
    return '健康條件與過敏原會同步到後端';
  }, [error, loading, saving]);

  return (
    <AppContainer>
      <ScreenHeader title="我的健康檔案" subtitle="管理身體資料、飲食目標、疾病條件與過敏原。" badge={isSupabaseAuthConfigured ? 'Auth 已登入' : 'Demo 模式'} badgeTone={isSupabaseAuthConfigured ? 'success' : 'warning'} />

      <View style={[styles.syncBanner, error && styles.syncWarning]}>
        {loading || saving ? <ActivityIndicator size="small" color={Palette.accent.green} /> : <Ionicons name={error ? 'cloud-offline-outline' : 'cloud-done-outline'} size={16} color={error ? Palette.status.warning : Palette.accent.green} />}
        <Text style={[styles.syncText, error && styles.syncWarningText]}>{savingMessage}</Text>
      </View>

      {!isDesktop ? <SegmentedControl options={PROFILE_SECTIONS} value={activeSection} onChange={setActiveSection} /> : null}

      <View style={isDesktop ? styles.desktopColumns : styles.mobileSectionContent}>
      {isDesktop || activeSection === 'personal' ? (
      <View style={isDesktop ? styles.desktopPane : undefined}>
        <View style={styles.accountCard}>
          <View style={styles.avatar}>
            <Text style={styles.avatarInitial}>{user.name.slice(0, 1).toUpperCase()}</Text>
          </View>
          <View style={styles.accountCopy}>
            <Text style={styles.userName}>{user.name}</Text>
            <Text style={styles.userEmail}>{user.email}</Text>
            <View style={styles.badgeRow}>
              <DataPill tone="success">連續 {user.streak} 天</DataPill>
              <DataPill tone="info">累積 {user.totalMeals} 餐</DataPill>
            </View>
          </View>
        </View>

        <View style={styles.metricRow}>
          <MetricCard label="BMR" value={user.bmr} unit="kcal" accent={Palette.accent.blue} />
          <MetricCard label="TDEE" value={user.tdee} unit="kcal" accent={Palette.accent.green} />
          <MetricCard label="BMI" value={user.bmi} accent={Palette.accent.orange} />
        </View>

        <View style={styles.profileSetupCard}>
          <View style={styles.profileSetupCopy}>
            <Text style={styles.profileSetupTitle}>個人基本資料</Text>
            <Text style={styles.profileSetupMeta}>{user.height}cm · {user.weight}kg · {user.age} 歲 · {user.dietType}</Text>
          </View>
          <SecondaryButton label="編輯資料" onPress={() => setProfileModalVisible(true)} icon={<Ionicons name="create-outline" size={17} color={Palette.accent.green} />} />
        </View>

        <View style={styles.accountActions}>
          <SecondaryButton label={signingOut ? '登出中' : '登出'} onPress={handleSignOut} disabled={signingOut} icon={<Ionicons name="log-out-outline" size={17} color={Palette.status.error} />} />
        </View>
      </View>
      ) : null}

      {isDesktop || activeSection === 'safety' ? (
      <View style={isDesktop ? styles.desktopPane : undefined}>
      <SectionBlock title="健康狀況管理" subtitle="影響推薦與掃描風險提示。">
        <View style={styles.medicalDisclaimer}>
          <Ionicons name="medical-outline" size={16} color={Palette.status.warning} />
          <Text style={styles.medicalDisclaimerText}>{medicalMetadata?.medical_disclaimer || '疾病與營養提醒僅供健康管理參考，不可取代醫療專業建議。'}</Text>
        </View>
        <View style={styles.conditionsGrid}>
          {conditionCatalog.map((cond) => {
            const isActive = user.healthConditions.includes(cond.id) || user.healthConditions.includes(cond.label_zh);
            const fallback = AVAILABLE_CONDITIONS.find((item) => item.id === cond.id);
            const accent = fallback?.color || Palette.accent.green;
            return (
              <Pressable
                key={cond.id}
                accessibilityRole="checkbox"
                accessibilityLabel={cond.label_zh}
                accessibilityState={{ checked: isActive }}
                onPress={() => {
                  const nextConditions = isActive
                    ? user.healthConditions.filter((c) => c !== cond.id && c !== cond.label_zh)
                    : [...user.healthConditions.filter((c) => c !== cond.label_zh), cond.id];
                  toggleCondition(cond.id);
                  void syncProfile({ ...user, healthConditions: nextConditions });
                }}
                style={[styles.conditionChip, isActive && styles.conditionChipActive]}
              >
                <View style={[styles.conditionIcon, isActive && { backgroundColor: `${accent}22` }]}>
                  <Ionicons name="medical-outline" size={18} color={isActive ? accent : Palette.text.tertiary} />
                </View>
                <View style={styles.conditionInfo}>
                  <Text style={[styles.conditionLabel, isActive && { color: accent }]}>{cond.label_zh}</Text>
                  <Text style={styles.conditionDesc}>{cond.description}</Text>
                </View>
                <Ionicons name={isActive ? 'checkmark-circle' : 'add-circle-outline'} size={22} color={isActive ? accent : Palette.text.tertiary} />
              </Pressable>
            );
          })}
        </View>
      </SectionBlock>

      <SectionBlock title="過敏原設定" subtitle="選取後會從掃描與推薦中自動排除。">
        <View style={styles.allergenChipsWrap}>
          {allergenCatalog.map((allergen) => {
            const isActive = user.allergens.includes(allergen.id) || user.allergens.includes(allergen.label_zh);
            return (
              <Pressable
                key={allergen.id}
                accessibilityRole="checkbox"
                accessibilityLabel={allergen.label_zh}
                accessibilityState={{ checked: isActive }}
                onPress={() => {
                  const nextAllergens = isActive
                    ? user.allergens.filter((a) => a !== allergen.id && a !== allergen.label_zh)
                    : [...user.allergens.filter((a) => a !== allergen.label_zh), allergen.id];
                  toggleAllergen(allergen.id);
                  void syncProfile({ ...user, allergens: nextAllergens });
                }}
                style={[styles.allergenChip, isActive && styles.allergenChipActive]}
              >
                <Text style={[styles.allergenChipText, isActive && styles.allergenChipTextActive]}>{allergen.label_zh}</Text>
                <Ionicons name={isActive ? 'close-circle' : 'add-circle-outline'} size={15} color={isActive ? Palette.status.error : Palette.text.tertiary} />
              </Pressable>
            );
          })}
        </View>
      </SectionBlock>
      </View>
      ) : null}

      {isDesktop || activeSection === 'goals' ? (
      <View style={isDesktop ? styles.desktopPane : undefined}>
      <SectionBlock title="飲食目標" subtitle="用於顯示目前設定與提醒。">
        <View style={styles.goalList}>
          {DIET_GOALS.map((goal) => (
            <View key={goal.id} style={styles.goalItem}>
              <View style={[styles.goalIcon, { backgroundColor: `${goal.color}18` }]}>
                <Ionicons name="flag-outline" size={18} color={goal.color} />
              </View>
              <View style={styles.goalInfo}>
                <Text style={styles.goalLabel}>{goal.label}</Text>
                <Text style={[styles.goalValue, { color: goal.color }]}>{goal.value}</Text>
              </View>
            </View>
          ))}
        </View>
      </SectionBlock>
      </View>
      ) : null}
      </View>

      <Modal visible={profileModalVisible} transparent animationType="fade" onRequestClose={() => setProfileModalVisible(false)}>
        <View style={styles.modalLayer}>
          <Pressable style={styles.modalBackdrop} onPress={() => setProfileModalVisible(false)} />
          <View style={styles.profileModal}>
            <View style={styles.modalHeader}>
              <View style={styles.modalTitleWrap}>
                <Text style={styles.modalTitle}>編輯基本資料</Text>
                <Text style={styles.modalSubtitle}>個人資料變更會影響 BMR、TDEE 與每日建議目標。</Text>
              </View>
              <Pressable accessibilityRole="button" accessibilityLabel="關閉編輯視窗" onPress={() => setProfileModalVisible(false)} style={styles.modalCloseButton}>
                <Ionicons name="close" size={20} color={Palette.text.secondary} />
              </Pressable>
            </View>

            <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.modalScrollContent}>
              <View style={styles.formGrid}>
                {[
                  { key: 'name', label: '姓名', keyboardType: 'default' as const },
                  { key: 'height', label: '身高 cm', keyboardType: 'numeric' as const },
                  { key: 'weight', label: '體重 kg', keyboardType: 'numeric' as const },
                  { key: 'age', label: '年齡', keyboardType: 'numeric' as const },
                  { key: 'dailyCalorieTarget', label: '每日熱量 kcal', keyboardType: 'numeric' as const },
                  { key: 'targetWeight', label: '目標體重 kg', keyboardType: 'numeric' as const },
                ].map((field) => (
                  <View key={field.key} style={[styles.inputGroup, { width: gridCol2(Spacing.sm) }]}>
                    <Text style={styles.inputLabel}>{field.label}</Text>
                    <TextInput
                      value={profileDraft[field.key as keyof typeof profileDraft]}
                      onChangeText={(value) => updateDraft(field.key as keyof typeof profileDraft, value)}
                      keyboardType={field.keyboardType}
                      placeholderTextColor={Palette.text.muted}
                      style={styles.profileInput}
                    />
                  </View>
                ))}
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>飲食類型</Text>
                <View style={styles.dietOptions}>
                  {(['葷食', '素食'] as const).map((option) => {
                    const active = profileDraft.dietType === option;
                    return (
                      <Pressable
                        key={option}
                        accessibilityRole="radio"
                        accessibilityLabel={option}
                        accessibilityState={{ checked: active }}
                        onPress={() => updateDraft('dietType', option)}
                        style={[styles.dietOption, active && styles.dietOptionActive]}
                      >
                        <Ionicons name={active ? 'checkmark-circle' : 'ellipse-outline'} size={18} color={active ? Palette.accent.green : Palette.text.tertiary} />
                        <Text style={[styles.dietOptionText, active && styles.dietOptionTextActive]}>{option}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>

              <PrimaryButton
                label={saving ? '儲存中' : '儲存健康檔案'}
                onPress={handleSaveProfileFields}
                disabled={saving || !isProfileDraftValid}
                icon={saving ? <ActivityIndicator size="small" color={Palette.text.inverse} /> : <Ionicons name="save-outline" size={17} color={Palette.text.inverse} />}
              />
            </ScrollView>
          </View>
        </View>
      </Modal>
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  syncBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    marginBottom: Spacing.lg,
  },
  syncWarning: { borderColor: 'rgba(245,158,11,0.24)', backgroundColor: Palette.accent.orangeDim },
  syncText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  syncWarningText: { color: Palette.status.warning },
  accountCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.lg,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    padding: Spacing.xl,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.card,
  },
  avatar: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: Palette.bg.mint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarInitial: { ...Typography.h1, color: Palette.accent.green },
  accountCopy: { flex: 1, gap: Spacing.xs },
  userName: { ...Typography.h2, color: Palette.text.primary },
  userEmail: { ...Typography.caption, color: Palette.text.tertiary },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, marginTop: Spacing.xs },
  mobileSectionContent: { marginTop: Spacing.xl },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.lg },
  desktopPane: { flex: 1, minWidth: 0 },
  metricRow: { flexDirection: 'row', gap: Spacing.sm, marginBottom: Spacing.xl },
  profileSetupCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.md,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.lg,
    marginBottom: Spacing.xl,
    ...Shadows.soft,
  },
  profileSetupCopy: { flex: 1, gap: Spacing.xs },
  profileSetupTitle: { ...Typography.bodyBold, color: Palette.text.primary },
  profileSetupMeta: { ...Typography.caption, color: Palette.text.tertiary },
  formGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm, marginBottom: Spacing.lg },
  inputGroup: { gap: Spacing.xs },
  inputLabel: { ...Typography.small, color: Palette.text.tertiary },
  profileInput: {
    minHeight: 46,
    color: Palette.text.primary,
    backgroundColor: Palette.bg.elevated,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    ...Typography.caption,
  },
  dietOptions: { flexDirection: 'row', gap: Spacing.sm },
  dietOption: {
    flex: 1,
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
  },
  dietOptionActive: { backgroundColor: Palette.accent.greenDim, borderColor: 'rgba(31,157,114,0.26)' },
  dietOptionText: { ...Typography.bodyBold, color: Palette.text.secondary },
  dietOptionTextActive: { color: Palette.accent.green },
  modalLayer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: Palette.overlay,
  },
  profileModal: {
    width: '100%',
    maxWidth: 430,
    maxHeight: '86%',
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.xl,
    ...Shadows.card,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: Spacing.md,
    marginBottom: Spacing.lg,
  },
  modalTitleWrap: { flex: 1, gap: Spacing.xs },
  modalTitle: { ...Typography.h2, color: Palette.text.primary },
  modalSubtitle: { ...Typography.caption, color: Palette.text.secondary },
  modalCloseButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.bg.elevated,
  },
  modalScrollContent: { gap: Spacing.lg, paddingBottom: Spacing.xs },
  medicalDisclaimer: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    backgroundColor: Palette.accent.orangeDim,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.18)',
    padding: Spacing.md,
    marginBottom: Spacing.lg,
  },
  medicalDisclaimerText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  conditionsGrid: { gap: Spacing.md },
  conditionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.md,
  },
  conditionChipActive: { backgroundColor: Palette.bg.card, borderColor: 'rgba(31,157,114,0.22)' },
  conditionIcon: { width: 38, height: 38, borderRadius: 19, backgroundColor: Palette.bg.card, alignItems: 'center', justifyContent: 'center' },
  conditionEmoji: { fontSize: 18 },
  conditionInfo: { flex: 1 },
  conditionLabel: { ...Typography.bodyBold, color: Palette.text.secondary },
  conditionDesc: { ...Typography.small, color: Palette.text.tertiary },
  allergenChipsWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  allergenChip: {
    minHeight: 44,
    borderRadius: Radius.full,
    backgroundColor: Palette.bg.elevated,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
    paddingHorizontal: Spacing.md,
  },
  allergenChipActive: { backgroundColor: 'rgba(226,85,85,0.10)', borderColor: 'rgba(226,85,85,0.24)' },
  allergenChipText: { ...Typography.caption, color: Palette.text.secondary },
  allergenChipTextActive: { color: Palette.status.error },
  goalList: { gap: Spacing.md },
  goalItem: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md },
  goalIcon: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  goalEmoji: { fontSize: 17 },
  goalInfo: { flex: 1 },
  goalLabel: { ...Typography.caption, color: Palette.text.tertiary },
  goalValue: { ...Typography.bodyBold },
  accountActions: { gap: Spacing.md, marginBottom: Spacing.xl },
});
