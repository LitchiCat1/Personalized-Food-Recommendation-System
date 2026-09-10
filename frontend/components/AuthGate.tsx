import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import type { Session } from '@supabase/supabase-js';

import { DEFAULT_DIET_TYPE, DIET_TYPES } from '@/constants/diet';
import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import { fetchMedicalMetadata, fetchUserProfile, saveUserProfile, type MedicalMetadataResponse, type UserProfileResponse } from '@/lib/api';
import { isSupabaseAuthRequired, supabase, supabaseConfigurationError } from '@/lib/supabase';
import { useStore, type UserProfile } from '@/store/useStore';


function applySession(session: Session | null) {
  const store = useStore.getState();
  if (!session?.user) {
    store.setAuthSession(null);
    return;
  }

  store.setAuthSession({
    userId: session.user.id,
    email: session.user.email,
    accessToken: session.access_token,
  });
}

function mapProfileResponse(data: UserProfileResponse, currentUser: UserProfile): UserProfile {
  return {
    ...currentUser,
    userId: data.user_id,
    name: data.name,
    gender: data.gender,
    height: data.height,
    weight: data.weight,
    age: data.age,
    bmi: data.bmi,
    bmr: data.bmr,
    tdee: data.tdee,
    activityLevel: data.activity_level,
    activityMultiplier: data.activity_multiplier,
    healthConditions: data.health_conditions,
    allergens: data.allergens,
    dailyCalorieTarget: data.daily_calorie_target,
    targetWeight: data.target_weight || currentUser.targetWeight,
    dietType: data.diet_type,
  };
}

const FALLBACK_ACTIVITY_LEVELS = [
  { id: 'sedentary', label_zh: '久坐（幾乎不運動）', multiplier: 1.2 },
  { id: 'light', label_zh: '輕度活動（每週 1-3 天）', multiplier: 1.375 },
  { id: 'moderate', label_zh: '中等活動（每週 3-5 天）', multiplier: 1.55 },
  { id: 'active', label_zh: '高度活動（每週 6-7 天）', multiplier: 1.725 },
  { id: 'very_active', label_zh: '極高活動（勞力工作或每日訓練）', multiplier: 1.9 },
];

// Supabase 回的是英文，而且斷網時只會給 "Failed to fetch"。
// 直接照抄到畫面上，使用者不知道自己該做什麼。
function describeAuthError(error: any, fallback: string) {
  const raw = String(error?.message || '').toLowerCase();
  if (!raw) return fallback;
  if (raw.includes('failed to fetch') || raw.includes('network')) {
    return '連不到伺服器，請確認網路連線後再試一次。';
  }
  if (raw.includes('invalid login credentials')) {
    return 'Email 或密碼不對。忘記密碼的話可以按下面的「忘記密碼？」。';
  }
  if (raw.includes('email not confirmed')) {
    return '這個 Email 還沒完成驗證，請先到信箱點開驗證信。';
  }
  if (raw.includes('user already registered') || raw.includes('already been registered')) {
    return '這個 Email 已經註冊過了，請直接登入。';
  }
  if (raw.includes('password should be at least')) {
    return '密碼太短了，請至少 6 個字元。';
  }
  if (raw.includes('unable to validate email') || raw.includes('invalid email')) {
    return 'Email 格式不對，請再確認一次。';
  }
  if (raw.includes('rate limit') || raw.includes('too many')) {
    return '嘗試次數太多，請等幾分鐘後再試。';
  }
  return fallback;
}

