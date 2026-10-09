import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { DEFAULT_DIET_TYPE, DIET_TYPES } from '@/constants/diet';
import { PROFILE_LIMITS, describeLimit, isWithinLimit } from '@/constants/profile-defaults';
import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import { fetchMedicalMetadata, fetchUserProfile, saveUserProfile, type MedicalMetadataResponse, type UserProfileResponse } from '@/lib/api';
import { clearStoredSession, fetchSignupMode, isAuthRequired, onUnauthorized, restoreSession, signIn, signUp, subscribeToSessionChanges, type AuthSession, type SignupMode } from '@/lib/auth';
import { useStore, type UserProfile } from '@/store/useStore';


function applySession(session: AuthSession | null) {
  const store = useStore.getState();
  if (!session?.user) {
    store.setAuthSession(null);
    return;
  }

  store.setAuthSession({
    userId: session.user.id,
    email: session.user.email,
    accessToken: session.accessToken,
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
    targetWeight: data.target_weight || 0,
    dietType: data.diet_type,
    // 後端落後一版時這個欄位是 undefined；判不出來就當成填過了。
    profileComplete: data.profile_complete !== false,
  };
}

const FALLBACK_ACTIVITY_LEVELS = [
  { id: 'sedentary', label_zh: '久坐（幾乎不運動）', multiplier: 1.2 },
  { id: 'light', label_zh: '輕度活動（每週 1-3 天）', multiplier: 1.375 },
  { id: 'moderate', label_zh: '中等活動（每週 3-5 天）', multiplier: 1.55 },
  { id: 'active', label_zh: '高度活動（每週 6-7 天）', multiplier: 1.725 },
  { id: 'very_active', label_zh: '極高活動（勞力工作或每日訓練）', multiplier: 1.9 },
];

// 後端回的錯誤訊息本來就是給使用者看的中文；只有斷網時瀏覽器給的
// "Failed to fetch" 要翻成使用者知道該做什麼的話。
function describeAuthError(error: any, fallback: string) {
  const raw = String(error?.message || '');
  if (!raw) return fallback;
  if (/failed to fetch|network/i.test(raw)) {
    return '連不到伺服器，請確認後端有開著，再試一次。';
  }
  return raw;
}

function buildInitialDraft(email?: string | null) {
  const fallbackName = email?.split('@')[0] || '';
  return {
    name: fallbackName,
    // 不預選。BMR 的公式男女差 166 kcal，而這一格先前是預先選好「男性」的：
    // 表單上其他欄位都要自己填，唯獨這個替使用者決定了，而且看起來像他選的。
    gender: '' as '' | 'male' | 'female',
    height: '',
    weight: '',
    age: '',
    // 這裡原本是一個「活動係數」欄位，要使用者自己填 1.55；
    // 改成挑活動量，係數與每日熱量都交給後端算。
    activityLevel: 'moderate',
    // 先前預填 '70'，而下面的 submit 又把空白補成「目前體重」——兩種情況都是
    // 替使用者編一個他沒說過的目標，然後「飲食目標」分頁把它當成真的顯示。
    targetWeight: '',
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
  const [inviteCode, setInviteCode] = useState('');
  // 從其他裝置或 tunnel 連進來時，註冊要邀請碼或不開放；由後端依連線來源決定
  const [signupMode, setSignupMode] = useState<SignupMode>('open');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [profileStatus, setProfileStatus] = useState<'idle' | 'loading' | 'required' | 'ready' | 'error'>('idle');
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileDraft, setProfileDraft] = useState(buildInitialDraft(null));
  const [profileReloadKey, setProfileReloadKey] = useState(0);
  /** 載入已經等了幾秒——用來在冷啟動時把畫面上的沉默換成一句解釋。 */
  const [loadingSeconds, setLoadingSeconds] = useState(0);
  // 新帳號原本一律送出空的疾病與過敏原陣列，等於整套醫療過濾在初次設定時是關掉的。
  const [medicalMetadata, setMedicalMetadata] = useState<MedicalMetadataResponse | null>(null);
  const [selectedConditions, setSelectedConditions] = useState<string[]>([]);
  const [selectedAllergens, setSelectedAllergens] = useState<string[]>([]);

  useEffect(() => {
    if (!isAuthRequired) {
      setAuthReady(true);
      return;
    }

    let active = true;
    restoreSession(useStore.getState().apiBaseUrl)
      .then((session) => {
        if (!active) return;
        applySession(session);
        setAuthReady(true);
      })
      .catch(() => {
        if (!active) return;
        applySession(null);
        setAuthReady(true);
      });

    return () => {
      active = false;
    };
  }, [setAuthReady]);

  useEffect(() => {
    if (!isAuthRequired) return;

    // 另一個分頁登入、登出或換帳號：這一頁跟著變。換帳號時先登出一下，
    // 讓畫面整個重新載入新帳號的資料，不會殘留上一個人的紀錄。
    const stopSync = subscribeToSessionChanges((session) => {
      const current = useStore.getState();
      if (session && current.isAuthenticated && current.user.userId !== session.user.id) {
        applySession(null);
        setTimeout(() => applySession(session), 0);
        return;
      }
      applySession(session);
    });

    // 後端說 token 沒用了（過期、在其他分頁登出、後端換了資料庫）：回登入畫面，
    // 而不是讓每個按鈕都跳「沒有權限」。
    const stopUnauthorized = onUnauthorized(() => {
      if (!useStore.getState().isAuthenticated) return;
      void clearStoredSession();
      applySession(null);
      setMessage('登入已過期，請重新登入。');
    });

    return () => {
      stopSync();
      stopUnauthorized();
    };
  }, []);

  // 被登出（自己按、其他分頁、或 token 過期）時回到登入表單。先前會停在上次用過的
  // 「建立帳號」，已經有帳號的人被叫去註冊。
  useEffect(() => {
    if (!isAuthenticated) setMode('login');
  }, [isAuthenticated]);

  useEffect(() => {
    if (mode !== 'signup') return;
    let active = true;
    fetchSignupMode(apiBaseUrl).then((next) => {
      if (active) setSignupMode(next);
    });
    return () => {
      active = false;
    };
  }, [apiBaseUrl, mode]);

  const signupClosed = mode === 'signup' && signupMode === 'closed';

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

  /**
   * 後端在 Render 免費方案上會休眠，第一個請求要等它冷啟動。
   *
   * 實測開首頁時 `OPTIONS /user/...` 一直 pending，畫面停在「正在載入你的
   * 基本資料...」超過 30 秒——沒有說明、沒有逾時、沒有重試。而 AuthGate 會
   * 擋住所有子畫面，所以那 30 秒裡整個 App 都不能用，看起來像壞了。
   *
   * 修不掉冷啟動本身（那是方案限制），但可以不要讓使用者對著一個沉默的
   * 轉圈圈猜發生什麼事。
   */
  useEffect(() => {
    if (profileStatus !== 'loading') {
      setLoadingSeconds(0);
      return;
    }
    const startedAt = Date.now();
    const timer = setInterval(() => {
      setLoadingSeconds(Math.round((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [profileStatus]);

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
    if (!profileDraft.gender) {
      setProfileMessage('請選擇生理性別，基礎代謝率的公式需要它。');
      return;
    }
    const outOfRange = ([['height', height], ['weight', weight], ['age', age]] as const)
      .find(([field, value]) => !isWithinLimit(PROFILE_LIMITS[field], String(value)));
    if (outOfRange) {
      setProfileMessage(`${describeLimit(PROFILE_LIMITS[outOfRange[0]])}。`);
      return;
    }
    if (profileDraft.targetWeight.trim() && !isWithinLimit(PROFILE_LIMITS.target_weight, profileDraft.targetWeight)) {
      setProfileMessage(`${describeLimit(PROFILE_LIMITS.target_weight)}，或留空不設定。`);
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
        // 沒填就是沒設定。先前這裡補上「目前體重」，於是每個人的檔案裡都有
        // 一個他沒設過的目標體重。
        target_weight: Number.isFinite(targetWeight) && targetWeight > 0 ? targetWeight : null,
        diet_type: profileDraft.dietType.trim() || DEFAULT_DIET_TYPE,
        profile_complete: true,
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

  const showPasswordResetHelp = () => {
    // 先前沒有這個入口，忘記密碼等於帳號永久鎖死。本地端不會寄信，
    // 改由跑後端的那台電腦重設。
    const address = email.trim() || '你的 Email';
    setMessage(`請在跑後端的電腦上執行：python backend/scripts/reset_password.py ${address}`);
  };

  const submit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const session = mode === 'login'
        ? await signIn(apiBaseUrl, email.trim(), password)
        : await signUp(apiBaseUrl, email.trim(), password, signupMode === 'code' ? inviteCode.trim() : undefined);
      applySession(session);
    } catch (error: any) {
      setMessage(describeAuthError(error, mode === 'login' ? '登入失敗，請稍後再試。' : '註冊失敗，請稍後再試。'));
    } finally {
      setBusy(false);
    }
  };

  if (!isAuthRequired) {
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
    // 本機後端正常是一秒內回應；超過 5 秒多半是後端沒開，超過 20 秒就給一個重試的出口。
    const slow = loadingSeconds >= 5;
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={Palette.accent.green} />
        <Text style={styles.mutedText}>正在載入你的基本資料...</Text>
        {slow ? (
          <Text style={styles.message}>
            後端回應比平常慢，請確認後端有開著。已等待 {loadingSeconds} 秒。
          </Text>
        ) : null}
        {loadingSeconds >= 20 ? (
          <Pressable onPress={() => setProfileReloadKey((key) => key + 1)} style={styles.primaryButton}>
            <Text style={styles.primaryText}>重新嘗試</Text>
          </Pressable>
        ) : null}
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
            ['targetWeight', '目標體重 kg（可留空）'],
          ].map(([key, label]) => (
            <View key={key}>
              <Text style={styles.inputLabel}>{label}</Text>
              <TextInput
                accessibilityLabel={label}
                value={profileDraft[key as keyof typeof profileDraft]}
                onChangeText={(value) => updateProfileDraft(key as keyof typeof profileDraft, value)}
                keyboardType="decimal-pad"
                placeholder={PROFILE_LIMITS[key === 'targetWeight' ? 'target_weight' : key]
                  ? `${PROFILE_LIMITS[key === 'targetWeight' ? 'target_weight' : key].min}~${PROFILE_LIMITS[key === 'targetWeight' ? 'target_weight' : key].max}`
                  : undefined}
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
        {/* 先前寫「後端會用 access token 驗證你的 user_id」——
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
          placeholder="至少 8 個字元"
          placeholderTextColor={Palette.text.tertiary}
          returnKeyType="go"
          secureTextEntry
          style={styles.input}
          value={password}
        />

        {mode === 'signup' && signupMode === 'code' ? (
          <>
            <Text style={styles.inputLabel} nativeID="auth-invite-label">邀請碼</Text>
            <TextInput
              accessibilityLabel="邀請碼"
              accessibilityLabelledBy="auth-invite-label"
              autoCapitalize="none"
              autoComplete="off"
              onChangeText={setInviteCode}
              onSubmitEditing={submit}
              placeholder="向網站主人索取"
              placeholderTextColor={Palette.text.tertiary}
              returnKeyType="go"
              style={styles.input}
              value={inviteCode}
            />
          </>
        ) : null}

        {signupClosed ? (
          <Text style={styles.message}>這個網址目前不開放註冊，請向網站主人索取邀請碼。已經有帳號的話可以直接登入。</Text>
        ) : null}

        {message ? <Text style={styles.message} accessibilityLiveRegion="polite">{message}</Text> : null}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={mode === 'login' ? '登入' : '註冊'}
          aria-disabled={busy || signupClosed} aria-busy={busy}
          disabled={busy || signupClosed}
          onPress={submit}
          style={[styles.primaryButton, (busy || signupClosed) && styles.disabledButton]}
        >
          {busy ? <ActivityIndicator color={Palette.bg.primary} /> : <Text style={styles.primaryText}>{mode === 'login' ? '登入' : '註冊'}</Text>}
        </Pressable>

        {mode === 'login' ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="忘記密碼，查看重設方式"
            disabled={busy}
            onPress={showPasswordResetHelp}
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
