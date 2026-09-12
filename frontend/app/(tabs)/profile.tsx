import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, TextInput, Alert, Platform, Modal, ScrollView } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { AVAILABLE_CONDITIONS, AVAILABLE_ALLERGENS } from '@/constants/mock-data';
import { DEFAULT_DIET_TYPE, DIET_TYPES, isKnownDietType } from '@/constants/diet';
import { NEW_USER_PROFILE, PROFILE_LIMITS, describeLimit, isWithinLimit, type ProfileLimit } from '@/constants/profile-defaults';
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
import FeedbackBanner from '@/components/ui/feedback-banner';
import { clearNearbyVenueIndex, fetchAllRecordsWithTargets, fetchMedicalMetadata, fetchUserProfile, indexNearbyVenues, listNearbyVenueIndex, saveUserProfile } from '@/lib/api';
import { bmiCategory, readWeightGoal } from '@/lib/body-metrics';
import { describeRequestError } from '@/lib/error-copy';
import { describeCalorieTarget, describeUserTargetFallback, formatCalories } from '@/lib/calorie-target';
import { calculateActivityStats } from '@/lib/dietary-trends';
import { describeLocation, resolveLocation } from '@/lib/location';
import { isSupabaseAuthConfigured, supabase } from '@/lib/supabase';
import { isSelected } from '@/lib/safety-selection';

type MedicalMetadata = Awaited<ReturnType<typeof fetchMedicalMetadata>>;

const PROFILE_SECTIONS = [
  { value: 'personal', label: '個人資料' },
  { value: 'safety', label: '安全條件' },
  { value: 'goals', label: '飲食目標' },
];

