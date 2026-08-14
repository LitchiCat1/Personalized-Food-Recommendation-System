import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import type { Session } from '@supabase/supabase-js';

import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import { fetchUserProfile, saveUserProfile, type UserProfileResponse } from '@/lib/api';
import { isSupabaseAuthRequired, supabase } from '@/lib/supabase';
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

function buildInitialDraft(email?: string | null) {
  const fallbackName = email?.split('@')[0] || '';
  return {
    name: fallbackName,
    gender: 'male' as 'male' | 'female',
    height: '170',
    weight: '70',
    age: '22',
    activityMultiplier: '1.55',
    dailyCalorieTarget: '2100',
    targetWeight: '70',
    dietType: '均衡飲食',
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

  useEffect(() => {
    if (!isSupabaseAuthRequired || !supabase) {
      setAuthReady(true);
      return;
    }

    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      applySession(data.session);
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

  const updateProfileDraft = (key: keyof typeof profileDraft, value: string) => {
    setProfileDraft((current) => ({ ...current, [key]: value }));
  };

  const submitInitialProfile = async () => {
    const height = Number(profileDraft.height);
    const weight = Number(profileDraft.weight);
    const age = Number(profileDraft.age);
    const activityMultiplier = Number(profileDraft.activityMultiplier);
    const dailyCalorieTarget = Number(profileDraft.dailyCalorieTarget);
    const targetWeight = Number(profileDraft.targetWeight);

    if (!profileDraft.name.trim()) {
      setProfileMessage('請輸入姓名或暱稱。');
      return;
    }
    if (![height, weight, age, activityMultiplier, dailyCalorieTarget].every((value) => Number.isFinite(value) && value > 0)) {
      setProfileMessage('請確認身高、體重、年齡、活動係數與目標熱量都是有效數字。');
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
        activity_level: '中等活動量',
        activity_multiplier: activityMultiplier,
        daily_calorie_target: dailyCalorieTarget,
        health_conditions: [],
        allergens: [],
        target_weight: Number.isFinite(targetWeight) && targetWeight > 0 ? targetWeight : weight,
        diet_type: profileDraft.dietType.trim() || '均衡飲食',
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
      setMessage(error?.message || '驗證失敗，請稍後再試。');
    } finally {
      setBusy(false);
    }
  };

  if (!isSupabaseAuthRequired) {
    return <>{children}</>;
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
          <Text style={styles.subtitle}>完成後才會進入 App，避免新帳號看到預設示範資料。疾病與過敏原可之後在「我的」頁調整。</Text>

          <Text style={styles.inputLabel}>姓名 / 暱稱</Text>
          <TextInput value={profileDraft.name} onChangeText={(value) => updateProfileDraft('name', value)} placeholder="例如：小明" placeholderTextColor={Palette.text.tertiary} style={styles.input} />

          <View style={styles.genderRow}>
            {(['male', 'female'] as const).map((gender) => (
              <Pressable key={gender} onPress={() => updateProfileDraft('gender', gender)} style={[styles.genderButton, profileDraft.gender === gender && styles.genderButtonActive]}>
                <Text style={[styles.genderText, profileDraft.gender === gender && styles.genderTextActive]}>{gender === 'male' ? '男性' : '女性'}</Text>
              </Pressable>
            ))}
          </View>

          {[
            ['height', '身高 cm'],
            ['weight', '體重 kg'],
            ['age', '年齡'],
            ['activityMultiplier', '活動係數'],
            ['dailyCalorieTarget', '每日目標熱量 kcal'],
            ['targetWeight', '目標體重 kg'],
            ['dietType', '飲食型態'],
          ].map(([key, label]) => (
            <View key={key}>
              <Text style={styles.inputLabel}>{label}</Text>
              <TextInput
                value={profileDraft[key as keyof typeof profileDraft]}
                onChangeText={(value) => updateProfileDraft(key as keyof typeof profileDraft, value)}
                keyboardType={key === 'dietType' ? 'default' : 'decimal-pad'}
                placeholderTextColor={Palette.text.tertiary}
                style={styles.input}
              />
            </View>
          ))}

          {profileMessage ? <Text style={styles.message}>{profileMessage}</Text> : null}

          <Pressable disabled={savingProfile} onPress={submitInitialProfile} style={[styles.primaryButton, savingProfile && styles.disabledButton]}>
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
        <Text style={styles.kicker}>Supabase Auth</Text>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>登入後，後端會用 Supabase access token 驗證你的 user_id。</Text>

        <TextInput
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          onChangeText={setEmail}
          placeholder="email@example.com"
          placeholderTextColor={Palette.text.tertiary}
          style={styles.input}
          value={email}
        />
        <TextInput
          autoCapitalize="none"
          onChangeText={setPassword}
          placeholder="至少 6 個字元的密碼"
          placeholderTextColor={Palette.text.tertiary}
          secureTextEntry
          style={styles.input}
          value={password}
        />

        {message ? <Text style={styles.message}>{message}</Text> : null}

        <Pressable disabled={busy} onPress={submit} style={[styles.primaryButton, busy && styles.disabledButton]}>
          {busy ? <ActivityIndicator color={Palette.bg.primary} /> : <Text style={styles.primaryText}>{mode === 'login' ? '登入' : '註冊'}</Text>}
        </Pressable>

        <Pressable onPress={() => setMode(mode === 'login' ? 'signup' : 'login')} style={styles.secondaryButton}>
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