function buildInitialDraft(email?: string | null) {
  const fallbackName = email?.split('@')[0] || '';
  return {
    name: fallbackName,
    gender: 'male' as 'male' | 'female',
    height: '170',
    weight: '70',
    age: '22',
    // 這裡原本是一個「活動係數」欄位，要使用者自己填 1.55；
    // 改成挑活動量，係數與每日熱量都交給後端算。
    activityLevel: 'moderate',
    targetWeight: '70',
    dietType: DEFAULT_DIET_TYPE as string,
  };
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const authReady = useStore((state) => state.authReady);
  const isAuthenticated = useStore((state) => state.isAuthenticated);
  const user = useStore((state) => state.user);
  const apiBaseUrl = useStore((state) => state.apiBaseUrl);
  const accessToken = useStore((state) => state.accessToken);
  const setAuthReady = useStore((state) => state.setAuthReady);
  const replaceUser = useStore((state) => state.replaceUser);
  const resetDashboard = useStore((state) => state.resetDashboard);
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [profileStatus, setProfileStatus] = useState<'idle' | 'loading' | 'required' | 'ready' | 'error'>('idle');
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileDraft, setProfileDraft] = useState(buildInitialDraft(null));
  const [profileReloadKey, setProfileReloadKey] = useState(0);
  // 新帳號原本一律送出空的疾病與過敏原陣列，等於整套醫療過濾在初次設定時是關掉的。
  const [medicalMetadata, setMedicalMetadata] = useState<MedicalMetadataResponse | null>(null);
  const [selectedConditions, setSelectedConditions] = useState<string[]>([]);
  const [selectedAllergens, setSelectedAllergens] = useState<string[]>([]);

  useEffect(() => {
    if (!isSupabaseAuthRequired) {
      setAuthReady(true);
      return;
    }
    if (!supabase) {
      applySession(null);
      setAuthReady(true);
      return;
    }

    let active = true;
    supabase.auth.getSession()
      .then(({ data, error }) => {
        if (!active) return;
        if (error) setMessage(error.message || '無法確認 Supabase 登入狀態');
        applySession(error ? null : data.session);
        setAuthReady(true);
      })
      .catch((error: Error) => {
        if (!active) return;
        applySession(null);
        setMessage(error.message || '無法連線至 Supabase Auth');
        setAuthReady(true);
      });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      applySession(session);
      setAuthReady(true);
    });

    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, [setAuthReady]);

  const title = useMemo(() => mode === 'login' ? '登入 NutriLens' : '建立 NutriLens 帳號', [mode]);

  useEffect(() => {
    if (!isAuthenticated || !accessToken) {
      setProfileStatus('idle');
      return;
    }

    let active = true;
    setProfileStatus('loading');
    setProfileMessage(null);

    fetchUserProfile(apiBaseUrl, user.userId, { accessToken })
      .then((profile) => {
        if (!active) return;
        replaceUser(mapProfileResponse(profile, useStore.getState().user));
        setProfileStatus('ready');
      })
      .catch((error: Error) => {
        if (!active) return;
        if (error.message.includes('使用者不存在')) {
          setProfileDraft(buildInitialDraft(user.email));
          resetDashboard();
          setProfileStatus('required');
          return;
        }
        setProfileMessage(error.message || '讀取使用者資料失敗');
        setProfileStatus('error');
      });

    return () => {
      active = false;
    };
  }, [accessToken, apiBaseUrl, isAuthenticated, profileReloadKey, replaceUser, resetDashboard, user.email, user.userId]);

  useEffect(() => {
    if (profileStatus !== 'required') return;
    let cancelled = false;
    fetchMedicalMetadata(apiBaseUrl)
      .then((metadata) => {
        if (!cancelled) setMedicalMetadata(metadata);
      })
      .catch(() => {
        // 拿不到就用內建清單，不要因此擋住註冊流程。
        if (!cancelled) setMedicalMetadata(null);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, profileStatus]);

  const activityLevels = medicalMetadata?.activity_levels?.length
    ? medicalMetadata.activity_levels
    : FALLBACK_ACTIVITY_LEVELS;

  const conditionOptions = medicalMetadata?.disease_rules?.conditions ?? [];
  const allergenOptions = medicalMetadata?.allergen_taxonomy?.groups ?? [];

  const toggleFrom = (list: string[], id: string) =>
    list.includes(id) ? list.filter((entry) => entry !== id) : [...list, id];

  const updateProfileDraft = (key: keyof typeof profileDraft, value: string) => {
    setProfileDraft((current) => ({ ...current, [key]: value }));
  };

  const submitInitialProfile = async () => {
    const height = Number(profileDraft.height);
    const weight = Number(profileDraft.weight);
    const age = Number(profileDraft.age);
    const targetWeight = Number(profileDraft.targetWeight);

    if (!profileDraft.name.trim()) {
      setProfileMessage('請輸入姓名或暱稱。');
      return;
    }
    if (![height, weight, age].every((value) => Number.isFinite(value) && value > 0)) {
      setProfileMessage('請確認身高、體重與年齡都填了有效的數字。');
      return;
    }

    setSavingProfile(true);
    setProfileMessage(null);
    try {
      const response = await saveUserProfile(apiBaseUrl, {
        user_id: user.userId,
        name: profileDraft.name.trim(),
        gender: profileDraft.gender,
        height,
        weight,
        age,
        // 每日熱量目標由後端從 BMR × 活動係數 算出來，前端不再問一次。
        activity_level: profileDraft.activityLevel,
        health_conditions: selectedConditions,
        allergens: selectedAllergens,
        target_weight: Number.isFinite(targetWeight) && targetWeight > 0 ? targetWeight : weight,
        diet_type: profileDraft.dietType.trim() || DEFAULT_DIET_TYPE,
      }, { accessToken });
      replaceUser(mapProfileResponse(response.user, useStore.getState().user));
      resetDashboard();
      setProfileStatus('ready');
    } catch (error: any) {
      setProfileMessage(error?.message || '儲存基本資料失敗，請稍後再試。');
    } finally {
      setSavingProfile(false);
    }
  };

  const sendPasswordReset = async () => {
    // 先前沒有這個入口，忘記密碼等於帳號永久鎖死。
    if (!supabase) return;
    const address = email.trim();
    if (!address) {
      setMessage('請先填入你的 Email，我們會寄重設連結過去。');
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(address, {
        redirectTo: typeof window !== 'undefined' ? window.location.origin : undefined,
      });
      if (error) throw error;
      setMessage(`重設密碼的連結已寄到 ${address}，請到信箱點開連結。`);
    } catch (error: any) {
      setMessage(describeAuthError(error, '寄送重設信失敗，請稍後再試。'));
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!supabase) return;
    setBusy(true);
    setMessage(null);
    try {
      const credentials = { email: email.trim(), password };
      const { data, error } = mode === 'login'
        ? await supabase.auth.signInWithPassword(credentials)
        : await supabase.auth.signUp(credentials);

      if (error) throw error;
      applySession(data.session);
      if (!data.session) {
        setMessage('請到信箱完成驗證後再登入。');
      }
    } catch (error: any) {
      setMessage(describeAuthError(error, mode === 'login' ? '登入失敗，請稍後再試。' : '註冊失敗，請稍後再試。'));
    } finally {
      setBusy(false);
    }
  };

  if (!isSupabaseAuthRequired) {
    return <>{children}</>;
  }

  if (supabaseConfigurationError || !supabase) {
    return (
      <View style={styles.screen}>
        <View style={styles.card}>
          <Text style={styles.kicker}>部署設定錯誤</Text>
          <Text style={styles.title}>Supabase 尚未連接</Text>
          <Text style={styles.subtitle}>{supabaseConfigurationError || 'Supabase client 初始化失敗。'}</Text>
          <Text style={styles.message}>請在 Render Blueprint 建立時填入 Supabase URL 與 publishable key，然後重新部署前端與後端。</Text>
        </View>
      </View>
    );
  }

  if (!authReady) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={Palette.accent.green} />
        <Text style={styles.mutedText}>正在確認登入狀態...</Text>
      </View>
    );
  }

  if (isAuthenticated && profileStatus === 'loading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={Palette.accent.green} />
        <Text style={styles.mutedText}>正在載入你的基本資料...</Text>
      </View>
    );
  }

  if (isAuthenticated && profileStatus === 'required') {
    return (
      <ScrollView contentContainerStyle={styles.onboardingScreen}>
        <View style={styles.card}>
          <Text style={styles.kicker}>初次設定</Text>
          <Text style={styles.title}>先完成基本資料</Text>
          <Text style={styles.subtitle}>這些資料用來算你的每日營養目標，並在推薦餐點時避開你不能吃的東西。之後都可以在「我的」頁改。</Text>

          <Text style={styles.inputLabel}>姓名 / 暱稱</Text>
          <TextInput accessibilityLabel="姓名或暱稱" value={profileDraft.name} onChangeText={(value) => updateProfileDraft('name', value)} placeholder="例如：小明" placeholderTextColor={Palette.text.tertiary} style={styles.input} />

          <Text style={styles.inputLabel}>生理性別</Text>
          <View style={styles.genderRow}>
            {(['male', 'female'] as const).map((gender) => (
              <Pressable
                key={gender}
                accessibilityRole="radio"
                accessibilityLabel={gender === 'male' ? '男性' : '女性'}
                aria-checked={profileDraft.gender === gender}
                onPress={() => updateProfileDraft('gender', gender)}
                style={[styles.genderButton, profileDraft.gender === gender && styles.genderButtonActive]}
              >
                <Text style={[styles.genderText, profileDraft.gender === gender && styles.genderTextActive]}>{gender === 'male' ? '男性' : '女性'}</Text>
              </Pressable>
            ))}
          </View>

          {[
            ['height', '身高 cm'],
            ['weight', '體重 kg'],
            ['age', '年齡'],
            ['targetWeight', '目標體重 kg'],
          ].map(([key, label]) => (
            <View key={key}>
              <Text style={styles.inputLabel}>{label}</Text>
              <TextInput
                accessibilityLabel={label}
                value={profileDraft[key as keyof typeof profileDraft]}
                onChangeText={(value) => updateProfileDraft(key as keyof typeof profileDraft, value)}
                keyboardType="decimal-pad"
                placeholderTextColor={Palette.text.tertiary}
                style={styles.input}
              />
            </View>
          ))}

          <Text style={styles.inputLabel}>飲食型態</Text>
          <View style={styles.genderRow}>
            {DIET_TYPES.map((option) => (
              <Pressable
                key={option}
                accessibilityRole="radio"
                accessibilityLabel={option}
                aria-checked={profileDraft.dietType === option}
                onPress={() => updateProfileDraft('dietType', option)}
                style={[styles.genderButton, profileDraft.dietType === option && styles.genderButtonActive]}
              >
                <Text style={[styles.genderText, profileDraft.dietType === option && styles.genderTextActive]}>{option}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.inputLabel}>平常的活動量</Text>
          <View style={styles.optionColumn}>
            {activityLevels.map((level) => (
              <Pressable
                key={level.id}
                accessibilityRole="radio"
                accessibilityLabel={level.label_zh}
                aria-checked={profileDraft.activityLevel === level.id}
                onPress={() => updateProfileDraft('activityLevel', level.id)}
                style={[styles.optionRow, profileDraft.activityLevel === level.id && styles.optionRowActive]}
              >
                <Text style={[styles.optionText, profileDraft.activityLevel === level.id && styles.optionTextActive]}>{level.label_zh}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.inputLabel}>慢性疾病（可複選，沒有就不用選）</Text>
          {conditionOptions.length ? (
            <View style={styles.chipWrap}>
              {conditionOptions.map((condition) => {
                const picked = selectedConditions.includes(condition.id);
                return (
                  <Pressable
                    key={condition.id}
                    accessibilityRole="checkbox"
                    accessibilityLabel={condition.label_zh || condition.id}
                    aria-checked={picked}
                    onPress={() => setSelectedConditions((current) => toggleFrom(current, condition.id))}
                    style={[styles.chip, picked && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, picked && styles.chipTextActive]}>{condition.label_zh || condition.id}</Text>
                  </Pressable>
                );
              })}
            </View>
          ) : (
            <Text style={styles.hint}>目前連不到後端的疾病清單，可以先跳過，稍後在「我的」頁補選。</Text>
          )}

          <Text style={styles.inputLabel}>食物過敏原（可複選）</Text>
          {allergenOptions.length ? (
            <View style={styles.chipWrap}>
              {allergenOptions.map((allergen) => {
                const picked = selectedAllergens.includes(allergen.id);
                return (
                  <Pressable
                    key={allergen.id}
                    accessibilityRole="checkbox"
                    accessibilityLabel={allergen.label_zh || allergen.id}
                    aria-checked={picked}
                    onPress={() => setSelectedAllergens((current) => toggleFrom(current, allergen.id))}
                    style={[styles.chip, picked && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, picked && styles.chipTextActive]}>{allergen.label_zh || allergen.id}</Text>
                  </Pressable>
                );
              })}
            </View>
          ) : (
            <Text style={styles.hint}>目前連不到後端的過敏原清單，可以先跳過，稍後在「我的」頁補選。</Text>
          )}

          {medicalMetadata?.medical_disclaimer ? (
            <Text style={styles.hint}>{medicalMetadata.medical_disclaimer}</Text>
          ) : null}

          {profileMessage ? <Text style={styles.message} accessibilityLiveRegion="polite">{profileMessage}</Text> : null}

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="完成並進入 App"
            aria-disabled={savingProfile} aria-busy={savingProfile}
            disabled={savingProfile}
            onPress={submitInitialProfile}
            style={[styles.primaryButton, savingProfile && styles.disabledButton]}
          >
            {savingProfile ? <ActivityIndicator color={Palette.bg.primary} /> : <Text style={styles.primaryText}>完成並進入 App</Text>}
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  if (isAuthenticated && profileStatus === 'error') {
    return (
      <View style={styles.centered}>
        <Text style={styles.message}>{profileMessage || '讀取使用者資料失敗'}</Text>
        <Pressable onPress={() => setProfileReloadKey((key) => key + 1)} style={styles.primaryButton}>
          <Text style={styles.primaryText}>重新整理後再試</Text>
        </Pressable>
      </View>
    );
  }

  if (isAuthenticated && profileStatus === 'ready') {
    return <>{children}</>;
  }

  return (
    <View style={styles.screen}>
      <View style={styles.card}>
        <Text style={styles.title}>{title}</Text>
        {/* 先前寫「後端會用 Supabase access token 驗證你的 user_id」——
            使用者不需要知道我們用什麼登入系統。 */}
        <Text style={styles.subtitle}>
          {mode === 'login'
            ? '登入後就能看到你的飲食紀錄與個人化推薦。'
            : '建立帳號後，我們會問幾個問題來計算你的每日營養目標。'}
        </Text>

        {/* placeholder 不是 label：螢幕閱讀器在欄位有輸入後就讀不到提示 */}
        <Text style={styles.inputLabel} nativeID="auth-email-label">Email</Text>
        <TextInput
          accessibilityLabel="Email"
          accessibilityLabelledBy="auth-email-label"
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          onChangeText={setEmail}
          placeholder="email@example.com"
          placeholderTextColor={Palette.text.tertiary}
          style={styles.input}
          value={email}
        />
        <Text style={styles.inputLabel} nativeID="auth-password-label">密碼</Text>
        <TextInput
          accessibilityLabel="密碼"
          accessibilityLabelledBy="auth-password-label"
          autoCapitalize="none"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          onChangeText={setPassword}
          onSubmitEditing={submit}
          placeholder="至少 6 個字元"
          placeholderTextColor={Palette.text.tertiary}
          returnKeyType="go"
          secureTextEntry
          style={styles.input}
          value={password}
        />

        {message ? <Text style={styles.message} accessibilityLiveRegion="polite">{message}</Text> : null}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={mode === 'login' ? '登入' : '註冊'}
          aria-disabled={busy} aria-busy={busy}
          disabled={busy}
          onPress={submit}
          style={[styles.primaryButton, busy && styles.disabledButton]}
        >
          {busy ? <ActivityIndicator color={Palette.bg.primary} /> : <Text style={styles.primaryText}>{mode === 'login' ? '登入' : '註冊'}</Text>}
        </Pressable>

        {mode === 'login' ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="忘記密碼，寄送重設連結"
            disabled={busy}
            onPress={sendPasswordReset}
            style={styles.secondaryButton}
          >
            <Text style={styles.secondaryText}>忘記密碼？</Text>
          </Pressable>
        ) : null}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={mode === 'login' ? '建立帳號' : '回到登入'}
          onPress={() => setMode(mode === 'login' ? 'signup' : 'login')}
          style={styles.secondaryButton}
        >
          <Text style={styles.secondaryText}>{mode === 'login' ? '還沒有帳號？建立帳號' : '已有帳號？回到登入'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
    backgroundColor: Palette.bg.primary,
  },
  onboardingScreen: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
    backgroundColor: Palette.bg.primary,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.md,
    backgroundColor: Palette.bg.primary,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    padding: Spacing.xl,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.card,
    ...Shadows.card,
  },
  kicker: {
    color: Palette.accent.green,
    fontSize: 12,
    fontWeight: Typography.label.fontWeight,
    letterSpacing: Typography.label.letterSpacing,
    marginBottom: Spacing.xs,
  },
  title: {
    color: Palette.text.primary,
    fontSize: 26,
    fontWeight: '800',
    marginBottom: Spacing.sm,
  },
  subtitle: {
    color: Palette.text.secondary,
    fontSize: 13,
    lineHeight: 20,
    marginBottom: Spacing.lg,
  },
  input: {
    color: Palette.text.primary,
    backgroundColor: Palette.bg.secondary,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
    marginBottom: Spacing.md,
  },
  inputLabel: {
    color: Palette.text.tertiary,
    fontSize: 12,
    fontWeight: '700',
    marginBottom: Spacing.xs,
  },
  genderRow: {
    flexDirection: 'row',
    gap: Spacing.sm,
    marginBottom: Spacing.md,
  },
  genderButton: {
    flex: 1,
    alignItems: 'center',
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.secondary,
    padding: Spacing.md,
  },
  genderButtonActive: {
    borderColor: Palette.accent.green,
    backgroundColor: 'rgba(74, 222, 128, 0.12)',
  },
  genderText: {
    color: Palette.text.secondary,
    fontSize: 13,
    fontWeight: '700',
  },
  genderTextActive: {
    color: Palette.accent.green,
  },
  optionColumn: {
    gap: Spacing.xs,
    marginBottom: Spacing.md,
  },
  optionRow: {
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.secondary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  optionRowActive: {
    borderColor: Palette.accent.green,
    backgroundColor: 'rgba(74, 222, 128, 0.12)',
  },
  optionText: {
    color: Palette.text.secondary,
    fontSize: 13,
    fontWeight: '600',
  },
  optionTextActive: {
    color: Palette.accent.green,
  },
  chipWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.xs,
    marginBottom: Spacing.md,
  },
  chip: {
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.secondary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.xs,
  },
  chipActive: {
    borderColor: Palette.accent.green,
    backgroundColor: 'rgba(74, 222, 128, 0.12)',
  },
  chipText: {
    color: Palette.text.secondary,
    fontSize: 12,
    fontWeight: '600',
  },
  chipTextActive: {
    color: Palette.accent.green,
  },
  hint: {
    color: Palette.text.tertiary,
    fontSize: 12,
    lineHeight: 18,
    marginBottom: Spacing.md,
  },
  message: {
    color: Palette.status.warning,
    fontSize: 12,
    marginBottom: Spacing.md,
  },
  mutedText: {
    color: Palette.text.secondary,
    fontSize: 13,
  },
  primaryButton: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 46,
    borderRadius: Radius.md,
    backgroundColor: Palette.accent.green,
  },
  disabledButton: {
    opacity: 0.7,
  },
  primaryText: {
    color: Palette.bg.primary,
    fontSize: 15,
    fontWeight: '800',
  },
  secondaryButton: {
    alignItems: 'center',
    marginTop: Spacing.md,
  },
  secondaryText: {
    color: Palette.accent.cyan,
    fontSize: 13,
    fontWeight: '700',
  },
});