export default function ProfileScreen() {
  const { gridCol2, isDesktop } = useResponsive();
  const { user, toggleCondition, toggleAllergen, apiBaseUrl, accessToken, replaceUser, invalidateDietaryRecords , dailyNutrition, nutritionTargetBasis, setActivityStats, applyNutritionTargets, isAuthenticated, nutritionTargetsReady } = useStore();
  const initialUserRef = useRef(user);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [profileFeedback, setProfileFeedback] = useState<{ tone: 'success' | 'error'; title: string; message?: string } | null>(null);
  const [profileModalVisible, setProfileModalVisible] = useState(false);
  const [seedBusy, setSeedBusy] = useState<'index' | 'rebuild' | 'list' | null>(null);
  const [activeSection, setActiveSection] = useState('personal');
  const [medicalMetadata, setMedicalMetadata] = useState<MedicalMetadata | null>(null);
  const [profileDraft, setProfileDraft] = useState({
    name: user.name,
    height: String(user.height),
    weight: String(user.weight),
    age: String(user.age),
    dailyCalorieTarget: String(user.dailyCalorieTarget),
    targetWeight: String(user.targetWeight || ''),
    // 存在後端的值可能已經不在選單裡（舊帳號的「均衡飲食」）。照抄的話，
    // 表單一打開就是無效狀態，儲存鈕是灰的，而使用者什麼都還沒碰。
    dietType: isKnownDietType(user.dietType) ? user.dietType : DEFAULT_DIET_TYPE,
    gender: user.gender,
    activityLevel: user.activityLevel,
    activityMultiplier: user.activityMultiplier,
  });
  /** 開啟表單時，後端存的飲食型態已經不在選單裡——要講清楚我們替他換了什麼。 */
  const [replacedDietType, setReplacedDietType] = useState<string | null>(null);
  const [signOutConfirmVisible, setSignOutConfirmVisible] = useState(false);

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
        // 帳號還沒有檔案時要先建一份，否則其他 API 全部 404。
        //
        // 先前這裡送的是 seedUser——也就是 store 的預設值，而那組預設值是
        // constants/mock-data.ts 的示範人物「王小明」：175cm / 72kg / 高血壓 /
        // 對花生與蝦蟹過敏。結果每個新帳號一開好就帶著一個沒人說過的診斷，
        // 而每日熱量目標、單餐鈉上限、店家排序全部吃那一欄。
        //
        // 現在建的是一份明確空白的檔案：疾病與過敏原一定是空陣列，身體數值
        // 用中性起始值，並標記 profile_complete: false 讓畫面去要求使用者確認。
        return saveUserProfile(apiBaseUrl, {
          user_id: seedUser.userId,
          name: seedUser.name || (seedUser.email || '').split('@')[0] || '新使用者',
          gender: NEW_USER_PROFILE.gender,
          weight: NEW_USER_PROFILE.weight,
          height: NEW_USER_PROFILE.height,
          age: NEW_USER_PROFILE.age,
          activity_level: NEW_USER_PROFILE.activityLevel,
          activity_multiplier: NEW_USER_PROFILE.activityMultiplier,
          health_conditions: [],
          allergens: [],
          target_weight: null,
          diet_type: NEW_USER_PROFILE.dietType,
          profile_complete: false,
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
          targetWeight: data.target_weight || 0,
          dietType: data.diet_type,
          // `!== false` 而不是 Boolean()：profile_complete 是後加的欄位，
          // 線上後端落後一版時整個欄位會是 undefined。判不出來的時候要當成
          // 「填過了」，不然既有帳號會被說「這些還不是你的資料」並被強制
          // 打開表單——誤判的代價是不對稱的，寧可少問一次。
          profileComplete: data.profile_complete !== false,
          // 這兩個不在 /user 的回應裡，要沿用 store 目前的值。
          // 用 seedUser（mount 當下的快照）會蓋掉 setActivityStats 剛算好的數字：
          // 兩個請求誰先回是不一定的，實測就出現過連續天數被打回 0。
          streak: useStore.getState().user.streak,
          totalMeals: useStore.getState().user.totalMeals,
        });
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(describeRequestError(err, '無法載入健康檔案'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiBaseUrl, replaceUser, user.userId]);

  /**
   * 「連續 N 天」與「累積 N 餐」要從實際紀錄算。
   *
   * 先前這兩個數字來自 constants/mock-data.ts 的 `streak: 14` / `totalMeals: 187`，
   * 而 streak 從來沒有被真實資料覆蓋過——今天才註冊、只有一筆紀錄的帳號
   * 照樣顯示「連續 14 天」。
   */
  /**
   * 重新向後端要每日目標與活動統計。
   *
   * 存完健康檔案之後也要跑一次：每日熱量基準、身高體重、疾病條件都會改變
   * 生效的目標，而畫面上的「每日目標」與「飲食目標」分頁的一致性檢查都讀
   * 這個數字。先前只在 mount 時抓一次——改完體重存檔，卡片上還是舊的目標，
   * 而那個舊目標正好是用來判斷「跟目標體重方向一致嗎」的輸入。
   */
  const refreshTargets = useCallback(async () => {
    // 沒有 accessToken 也要問。首頁（app/(tabs)/index.tsx）就是無條件抓的，
    // 先前這裡多一道 `if (!accessToken) return`，於是本機／Demo 模式下首頁
    // 顯示後端算的目標、「我的」頁顯示 store 的預設值，同一個數字兩個答案。
    try {
      const { records, targets, goalTypes, basis } =
        await fetchAllRecordsWithTargets(apiBaseUrl, user.userId, { accessToken });
      setActivityStats(calculateActivityStats(records));
      applyNutritionTargets(targets, goalTypes, basis);
    } catch {
      // 這些數字只是輔助資訊，抓不到就維持現狀，不要用錯誤蓋掉整頁。
    }
  }, [accessToken, apiBaseUrl, applyNutritionTargets, setActivityStats, user.userId]);

  useEffect(() => {
    void refreshTargets();
  }, [refreshTargets]);

  useEffect(() => {
    const knownDiet = isKnownDietType(user.dietType);
    setProfileDraft({
      name: user.name,
      height: String(user.height),
      weight: String(user.weight),
      age: String(user.age),
      dailyCalorieTarget: String(user.dailyCalorieTarget),
      targetWeight: String(user.targetWeight || ''),
      dietType: isKnownDietType(user.dietType) ? user.dietType : DEFAULT_DIET_TYPE,
      gender: user.gender,
      activityLevel: user.activityLevel,
      activityMultiplier: user.activityMultiplier,
    });
    setReplacedDietType(knownDiet ? null : user.dietType || null);
  }, [user.name, user.height, user.weight, user.age, user.dailyCalorieTarget, user.targetWeight, user.dietType, user.gender, user.activityLevel, user.activityMultiplier]);

  /**
   * 還沒填過的檔案要主動把表單打開。
   *
   * 不這樣做的話，畫面上那組起始預設值看起來就跟使用者自己填的一樣，
   * 而它會一路變成每日目標與單餐上限。
   */
  useEffect(() => {
    // error 一定要看：載入失敗時 user 還是 store 的起始預設值，這時候把表單
    // 打開等於請使用者按下「用預設值覆蓋我後端的真實檔案」。
    if (!loading && !error && !user.profileComplete) setProfileModalVisible(true);
  }, [loading, error, user.profileComplete]);

  /**
   * Esc 關閉編輯視窗。
   *
   * RN 的 Modal 有 onRequestClose，但在 react-native-web 上它只對 Android 的
   * 返回鍵有反應——網頁上按 Esc 是沒有用的，只能用滑鼠點那個小叉叉。
   */
  useEffect(() => {
    if (Platform.OS !== 'web' || typeof document === 'undefined') return;
    if (!profileModalVisible && !signOutConfirmVisible) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setSignOutConfirmVisible(false);
      setProfileModalVisible(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [profileModalVisible, signOutConfirmVisible]);

  /**
   * 安全條件的儲存必須排隊，而且要送出當下 store 的最新狀態。
   *
   * 先前是 `void syncProfile({ ...user, ... })`：連續勾兩個病症會同時發出兩個
   * 寫入，誰先到後端不一定（Render 冷啟動延遲差到幾秒），晚到的舊 payload 會
   * 把後來勾的那個蓋掉；而且 payload 是用當次 render 的 user 算的，不是 store
   * 的最新值。畫面永遠顯示兩個都勾了，後端卻少一個——少一個病症就等於那整組
   * 禁忌規則沒套用。
   */
  const profileSyncChain = useRef<Promise<void>>(Promise.resolve());

  /**
   * 勾／取消一個疾病或過敏原，並且在後端沒收到時把畫面改回去。
   *
   * 先前失敗只會在上面顯示一行「同步失敗」，chip 照樣是亮的——畫面說你已經
   * 勾了高血壓，後端的檔案裡沒有，而整組鈉的禁忌規則是照後端的檔案跑的。
   * 這比看不到任何東西更危險，因為使用者會以為已經設定好了。
   *
   * 這條路徑現在比以前容易踩到：身高體重年齡加了合理範圍之後，一個早年存進
   * 去的離譜數值會讓「整份檔案」的寫入被退回，即使這次只是想勾一個疾病。
   */
  const applySafetySelection = (mutate: () => void) => {
    const before = useStore.getState().user;
    mutate();
    profileSyncChain.current = profileSyncChain.current
      .catch(() => {})
      .then(async () => {
        const saved = await syncProfile(useStore.getState().user);
        if (saved) return;
        const current = useStore.getState().user;
        replaceUser({
          ...current,
          healthConditions: before.healthConditions,
          allergens: before.allergens,
        });
      });
    return profileSyncChain.current;
  };

  const thresholdConflicts = medicalMetadata?.threshold_conflicts ?? [];

  /** 回傳後端是否真的收下了——呼叫端要據此決定畫面要不要改回去。 */
  const syncProfile = async (nextUser = user): Promise<boolean> => {
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
        target_weight: nextUser.targetWeight || null,
        diet_type: nextUser.dietType,
        profile_complete: nextUser.profileComplete,
      }, { accessToken });

      replaceUser({
        ...nextUser,
        bmi: response.user.bmi,
        bmr: response.user.bmr,
        tdee: response.user.tdee,
        dailyCalorieTarget: response.user.daily_calorie_target,
        dietType: response.user.diet_type,
        profileComplete: response.user.profile_complete !== false,
      });
      setError(null);
      await refreshTargets();
      return true;
    } catch (err: any) {
      const message = describeRequestError(err);
      // 後端退回身體數值時，出問題的欄位不在這一頁上——要講去哪裡改。
      const needsProfileEdit = /身高|體重|年齡|目標體重|每日熱量基準/.test(message);
      setError(needsProfileEdit ? `${message}請按「編輯資料」修正後再試。` : message);
      return false;
    } finally {
      setSaving(false);
    }
  };

  const updateDraft = <K extends keyof typeof profileDraft>(key: K, value: (typeof profileDraft)[K]) => {
    setProfileDraft((draft) => ({ ...draft, [key]: value }));
  };

  const parsePositiveNumber = (value: string, fallback: number) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };

  /**
   * 合理範圍由後端提供（/medical-metadata 的 profile_limits），拿不到才用本地退路。
   *
   * 先前前後端都只檢查「大於 0」：身高 1cm、體重 1kg、年齡 1 歲全部存得進去，
   * 而這些值會直接餵進 BMR/TDEE/BMI，再變成每日目標與單餐上限。
   */
  const profileLimits: Record<string, ProfileLimit> = medicalMetadata?.profile_limits || PROFILE_LIMITS;

  /** 表單欄位 → 後端 profile_limits 的鍵。 */
  const LIMIT_KEY_BY_FIELD: Record<string, string> = {
    height: 'height',
    weight: 'weight',
    age: 'age',
    targetWeight: 'target_weight',
    dailyCalorieTarget: 'daily_calorie_target',
  };

  const isDraftFieldValid = (field: string) => {
    if (field === 'name') return profileDraft.name.trim().length > 0;
    const limitKey = LIMIT_KEY_BY_FIELD[field];
    return isWithinLimit(profileLimits[limitKey], profileDraft[field as keyof typeof profileDraft] as string);
  };

  const invalidNumericField = Object.keys(LIMIT_KEY_BY_FIELD).find((field) => !isDraftFieldValid(field));

  const isProfileDraftValid =
    profileDraft.name.trim().length > 0 &&
    !invalidNumericField &&
    isKnownDietType(profileDraft.dietType);

  // 儲存鈕先前只是變灰，畫面上沒有任何一句話說為什麼；就算有，那句話也只說
  // 「都要大於 0」，不會告訴你是哪一格、範圍是多少。
  const profileDraftProblem = isProfileDraftValid
    ? null
    : !profileDraft.name.trim()
      ? '請填寫姓名或暱稱。'
      : !isKnownDietType(profileDraft.dietType)
        ? '請在下方選一個飲食型態。'
        : invalidNumericField
          ? `${describeLimit(profileLimits[LIMIT_KEY_BY_FIELD[invalidNumericField]] || PROFILE_LIMITS[LIMIT_KEY_BY_FIELD[invalidNumericField]])}。`
          : null;

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

  // 選項由後端提供，前端不再自己抄一份，免得兩邊數字慢慢走鐘
  const activityLevels = medicalMetadata?.activity_levels?.length
    ? medicalMetadata.activity_levels
    : [
        { id: 'sedentary', label_zh: '久坐（幾乎不運動）', multiplier: 1.2 },
        { id: 'light', label_zh: '輕度活動（每週 1-3 天）', multiplier: 1.375 },
        { id: 'moderate', label_zh: '中等活動（每週 3-5 天）', multiplier: 1.55 },
        { id: 'active', label_zh: '高度活動（每週 6-7 天）', multiplier: 1.725 },
        { id: 'very_active', label_zh: '極高活動（勞力工作或每日訓練）', multiplier: 1.9 },
      ];

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
      gender: profileDraft.gender,
      activityLevel: profileDraft.activityLevel,
      activityMultiplier: profileDraft.activityMultiplier,
      // 這一刻起這份檔案才是使用者自己填的。
      profileComplete: true,
    };

    await syncProfile(nextUser);
    setReplacedDietType(null);
    setProfileModalVisible(false);
    setProfileFeedback({ tone: 'success', title: '健康檔案已更新', message: '個人資料已同步到後端。' });
  };

  const performSignOut = async () => {
    if (!isSupabaseAuthConfigured || !supabase) {
      setProfileFeedback({ tone: 'error', title: 'Demo 模式', message: '目前未啟用 Supabase Auth，無法登出。' });
      return;
    }
    const supabaseClient = supabase;

    setSigningOut(true);
    try {
      const { error: signOutError } = await supabaseClient.auth.signOut();
      if (signOutError) throw signOutError;
      useStore.getState().setAuthSession(null);
    } catch (err: any) {
      setProfileFeedback({ tone: 'error', title: '登出失敗', message: err?.message || '無法登出。' });
    } finally {
      setSigningOut(false);
    }
  };

  const runSeedAction = async (
    busyKey: 'index' | 'rebuild' | 'list',
    action: () => Promise<{ tone: 'success' | 'error'; title: string; message?: string }>
  ) => {
    setSeedBusy(busyKey);
    setProfileFeedback(null);
    try {
      setProfileFeedback(await action());
      invalidateDietaryRecords();
    } catch (err: any) {
      setProfileFeedback({ tone: 'error', title: '測試資料操作失敗', message: err?.message || '請確認後端連線與登入狀態。' });
    } finally {
      setSeedBusy(null);
    }
  };

  // 先前這裡讀 constants/mock-data.ts 的 DIET_GOALS，那是一組寫死的假資料：
  // 不管使用者是誰都顯示「2,100 kcal／目標體重 70kg／每日 4 餐／16:8 間歇性」。
  // 只留真的存在於使用者檔案裡的欄位，捏造的那幾項直接拿掉。
  const calorieTargetExplanation = describeCalorieTarget(nutritionTargetBasis);
  const userTargetNote = describeUserTargetFallback(nutritionTargetBasis);

  // BMI 那張卡片先前的顏色是寫死的橘色：20.3（標準）跟 35 長得一模一樣，
  // 而且只有一個數字，分級要讀者自己查表。
  const displayName = user.name.trim() || (user.email || '').split('@')[0] || '';

  const bmi = bmiCategory(user.bmi);
  const bmiAccent = bmi.tone === 'normal'
    ? Palette.accent.green
    : bmi.tone === 'alert' ? Palette.status.error : Palette.accent.orange;

  // 目標體重先前只是顯示出來而已——後端也只是存進去再讀出來，沒有任何
  // 計算用到它，所以「增重 20kg」配上一個赤字目標也不會有人說話。
  // 每日目標是後端給的；還沒回來時是 0，拿 0 去比對會生出一則假的矛盾提示
  // （「每日目標 0 kcal 比你的 TDEE 少 2,133 kcal」）。
  const weightGoal = nutritionTargetsReady
    ? readWeightGoal(
        user.weight,
        user.targetWeight,
        dailyNutrition.calories.target,
        user.tdee,
        nutritionTargetBasis?.source === 'disease',
      )
    : null;

  const dietGoals = [
    {
      label: '每日目標熱量',
      value: nutritionTargetsReady ? `${formatCalories(dailyNutrition.calories.target)} kcal` : '讀取中…',
      color: '#FB923C',
    },
    {
      label: '目標體重',
      value: user.targetWeight ? `${user.targetWeight} kg` : '未設定',
      color: '#4ADE80',
    },
    { label: '飲食計畫', value: user.dietType || '未設定', color: '#60A5FA' },
    { label: '目前體重', value: `${user.weight} kg`, color: '#A78BFA' },
  ];

  const handleIndexVenues = () =>
    runSeedAction('index', async () => {
      // 之前沒送座標，後端就用預設的台北 101，建的是那裡的店而不是你附近的
      const location = await resolveLocation();
      const summary = await indexNearbyVenues(
        apiBaseUrl,
        user.userId,
        { budget: 150, lat: location.lat, lng: location.lng },
        { accessToken }
      );
      const rest = summary.remaining ? `，還有 ${summary.remaining} 家沒建（再按一次繼續）` : '';
      return {
        tone: summary.analysed > 0 || summary.already_cached > 0 ? 'success' : 'error',
        title: `附近 ${summary.found} 家店：本次建檔 ${summary.analysed} 家，已建檔過 ${summary.already_cached} 家${rest}`,
        message: `${describeLocation(location)} 資料庫目前累積 ${summary.total_cached} 家店的菜單${summary.failed ? `，${summary.failed} 家分析失敗` : ''}。`,
      };
    });

  const handleListIndex = () =>
    runSeedAction('list', async () => {
      const result = await listNearbyVenueIndex(apiBaseUrl, user.userId, { accessToken });
      if (!result.count) {
        return { tone: 'error', title: '還沒有建檔任何店家', message: '按①開始建檔。' };
      }
      const names = result.venues.map((venue) =>
        `${venue.name}（${venue.items} 道${venue.stale ? '・需更新' : ''}${venue.has_opening_hours ? '' : '・無營業時段'}）`
      );
      return {
        tone: 'success',
        title: `已建檔 ${result.count} 家店，${result.stale} 家需更新，${result.without_opening_hours} 家沒有營業時段`,
        message: names.join('、'),
      };
    });

  const handleRebuildIndex = () =>
    runSeedAction('rebuild', async () => {
      const result = await clearNearbyVenueIndex(apiBaseUrl, user.userId, { accessToken });
      return {
        tone: 'success',
        title: result.removed > 0 ? `已清除 ${result.removed} 家店的菜單檔案` : '菜單檔案本來就是空的',
        message: '按①重新建檔，這次會照現在的規則來：已歇業的店不收，並記下每家店的營業時段。',
      };
    });

  const handleSignOut = () => {
    setProfileFeedback(null);
    if (!isSupabaseAuthConfigured || !supabase) {
      setProfileFeedback({ tone: 'error', title: 'Demo 模式', message: '目前未啟用 Supabase Auth，無法登出。' });
      return;
    }

    // 網頁先前用的是 window.confirm——一個跟整個 App 完全脫節的系統對話框，
    // 而且在 iframe、內嵌瀏覽器與部分隱私設定下會被直接擋掉（回傳 false），
    // 使用者按了登出卻什麼事都不會發生。改用 App 自己的對話框。
    if (Platform.OS === 'web') {
      setSignOutConfirmVisible(true);
      return;
    }

    Alert.alert('登出 NutriLens', '確定要登出嗎？', [
      { text: '取消', style: 'cancel' },
      { text: '登出', style: 'destructive', onPress: () => { void performSignOut(); } },
    ]);
  };

  /**
   * 只在真的有事發生時才出現。
   *
   * 先前閒置時常駐一句「健康條件與過敏原會同步到後端」——那是講給開發者
   * 聽的，使用者不需要知道資料存在哪裡，而一條永遠在的橫幅會讓真正該被
   * 看見的「同步失敗」看起來跟平常一樣。
   */
  const savingMessage = useMemo(() => {
    if (loading) return '載入健康檔案中';
    if (saving) return '同步中';
    if (error) return `同步失敗：${error}`;
    return null;
  }, [error, loading, saving]);

  /**
   * 載入失敗時，畫面上的身高體重與每日目標都是 store 的起始預設值。
   *
   * 先前只寫一句「同步失敗」，旁邊照樣有三張寫著具體數字的卡片——使用者會
   * 以為那是他的資料，只是這次沒存上去。
   */
  const showingFallbackNumbers = Boolean(error) && !user.profileComplete;

  return (
    <AppContainer>
      {/* 徽章先前只看「有沒有設定 Supabase」，不看有沒有真的登入：session 過期
          之後畫面照樣寫「Auth 已登入」，而下面每一次同步都會 401。 */}
      <ScreenHeader
        title="我的健康檔案"
        subtitle="管理身體資料、飲食目標、疾病條件與過敏原。"
        badge={!isSupabaseAuthConfigured ? 'Demo 模式' : isAuthenticated ? 'Auth 已登入' : '尚未登入'}
        badgeTone={isSupabaseAuthConfigured && isAuthenticated ? 'success' : 'warning'}
      />

      {profileFeedback ? (
        <FeedbackBanner
          tone={profileFeedback.tone}
          title={profileFeedback.title}
          message={profileFeedback.message}
          onDismiss={() => setProfileFeedback(null)}
        />
      ) : null}

      {savingMessage ? (
        <View style={[styles.syncBanner, error && styles.syncWarning]}>
          {loading || saving ? <ActivityIndicator size="small" color={Palette.accent.green} /> : <Ionicons name="cloud-offline-outline" size={16} color={Palette.status.warning} />}
          <Text style={[styles.syncText, error && styles.syncWarningText]}>
            {savingMessage}
            {showingFallbackNumbers ? '下面顯示的是預設值，不是你的資料。' : ''}
          </Text>
        </View>
      ) : null}

      {!isDesktop ? <SegmentedControl options={PROFILE_SECTIONS} value={activeSection} onChange={setActiveSection} /> : null}

      <View style={isDesktop ? styles.desktopColumns : styles.mobileSectionContent}>
      {isDesktop || activeSection === 'personal' ? (
      <View style={isDesktop ? styles.desktopPane : undefined}>
        {/* name 在起始檔案裡是空字串（載入失敗時也還是空的），先前這裡會渲染出
            一個沒有字母的圓圈加兩行空白，看起來像畫面壞了。 */}
        <View style={styles.accountCard}>
          <View style={styles.avatar}>
            {displayName ? (
              <Text style={styles.avatarInitial}>{displayName.slice(0, 1).toUpperCase()}</Text>
            ) : (
              <Ionicons name="person-outline" size={30} color={Palette.accent.green} />
            )}
          </View>
          <View style={styles.accountCopy}>
            <Text style={styles.userName}>{displayName || '尚未設定名稱'}</Text>
            {user.email ? <Text style={styles.userEmail}>{user.email}</Text> : null}
            <View style={styles.badgeRow}>
              <DataPill tone="success">連續 {user.streak} 天</DataPill>
              <DataPill tone="info">累積 {user.totalMeals} 餐</DataPill>
            </View>
          </View>
        </View>

        {/*
          先前這裡放的是 TDEE，但整個 App 實際採用的是疾病指引算出來的目標，
          兩個數字不一樣又都沒有說明，使用者看到的就是「我的」頁寫 2570、
          首頁寫 1590。這裡直接顯示生效的那一個，TDEE 移到下面的基本資料列。
        */}
        <View style={styles.metricRow}>
          <MetricCard label="BMR" value={user.bmr} unit="kcal" accent={Palette.accent.blue} />
          <MetricCard
            label="每日目標"
            value={nutritionTargetsReady ? Math.round(dailyNutrition.calories.target) : '—'}
            unit={nutritionTargetsReady ? 'kcal' : undefined}
            accent={Palette.accent.green}
          />
          <MetricCard label="BMI" value={user.bmi} accent={bmiAccent} caption={bmi.label} />
        </View>

        {calorieTargetExplanation ? (
          <View style={styles.targetExplainCard}>
            <Ionicons name="information-circle-outline" size={16} color={Palette.text.tertiary} />
            <View style={styles.targetExplainCopy}>
              <Text style={styles.targetExplainText}>{calorieTargetExplanation}</Text>
              {userTargetNote ? <Text style={styles.targetExplainMuted}>{userTargetNote}</Text> : null}
            </View>
          </View>
        ) : null}

        {/* 還沒填過的檔案裡，上面那些數字都是起始預設值，不是任何人填的。
            不講清楚的話，使用者會以為 App 已經知道他的身體狀況。 */}
        {!loading && !error && !user.profileComplete ? (
          <View style={styles.onboardingCard}>
            <Ionicons name="alert-circle-outline" size={18} color={Palette.status.warning} />
            <View style={styles.onboardingCopy}>
              <Text style={styles.onboardingTitle}>還沒填寫你的基本資料</Text>
              <Text style={styles.onboardingText}>
                上面的身高、體重、年齡與 BMR 目前是起始預設值，不是你的資料。
                填完之後每日熱量目標與餐點篩選才會照你的身體狀況算。
              </Text>
            </View>
          </View>
        ) : null}

        <View style={styles.profileSetupCard}>
          <View style={styles.profileSetupCopy}>
            <Text style={styles.profileSetupTitle}>個人基本資料</Text>
            {/* 生理性別先前沒有出現在這一行，但它決定 BMR 用哪一條公式——
                同樣的身高體重，男女差 166 kcal，而畫面上看不出來套的是哪個。 */}
            <Text style={styles.profileSetupMeta}>
              {user.height}cm · {user.weight}kg · {user.age} 歲 · {user.gender === 'male' ? '男性' : '女性'} · {user.dietType}
            </Text>
            <Text style={styles.profileSetupMeta}>
              目標體重 {user.targetWeight ? `${user.targetWeight} kg` : '未設定'} · TDEE {formatCalories(user.tdee)} kcal（未計入疾病調整）
            </Text>
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
      <SectionBlock title="健康狀況管理" subtitle="影響附近店家排序與掃描風險提示。">
        <View style={styles.medicalDisclaimer}>
          <Ionicons name="medical-outline" size={16} color={Palette.status.warning} />
          <Text style={styles.medicalDisclaimerText}>{medicalMetadata?.medical_disclaimer || '疾病與營養提醒僅供健康管理參考，不可取代醫療專業建議。'}</Text>
        </View>

        {/* 規則檔簽核的門檻與程式公式算出來的不一致時，實際生效的是較嚴的那個。
            後端一直有算出這份清單，但從來沒顯示——選了病症的人有權知道系統
            執行的數字跟審閱過的檔案不同。 */}
        {thresholdConflicts.length ? (
          <View style={styles.thresholdConflictBox}>
            <View style={styles.thresholdConflictHeader}>
              <Ionicons name="shield-checkmark-outline" size={16} color={Palette.text.secondary} />
              <Text style={styles.thresholdConflictTitle}>
                {medicalMetadata?.threshold_conflict_note
                  || '疾病門檻採用規則檔與臨床公式中較嚴格的一組。'}
              </Text>
            </View>
          </View>
        ) : null}
        <View style={styles.conditionsGrid}>
          {conditionCatalog.map((cond) => {
            const isActive = isSelected(user.healthConditions, cond.id, [cond.label_zh]);
            const fallback = AVAILABLE_CONDITIONS.find((item) => item.id === cond.id);
            const accent = fallback?.color || Palette.accent.green;
            return (
              <Pressable
                key={cond.id}
                accessibilityRole="checkbox"
                accessibilityLabel={cond.label_zh}
                aria-checked={isActive}
                onPress={() => {
                  void applySafetySelection(() => toggleCondition(cond.id, [cond.label_zh]));
                }}
                style={[styles.conditionChip, isActive && styles.conditionChipActive]}
              >
                <View style={[styles.conditionIcon, isActive && { backgroundColor: `${accent}22` }]}>
                  <Ionicons name="medical-outline" size={18} color={isActive ? accent : Palette.text.tertiary} />
                </View>
                <View style={styles.conditionInfo}>
                  <Text style={[styles.conditionLabel, isActive && { color: accent }]}>{cond.label_zh}</Text>
                  <Text style={styles.conditionDesc}>{cond.description}</Text>
                  {/* 規則檔已經標明腎臟病需要依分期與抽血數值個人化，但程式套的是
                      固定門檻。選了它的人有權知道這件事，不能只寫在 JSON 裡。 */}
                  {cond.review_status === 'requires_clinical_personalization' ? (
                    <Text style={styles.conditionCaveat}>
                      ⚠ 此條件的門檻需由醫療人員依你的分期與抽血數值個人化，App 目前套用的是通用估算值。
                    </Text>
                  ) : null}
                </View>
                <Ionicons name={isActive ? 'checkmark-circle' : 'add-circle-outline'} size={22} color={isActive ? accent : Palette.text.tertiary} />
              </Pressable>
            );
          })}
        </View>
      </SectionBlock>

      <SectionBlock title="過敏原設定" subtitle="選取後會套用於掃描風險提示與店家篩選。">
        <View style={styles.allergenChipsWrap}>
          {allergenCatalog.map((allergen) => {
            const isActive = isSelected(user.allergens, allergen.id, [allergen.label_zh]);
            return (
              <Pressable
                key={allergen.id}
                accessibilityRole="checkbox"
                accessibilityLabel={allergen.label_zh}
                aria-checked={isActive}
                onPress={() => {
                  void applySafetySelection(() => toggleAllergen(allergen.id, [allergen.label_zh]));
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
      <SectionBlock title="飲食目標" subtitle="依你的身高體重與疾病條件計算。">
        <View style={styles.goalList}>
          {dietGoals.map((goal) => (
            <View key={goal.label} style={styles.goalItem}>
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

        {/* 目標體重先前只是被顯示出來。「目標 70kg／目前 50kg」配上一個比
            TDEE 少 235 kcal 的每日目標，畫面上一個字都沒提。 */}
        {weightGoal ? (
          <View style={[styles.targetExplainCard, weightGoal.conflict && styles.goalConflictCard]}>
            <Ionicons
              name={weightGoal.conflict ? 'warning-outline' : 'information-circle-outline'}
              size={16}
              color={weightGoal.conflict ? Palette.status.warning : Palette.text.tertiary}
            />
            <View style={styles.targetExplainCopy}>
              <Text style={[styles.targetExplainText, weightGoal.conflict && styles.goalConflictText]}>
                {weightGoal.summary}
              </Text>
              {weightGoal.conflict ? (
                <Text style={styles.goalConflictText}>{weightGoal.conflict}</Text>
              ) : null}
            </View>
          </View>
        ) : nutritionTargetsReady ? (
          <View style={styles.targetExplainCard}>
            <Ionicons name="information-circle-outline" size={16} color={Palette.text.tertiary} />
            <View style={styles.targetExplainCopy}>
              <Text style={styles.targetExplainMuted}>
                還沒設定目標體重。填了之後這裡會對照每日熱量目標，告訴你兩者方向是不是一致。
              </Text>
            </View>
          </View>
        ) : null}

        {calorieTargetExplanation ? (
          <View style={styles.targetExplainCard}>
            <Ionicons name="information-circle-outline" size={16} color={Palette.text.tertiary} />
            <View style={styles.targetExplainCopy}>
              <Text style={styles.targetExplainText}>{calorieTargetExplanation}</Text>
              {userTargetNote ? <Text style={styles.targetExplainMuted}>{userTargetNote}</Text> : null}
            </View>
          </View>
        ) : null}
      </SectionBlock>
      </View>
      ) : null}
      </View>

      <SectionBlock title="附近店家菜單" subtitle="建檔後，推薦才能逐道菜比對疾病禁忌與過敏原。">
        <View style={styles.seedActions}>
          <PrimaryButton
            label={seedBusy === 'index' ? '建檔中…' : '建立附近店家菜單檔案'}
            onPress={handleIndexVenues}
            disabled={seedBusy !== null}
          />
          <SecondaryButton
            label={seedBusy === 'list' ? '讀取中…' : '看已建檔的店家'}
            onPress={handleListIndex}
            disabled={seedBusy !== null}
          />
          <SecondaryButton
            label={seedBusy === 'rebuild' ? '清除中…' : '清除菜單檔案（重建用）'}
            onPress={handleRebuildIndex}
            disabled={seedBusy !== null}
          />
        </View>
        <Text style={styles.seedHint}>
Google Places 只給店名與位置，沒有菜色營養。建檔會請 Gemini 讀出菜單並估算營養，一家約 20~30 秒，可以重複按累積。已建檔且未過期的店家不會重複分析。沒有建檔的店家，推薦只能用店名比對，無法逐道菜篩選。
        </Text>
      </SectionBlock>

      {/* aria-label 要放在 Modal 上：react-native-web 會把多出來的 props 展開到
          那個帶著 role="dialog" 的節點，放在裡面的 View 上讀屏軟體讀不到。 */}
      <Modal
        visible={profileModalVisible}
        transparent
        animationType="fade"
        aria-label="編輯基本資料"
        onRequestClose={() => setProfileModalVisible(false)}
      >
        <View style={styles.modalLayer}>
          <Pressable style={styles.modalBackdrop} accessibilityLabel="關閉編輯視窗" onPress={() => setProfileModalVisible(false)} />
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
                  { key: 'name' as const, label: '姓名', keyboardType: 'default' as const, hint: undefined as string | undefined },
                  { key: 'height' as const, label: '身高 cm', keyboardType: 'numeric' as const, hint: undefined as string | undefined },
                  { key: 'weight' as const, label: '體重 kg', keyboardType: 'numeric' as const, hint: undefined as string | undefined },
                  { key: 'age' as const, label: '年齡', keyboardType: 'numeric' as const, hint: undefined as string | undefined },
                  {
                    key: 'dailyCalorieTarget' as const,
                    label: '每日熱量基準 kcal',
                    keyboardType: 'numeric' as const,
                    // 這個欄位先前叫「每日熱量」，改了會顯示儲存成功，但畫面上沒有一處會變──
                    // 有疾病條件時一律以臨床指引的目標為準。講清楚它什麼時候才生效。
                    hint: '沒有勾選疾病時採用這個數字；有疾病條件時以臨床指引的每日目標為準。',
                  },
                  {
                    key: 'targetWeight' as const,
                    label: '目標體重 kg',
                    keyboardType: 'numeric' as const,
                    hint: '「飲食目標」會拿它跟每日熱量目標對照，方向不一致時會提醒你。',
                  },
                ].map((field) => {
                  const invalid = !isDraftFieldValid(field.key);
                  // 無效時把合理範圍講出來，而不是只留一個紅框跟一顆灰掉的儲存鈕。
                  const limit = profileLimits[LIMIT_KEY_BY_FIELD[field.key]];
                  const hint = invalid && limit ? `${describeLimit(limit)}。` : field.hint;
                  return (
                    <View key={field.key} style={[styles.inputGroup, { width: gridCol2(Spacing.sm) }]}>
                      <Text style={styles.inputLabel}>{field.label}</Text>
                      <TextInput
                        value={profileDraft[field.key]}
                        onChangeText={(value) => updateDraft(field.key, value)}
                        keyboardType={field.keyboardType}
                        placeholderTextColor={Palette.text.muted}
                        accessibilityLabel={field.label}
                        // 先前無效值只有橘色外框，讀屏軟體與色覺障礙的使用者
                        // 只會遇到一個按不下去的儲存鍵，不知道是哪一格有問題。
                        aria-invalid={invalid}
                        style={[styles.profileInput, invalid && styles.profileInputInvalid]}
                      />
                      {hint ? <Text style={[styles.inputHint, invalid && styles.inputHintInvalid]}>{hint}</Text> : null}
                    </View>
                  );
                })}
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>生理性別</Text>
                <Text style={styles.inputHint}>用於計算基礎代謝率。</Text>
                <View style={styles.dietOptions}>
                  {([['male', '男性'], ['female', '女性']] as const).map(([value, label]) => {
                    const active = profileDraft.gender === value;
                    return (
                      <Pressable
                        key={value}
                        accessibilityRole="radio"
                        accessibilityLabel={label}
                        aria-checked={active}
                        onPress={() => updateDraft('gender', value)}
                        style={[styles.dietOption, active && styles.dietOptionActive]}
                      >
                        <Ionicons name={active ? 'checkmark-circle' : 'ellipse-outline'} size={18} color={active ? Palette.accent.green : Palette.text.tertiary} />
                        <Text style={[styles.dietOptionText, active && styles.dietOptionTextActive]}>{label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>運動量</Text>
                <Text style={styles.inputHint}>影響每日建議熱量與餐點推薦。</Text>
                <View style={styles.activityOptions}>
                  {activityLevels.map((level: { id: string; label_zh: string; multiplier: number }) => {
                    const active = profileDraft.activityMultiplier === level.multiplier;
                    return (
                      <Pressable
                        key={level.id}
                        accessibilityRole="radio"
                        accessibilityLabel={level.label_zh}
                        aria-checked={active}
                        onPress={() => {
                          updateDraft('activityLevel', level.label_zh);
                          updateDraft('activityMultiplier', level.multiplier);
                        }}
                        style={[styles.dietOption, active && styles.dietOptionActive]}
                      >
                        <Ionicons name={active ? 'checkmark-circle' : 'ellipse-outline'} size={18} color={active ? Palette.accent.green : Palette.text.tertiary} />
                        <Text style={[styles.dietOptionText, active && styles.dietOptionTextActive]}>
                          {level.label_zh}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>飲食類型</Text>
                <View style={styles.dietOptions}>
                  {DIET_TYPES.map((option) => {
                    const active = profileDraft.dietType === option;
                    return (
                      <Pressable
                        key={option}
                        accessibilityRole="radio"
                        accessibilityLabel={option}
                        aria-checked={active}
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

              {/* 舊帳號存的飲食型態已經不在選單裡時，不能默默換掉就算了。 */}
              {replacedDietType ? (
                <Text style={styles.inputHint}>
                  你先前存的「{replacedDietType}」已經不在選項裡，這裡先幫你選成「{DEFAULT_DIET_TYPE}」，
                  存檔前可以改。
                </Text>
              ) : null}

              {profileDraftProblem ? <Text style={styles.draftProblem}>{profileDraftProblem}</Text> : null}

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

      {/* 網頁版的登出確認。先前用 window.confirm，在 iframe 與部分隱私設定下
          會被瀏覽器直接擋掉並回傳 false——按了登出，什麼都不會發生。 */}
      <Modal
        visible={signOutConfirmVisible}
        transparent
        animationType="fade"
        aria-label="登出 NutriLens"
        onRequestClose={() => setSignOutConfirmVisible(false)}
      >
        <View style={styles.modalLayer}>
          <Pressable style={styles.modalBackdrop} accessibilityLabel="取消登出" onPress={() => setSignOutConfirmVisible(false)} />
          <View style={styles.confirmModal}>
            <Text style={styles.modalTitle}>登出 NutriLens</Text>
            <Text style={styles.modalSubtitle}>確定要登出嗎？健康檔案已經存在後端，下次登入還在。</Text>
            {/* 兩顆按鈕都是 width:'100%'，直接放進 row 會撐出卡片外面。 */}
            <View style={styles.confirmActions}>
              <View style={styles.confirmAction}>
                <SecondaryButton label="取消" onPress={() => setSignOutConfirmVisible(false)} />
              </View>
              <View style={styles.confirmAction}>
                <PrimaryButton
                  label={signingOut ? '登出中' : '登出'}
                  disabled={signingOut}
                  onPress={() => {
                    setSignOutConfirmVisible(false);
                    void performSignOut();
                  }}
                />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </AppContainer>
  );
}

const styles = StyleSheet.create({
  onboardingCard: {
    flexDirection: 'row',
    gap: Spacing.sm,
    alignItems: 'flex-start',
    backgroundColor: Palette.accent.orangeDim,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.28)',
    padding: Spacing.lg,
    marginBottom: Spacing.lg,
  },
  onboardingCopy: { flex: 1, gap: 2 },
  onboardingTitle: { ...Typography.caption, color: Palette.status.warning, fontWeight: '700' },
  onboardingText: { ...Typography.small, color: Palette.text.secondary, lineHeight: 18 },
  goalConflictCard: { backgroundColor: Palette.accent.orangeDim, borderColor: 'rgba(245,158,11,0.28)' },
  goalConflictText: { ...Typography.small, color: Palette.status.warning, lineHeight: 18 },
  confirmModal: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    padding: Spacing.xl,
    gap: Spacing.sm,
    ...Shadows.card,
  },
  confirmActions: { flexDirection: 'row', gap: Spacing.sm, marginTop: Spacing.md },
  confirmAction: { flex: 1, minWidth: 0 },
  inputHintInvalid: { color: Palette.status.error },
  draftProblem: {
    color: Palette.status.error,
    fontSize: 13,
    lineHeight: 19,
    marginBottom: Spacing.sm,
  },
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
  metricRow: { flexDirection: 'row', gap: Spacing.sm, marginBottom: Spacing.md },
  targetExplainCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.mint,
    borderRadius: Radius.md,
    padding: Spacing.md,
    marginBottom: Spacing.xl,
  },
  targetExplainCopy: { flex: 1, gap: 2 },
  targetExplainText: { ...Typography.small, color: Palette.text.secondary, lineHeight: 17 },
  targetExplainMuted: { ...Typography.small, color: Palette.text.tertiary, lineHeight: 17 },
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
  inputHint: { ...Typography.small, color: Palette.text.tertiary, marginBottom: Spacing.xs },
  activityOptions: { gap: Spacing.sm },
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
  profileInputInvalid: { borderColor: Palette.status.warning },
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
  thresholdConflictBox: {
    backgroundColor: Palette.accent.orangeDim,
    borderRadius: Radius.lg,
    borderLeftWidth: 3,
    borderLeftColor: Palette.status.warning,
    padding: Spacing.md,
    marginBottom: Spacing.md,
    gap: Spacing.xs,
  },
  thresholdConflictHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xs },
  thresholdConflictTitle: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700', flex: 1 },
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
  conditionCaveat: { ...Typography.small, color: Palette.status.warning, marginTop: Spacing.xs },
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
  seedActions: {
    gap: Spacing.sm,
  },
  seedHint: {
    ...Typography.caption,
    color: Palette.text.muted,
    marginTop: Spacing.sm,
    lineHeight: 18,
  },
  goalList: { gap: Spacing.md },
  goalItem: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md },
  goalIcon: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  goalEmoji: { fontSize: 17 },
  goalInfo: { flex: 1 },
  goalLabel: { ...Typography.caption, color: Palette.text.tertiary },
  goalValue: { ...Typography.bodyBold },
  accountActions: { gap: Spacing.md, marginBottom: Spacing.xl },
});
