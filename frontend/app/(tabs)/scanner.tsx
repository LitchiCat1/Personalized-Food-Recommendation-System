import React, { useState, useRef, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator, Keyboard, TextInput } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import type { DetectedFood } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import SegmentedControl from '@/components/ui/segmented-control';
import FeedbackBanner from '@/components/ui/feedback-banner';
import ScannerCameraView from '@/components/scanner/ScannerCameraView';
import ScannerManualTools from '@/components/scanner/ScannerManualTools';
import ScannerResults from '@/components/scanner/ScannerResults';
import {
  buildOCRDetectedFood,
  FOOD_NAME_REQUIRED_MESSAGE,
  manualSearchFood,
  normalizeFoodName,
  runNutritionLabelOCR,
  runPrediction,
  saveCustomFood,
  saveRecord,
  type OCRDraft,
  type RejectedDetection,
} from '@/lib/scanner';
import {
  canRetryPendingRecordSync,
  enqueuePendingRecordSync,
  loadPendingRecordSyncQueue,
  markPendingRecordSyncFailed,
  MAX_RECORD_SYNC_ATTEMPTS,
  removePendingRecordSync,
  removePendingRecordSyncByClientRecordId,
  type PendingRecordSync,
  type RecordSource,
} from '@/lib/recordSyncQueue';

type ScanMode = 'camera' | 'gallery' | 'label' | 'manual';

type RecordFeedback = {
  tone: 'success' | 'error';
  title: string;
  message: string;
};

type ActiveRecordSubmission = {
  key: string;
  source: RecordSource;
};

const SCAN_MODE_OPTIONS = [
  { value: 'camera', label: '拍照' },
  { value: 'gallery', label: '相簿' },
  { value: 'label', label: '營養標示' },
  { value: 'manual', label: '手動搜尋' },
];

function OCRDraftCard({
  draft,
  foodNameError,
  onFoodNameChange,
  onFoodNameBlur,
  onSaveCustomFood,
  onQuickAdd,
  submitting,
  actionsDisabled,
}: {
  draft: OCRDraft;
  foodNameError: string | null;
  onFoodNameChange: (value: string) => void;
  onFoodNameBlur: () => void;
  onSaveCustomFood: () => void;
  onQuickAdd: () => void;
  submitting: boolean;
  actionsDisabled: boolean;
}) {
  return (
    <SectionBlock title="營養標示辨識結果" subtitle="可直接加入今日紀錄，或儲存成自訂食品供下次搜尋。">
      {draft.brand ? (
        <View style={styles.ocrBrandRow}>
          <DataPill tone="info">{draft.brand}</DataPill>
        </View>
      ) : null}
      <View style={styles.ocrNameField}>
        <Text style={styles.ocrNameLabel}>食物名稱</Text>
        <TextInput
          value={draft.product_name || ''}
          onChangeText={onFoodNameChange}
          onBlur={onFoodNameBlur}
          onSubmitEditing={Keyboard.dismiss}
          placeholder="輸入食物名稱"
          placeholderTextColor={Palette.text.muted}
          selectionColor={Palette.accent.green}
          autoCorrect={false}
          autoCapitalize="none"
          autoComplete="off"
          returnKeyType="done"
          maxLength={80}
          editable={!actionsDisabled}
          accessibilityLabel="食物名稱"
          accessibilityHint={foodNameError || undefined}
          style={[
            styles.ocrNameInput,
            foodNameError && styles.ocrNameInputError,
            actionsDisabled && styles.controlDisabled,
          ]}
        />
        {foodNameError ? (
          <View style={styles.ocrNameErrorRow}>
            <Ionicons name="alert-circle-outline" size={15} color={Palette.status.error} />
            <Text style={styles.ocrNameErrorText} selectable>{foodNameError}</Text>
          </View>
        ) : null}
      </View>
      {draft.serving_size_g ? <Text style={styles.ocrMetaText}>每份 {draft.serving_size_g} g</Text> : null}
      <View style={styles.nutritionGrid}>
        {[
          { label: '熱量', value: draft.nutrition_per_serving?.calories ?? '--', unit: 'kcal', color: Palette.accent.green },
          { label: '蛋白質', value: draft.nutrition_per_serving?.protein ?? '--', unit: 'g', color: Palette.accent.blue },
          { label: '總碳水化合物', value: draft.nutrition_per_serving?.carbs ?? '--', unit: 'g', color: Palette.accent.orange },
          { label: '精緻糖', value: draft.nutrition_per_serving?.sugar ?? '--', unit: 'g', color: Palette.accent.orange },
          { label: '總脂肪', value: draft.nutrition_per_serving?.fat ?? '--', unit: 'g', color: Palette.accent.purple },
          { label: '飽和脂肪', value: draft.nutrition_per_serving?.saturated_fat ?? '--', unit: 'g', color: Palette.accent.purple },
          { label: '反式脂肪', value: draft.nutrition_per_serving?.trans_fat ?? '--', unit: 'g', color: Palette.status.error },
          { label: '膳食纖維', value: draft.nutrition_per_serving?.fiber ?? '--', unit: 'g', color: Palette.accent.cyan },
          { label: '鈉 (Sodium)', value: draft.nutrition_per_serving?.sodium ?? '--', unit: 'mg', color: Palette.accent.pink },
          { label: '鈣 (Calcium)', value: draft.nutrition_per_serving?.calcium ?? '--', unit: 'mg', color: Palette.accent.green },
          { label: '鐵 (Iron)', value: draft.nutrition_per_serving?.iron ?? '--', unit: 'mg', color: Palette.accent.blue },
        ].map((item) => (
          <View key={item.label} style={styles.nutritionItem}>
            <Text style={styles.nutritionLabel}>{item.label}</Text>
            <Text style={[styles.nutritionValue, { color: item.color }]}>
              {item.value}
              <Text style={styles.nutritionUnit}> {item.unit}</Text>
            </Text>
          </View>
        ))}
      </View>
      <View style={styles.ocrActions}>
        <SecondaryButton label="儲存成自訂食品" onPress={onSaveCustomFood} disabled={actionsDisabled} icon={<Ionicons name="bookmark-outline" size={15} color={Palette.accent.green} />} />
        <PrimaryButton
          label={submitting ? '儲存中' : '直接加入今日紀錄'}
          onPress={onQuickAdd}
          disabled={actionsDisabled}
          icon={submitting
            ? <ActivityIndicator size="small" color={Palette.text.inverse} />
            : <Ionicons name="add-circle-outline" size={18} color={Palette.text.inverse} />}
        />
      </View>
    </SectionBlock>
  );
}

function ManualResultsList({
  foods,
  onAddFood,
  submittingFoodId,
  actionsDisabled,
}: {
  foods: DetectedFood[];
  onAddFood: (food: DetectedFood) => void;
  submittingFoodId: string | null;
  actionsDisabled: boolean;
}) {
  if (foods.length === 0) return null;

  return (
    <SectionBlock title="手動搜尋結果" subtitle="以每 100g 營養資料顯示，加入後仍可在紀錄中校正。">
      <View style={styles.manualResultsWrap}>
        {foods.map((food) => (
          <View key={food.id} style={styles.manualFoodCard}>
            <View style={styles.manualFoodTop}>
              <View style={styles.manualFoodCopy}>
                <Text style={styles.manualFoodName}>{food.foodName}</Text>
                <Text style={styles.manualFoodHint}>每 100g · TFDA/自訂食品資料</Text>
              </View>
              <SecondaryButton
                label={submittingFoodId === food.id ? '儲存中' : '加入'}
                onPress={() => onAddFood(food)}
                disabled={actionsDisabled}
                icon={submittingFoodId === food.id
                  ? <ActivityIndicator size="small" color={Palette.accent.green} />
                  : undefined}
              />
            </View>
            <View style={styles.macroRow}>
              <Text style={styles.macro}>熱量 {food.nutrition.calories} kcal</Text>
              <Text style={styles.macro}>蛋白質 {food.nutrition.protein}g</Text>
              <Text style={styles.macro}>鈉 {food.nutrition.sodium}mg</Text>
            </View>
          </View>
        ))}
      </View>
    </SectionBlock>
  );
}

export default function ScannerScreen() {
  const insets = useSafeAreaInsets();
  const { rs, wp, isWeb, isDesktop } = useResponsive();
  const {
    scanResult,
    setScanResult,
    updateScanFoodWeight,
    clearScan,
    setScanning,
    addMealFromScan,
    apiBaseUrl,
    accessToken,
    isCameraActive,
    setCameraActive,
    user,
    invalidateDietaryRecords,
  } = useStore();
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const [manualQuery, setManualQuery] = useState('');
  const [manualResults, setManualResults] = useState<DetectedFood[]>([]);
  const [manualSearching, setManualSearching] = useState(false);
  const [rejectedDetections, setRejectedDetections] = useState<RejectedDetection[]>([]);
  const [ocrQuerying, setOcrQuerying] = useState(false);
  const [ocrDraft, setOcrDraft] = useState<OCRDraft | null>(null);
  const [ocrNameError, setOcrNameError] = useState<string | null>(null);
  const [scanMode, setScanMode] = useState<ScanMode>('camera');
  const [syncingRecord, setSyncingRecord] = useState(false);
  const [activeRecordSubmission, setActiveRecordSubmission] = useState<ActiveRecordSubmission | null>(null);
  const [recordFeedback, setRecordFeedback] = useState<RecordFeedback | null>(null);
  const [pendingRecordQueue, setPendingRecordQueue] = useState<PendingRecordSync[]>([]);
  const [isCameraReady, setCameraReady] = useState(false);
  const [isCapturing, setCapturing] = useState(false);
  const captureInFlightRef = useRef(false);
  const recordSubmitInFlightRef = useRef(false);
  const recordSyncInFlightRef = useRef(false);
  const recordClientIdsRef = useRef(new Map<string, string>());
  const ocrSubmissionKeyRef = useRef(buildSubmissionKey('nutrition-label'));

  const results = scanResult.detections;
  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);
  const userPendingRecords = pendingRecordQueue.filter((item) => item.userId === user.userId);
  const firstPendingRecord = userPendingRecords[0];
  const recordActionsDisabled = Boolean(activeRecordSubmission) || syncingRecord;
  const cameraRecordSubmitting = activeRecordSubmission?.source === 'camera';
  const ocrRecordSubmitting = activeRecordSubmission?.source === 'nutrition-label';
  const submittingManualFoodId = activeRecordSubmission?.source === 'manual'
    ? activeRecordSubmission.key.slice('manual:'.length)
    : null;

  const handleCamera = async () => {
    try {
      const isAvailable = await CameraView.isAvailableAsync();
      if (!isAvailable) {
        Alert.alert(
          '無法使用相機',
          isWeb
            ? '請使用支援相機的瀏覽器，並透過 HTTPS 或 localhost 開啟 NutriLens。你仍可改用相簿上傳。'
            : '此裝置沒有可用的相機，你仍可改用相簿上傳。'
        );
        return;
      }

      if (!permission?.granted) {
        const res = await requestPermission();
        if (!res.granted) {
          Alert.alert(
            '需要相機權限',
            res.canAskAgain
              ? '請允許 NutriLens 存取相機後再試一次。'
              : '相機權限已被封鎖，請到瀏覽器或系統設定中允許 NutriLens 使用相機。'
          );
          return;
        }
      }

      setCameraReady(false);
      setCameraActive(true);
    } catch (error: any) {
      Alert.alert('相機啟動失敗', error?.message || '請重新整理後再試，或改用相簿上傳。');
    }
  };

  const handlePrediction = async (imageBase64: string) => {
    const response = await runPrediction({
      apiBaseUrl,
      imageBase64,
      healthConditions: user.healthConditions,
      allergens: user.allergens,
      userId: user.userId,
      auth: { accessToken },
    });
    setRejectedDetections(response.rejectedDetections);
    if (response.detections.length > 0) {
      setScanResult(response.detections);
      setManualResults([]);
      return true;
    }
    return false;
  };

  const analyzeImage = async (imageBase64: string) => {
    setScanning(true);
    try {
      const ok = await handlePrediction(imageBase64);
      if (!ok) {
        clearScan();
        Alert.alert('未辨識到可記錄的食物', '請拍攝完整餐盤、保持光線充足，或改用相簿與手動搜尋。');
      }
      return ok;
    } catch (error: any) {
      setRejectedDetections([]);
      clearScan();
      Alert.alert('AI 辨識暫時不可用', error?.message || '請先使用手動搜尋加入餐點。');
      return false;
    } finally {
      setScanning(false);
    }
  };

  const takePicture = async () => {
    if (!cameraRef.current || !isCameraReady || captureInFlightRef.current) return;
    captureInFlightRef.current = true;
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.7,
        ...(isWeb ? { imageType: 'jpg' as const, scale: 0.8 } : {}),
      });
      setCameraActive(false);
      const imageBase64 = photo?.base64 || (isWeb ? photo?.uri : undefined);
      if (!imageBase64) {
        throw new Error('相機沒有回傳可辨識的圖片，請重新拍照。');
      }
      await analyzeImage(imageBase64);
    } catch (error: any) {
      setScanning(false);
      Alert.alert('拍照失敗', error?.message || '請再試一次，或改用相簿上傳。');
    } finally {
      captureInFlightRef.current = false;
      setCapturing(false);
    }
  };

  const handleGallery = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      base64: true,
      quality: 0.7,
    });

    if (result.canceled) return;
    const asset = result.assets[0];
    if (asset.base64) {
      await analyzeImage(asset.base64);
      return;
    }
    Alert.alert('圖片無法讀取', '請改選另一張圖片，或直接使用相機拍攝。');
  };

  const handleLabelOCRFromGallery = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      base64: true,
      quality: 0.9,
    });

    if (result.canceled) return;
    const asset = result.assets[0];
    if (!asset.base64) {
      Alert.alert('圖片無法讀取', '請改選另一張圖片');
      return;
    }

    setOcrQuerying(true);
    try {
      const draft = await runNutritionLabelOCR({ apiBaseUrl, imageBase64: asset.base64 });
      ocrSubmissionKeyRef.current = buildSubmissionKey('nutrition-label');
      setOcrDraft(draft);
      setOcrNameError(null);
      Alert.alert('營養標示已辨識', '你可以直接儲存成自訂食品，之後就不必重複輸入。');
    } catch (error: any) {
      Alert.alert('營養標示辨識失敗', error?.message || '請確認後端已設定 Gemini API key');
    } finally {
      setOcrQuerying(false);
    }
  };

  const handleManualSearch = async () => {
    const keyword = manualQuery.trim();
    if (!keyword) {
      Alert.alert('請輸入關鍵字', '例如：白飯、雞胸肉、花椰菜');
      return;
    }

    setManualSearching(true);
    try {
      const foods = await manualSearchFood({ apiBaseUrl, keyword, limit: 6, userId: user.userId, auth: { accessToken } });
      setManualResults(foods);
      if (foods.length === 0) {
        Alert.alert('查無結果', '請試試更短的關鍵字或常見食品名稱');
      }
    } catch {
      Alert.alert('搜尋失敗', '目前無法連線到食品資料庫');
    } finally {
      setManualSearching(false);
    }
  };

  const submitRecord = async ({
    foods,
    source,
    submissionKey,
    successTitle,
    successMessage,
    onSuccess,
  }: {
    foods: DetectedFood[];
    source: RecordSource;
    submissionKey: string;
    successTitle: string;
    successMessage: string;
    onSuccess: () => void;
  }) => {
    if (
      foods.length === 0
      || recordSubmitInFlightRef.current
      || recordSyncInFlightRef.current
    ) {
      return false;
    }

    recordSubmitInFlightRef.current = true;
    setActiveRecordSubmission({ key: submissionKey, source });
    setRecordFeedback(null);
    Keyboard.dismiss();

    const clientRecordId = getOrCreateClientRecordId(recordClientIdsRef.current, submissionKey);
    let recordSaved = false;

    try {
      await saveRecord({ apiBaseUrl, userId: user.userId, clientRecordId, foods, source, auth: { accessToken } });
      recordSaved = true;
      invalidateDietaryRecords();

      try {
        const nextQueue = await removePendingRecordSyncByClientRecordId(user.userId, clientRecordId);
        setPendingRecordQueue(nextQueue);
      } catch {
        // The backend write already succeeded. A stale local queue item is harmless
        // because client_record_id keeps later synchronization idempotent.
      }

      addMealFromScan(foods);
      onSuccess();
      recordClientIdsRef.current.delete(submissionKey);
      setRecordFeedback({ tone: 'success', title: successTitle, message: successMessage });
      return true;
    } catch (error: any) {
      if (recordSaved) {
        setRecordFeedback({
          tone: 'error',
          title: '紀錄已儲存，畫面更新失敗',
          message: '請重新整理畫面確認最新紀錄，請勿再次送出。',
        });
        return false;
      }

      const errorMessage = getRecordSubmitErrorMessage(error);
      try {
        const nextQueue = await enqueuePendingRecordSync({
          userId: user.userId,
          clientRecordId,
          foods,
          source,
          error: errorMessage,
        });
        setPendingRecordQueue(nextQueue);
      } catch {
        // The visible result remains available for an explicit retry even if
        // local persistence is unavailable.
      }

      setRecordFeedback({
        tone: 'error',
        title: '飲食紀錄新增失敗',
        message: `${errorMessage}。內容已保留，請再按一次加入重試。`,
      });
      return false;
    } finally {
      recordSubmitInFlightRef.current = false;
      setActiveRecordSubmission(null);
    }
  };

  const syncPendingRecords = useCallback(async (queue: PendingRecordSync[], options?: { manual?: boolean }) => {
    if (recordSubmitInFlightRef.current || recordSyncInFlightRef.current) return 0;
    const userQueue = queue.filter((item) => item.userId === user.userId);
    const retryableQueue = options?.manual ? userQueue : userQueue.filter(canRetryPendingRecordSync);
    if (retryableQueue.length === 0) return 0;

    recordSyncInFlightRef.current = true;
    setSyncingRecord(true);
    let syncedCount = 0;
    try {
      for (const item of retryableQueue) {
        try {
          await saveRecord({ apiBaseUrl, userId: item.userId, clientRecordId: item.clientRecordId, foods: item.foods, source: item.source, auth: { accessToken } });
          invalidateDietaryRecords();
          const nextQueue = await removePendingRecordSync(item.id);
          setPendingRecordQueue(nextQueue);
          syncedCount += 1;
        } catch (error: any) {
          const nextQueue = await markPendingRecordSyncFailed(item.id, error?.message || '後端暫時無法儲存這筆紀錄');
          setPendingRecordQueue(nextQueue);
          break;
        }
      }
    } finally {
      recordSyncInFlightRef.current = false;
      setSyncingRecord(false);
    }

    return syncedCount;
  }, [accessToken, apiBaseUrl, invalidateDietaryRecords, user.userId]);

  const retryPendingRecordSync = async () => {
    if (recordSubmitInFlightRef.current || recordSyncInFlightRef.current) return;
    setRecordFeedback(null);
    try {
      const syncedCount = await syncPendingRecords(pendingRecordQueue, { manual: true });

      if (syncedCount > 0) {
        setRecordFeedback({
          tone: 'success',
          title: '待同步紀錄已儲存',
          message: `${syncedCount} 筆餐點已寫入後端紀錄。`,
        });
        return;
      }

      const latestQueue = await loadPendingRecordSyncQueue();
      const latestPendingRecord = latestQueue.find((item) => item.userId === user.userId);
      if (latestPendingRecord) {
        setRecordFeedback({
          tone: 'error',
          title: '同步仍未完成',
          message: `${latestPendingRecord.error} 請稍後再試。`,
        });
      }
    } catch (error) {
      setRecordFeedback({
        tone: 'error',
        title: '同步仍未完成',
        message: `${getRecordSubmitErrorMessage(error)} 請稍後再試。`,
      });
    }
  };

  useFocusEffect(
    useCallback(() => {
      let active = true;
      loadPendingRecordSyncQueue().then((queue) => {
        if (!active) return;
        setPendingRecordQueue(queue);
        void syncPendingRecords(queue).catch(() => undefined);
      });
      return () => {
        active = false;
        setCameraActive(false);
      };
    }, [setCameraActive, syncPendingRecords])
  );

  const handleAddRecord = async () => {
    if (results.length === 0) return;
    const submissionKey = `camera:${scanResult.timestamp || results.map((food) => food.id).join(',')}`;
    await submitRecord({
      foods: results,
      source: 'camera',
      submissionKey,
      successTitle: '飲食紀錄已新增',
      successMessage: `${results.length} 項食物已加入今日紀錄。`,
      onSuccess: clearScan,
    });
  };

  const handleAddManualFood = async (food: DetectedFood) => {
    await submitRecord({
      foods: [food],
      source: 'manual',
      submissionKey: `manual:${food.id}`,
      successTitle: '飲食紀錄已新增',
      successMessage: `${food.foodName} 已以每 100g 份量加入今日紀錄。`,
      onSuccess: () => setManualResults((current) => current.filter((item) => item.id !== food.id)),
    });
  };

  const handleSaveCustomFood = async () => {
    const draft = getValidatedOCRDraft();
    if (!draft) return;
    try {
      const data = await saveCustomFood({ apiBaseUrl, userId: user.userId, draft, auth: { accessToken } });
      Alert.alert('自訂食品已儲存', `${data.food?.name_zh || draft.product_name} 之後可直接搜尋使用`);
    } catch (error: any) {
      Alert.alert('儲存失敗', error?.message || '請稍後再試');
    }
  };

  const handleQuickAddOCRFood = async () => {
    const draft = getValidatedOCRDraft();
    if (!draft) return;
    const food = buildOCRDetectedFood(draft);
    await submitRecord({
      foods: [food],
      source: 'nutrition-label',
      submissionKey: ocrSubmissionKeyRef.current,
      successTitle: '飲食紀錄已新增',
      successMessage: `${food.foodName} 已依包裝營養標示加入紀錄。`,
      onSuccess: () => {
        setOcrDraft(null);
        setOcrNameError(null);
      },
    });
  };

  const handleOCRFoodNameChange = (value: string) => {
    setOcrDraft((current) => current ? { ...current, product_name: value } : current);
    if (ocrNameError && normalizeFoodName(value)) {
      setOcrNameError(null);
    }
  };

  const handleOCRFoodNameBlur = () => {
    if (!ocrDraft) return;
    const foodName = normalizeFoodName(ocrDraft.product_name);
    if (!foodName) {
      setOcrNameError(FOOD_NAME_REQUIRED_MESSAGE);
      return;
    }
    setOcrDraft({ ...ocrDraft, product_name: foodName });
    setOcrNameError(null);
  };

  const getValidatedOCRDraft = (): OCRDraft | null => {
    if (!ocrDraft) return null;
    const foodName = normalizeFoodName(ocrDraft.product_name);
    if (!foodName) {
      setOcrNameError(FOOD_NAME_REQUIRED_MESSAGE);
      return null;
    }
    const normalizedDraft = { ...ocrDraft, product_name: foodName };
    setOcrDraft(normalizedDraft);
    setOcrNameError(null);
    return normalizedDraft;
  };

  if (isCameraActive) {
    return (
      <ScannerCameraView
        cameraRef={cameraRef}
        rs={rs}
        topInset={insets.top}
        isReady={isCameraReady}
        isCapturing={isCapturing}
        onClose={() => {
          setCameraReady(false);
          setCameraActive(false);
        }}
        onCapture={takePicture}
        onReady={() => setCameraReady(true)}
        onError={(message) => {
          setCameraReady(false);
          setCameraActive(false);
          Alert.alert('相機啟動失敗', message || '請確認權限後再試，或改用相簿上傳。');
        }}
      />
    );
  }

  const modeConfig = {
    camera: { icon: 'camera-outline' as const, title: '拍攝完整餐盤', hint: '保持光線充足並避免遮擋，拍攝後會立即送出 AI 分析。', action: '啟動相機', onPress: handleCamera },
    gallery: { icon: 'images-outline' as const, title: '從相簿選擇餐點', hint: '可使用已拍攝的餐點照片，不需要重新開啟相機。', action: '選擇餐點照片', onPress: handleGallery },
    label: { icon: 'document-text-outline' as const, title: '辨識包裝營養標示', hint: '選擇清晰的營養標示照片，可建立自訂食品或直接加入紀錄。', action: ocrQuerying ? '辨識中' : '選擇標示照片', onPress: handleLabelOCRFromGallery },
    manual: { icon: 'search-outline' as const, title: '從食品資料庫搜尋', hint: '辨識結果不確定時，可直接從 TFDA 與自訂食品中補上餐點。', action: '', onPress: handleManualSearch },
  }[scanMode];

  const captureWorkspace = (
    <>
      <SegmentedControl options={SCAN_MODE_OPTIONS} value={scanMode} onChange={(value) => setScanMode(value as ScanMode)} />
      <View style={styles.scanHero}>
        <View style={styles.scanIcon}>
          {scanResult.isScanning || ocrQuerying ? (
            <ActivityIndicator size="large" color={Palette.accent.green} />
          ) : results.length > 0 ? (
            <Ionicons name="checkmark-circle-outline" size={42} color={Palette.accent.green} />
          ) : (
            <Ionicons name={modeConfig.icon} size={42} color={Palette.accent.green} />
          )}
        </View>
        <Text style={styles.scanTitle}>{scanResult.isScanning ? '正在分析照片' : results.length > 0 ? `已辨識 ${results.length} 項食物` : modeConfig.title}</Text>
        <Text style={styles.scanHint}>{results.length > 0 ? `合計 ${totalCal} kcal，鈉 ${totalSodium}mg。請確認份量後加入。` : modeConfig.hint}</Text>
        {scanMode !== 'manual' ? (
          <PrimaryButton label={modeConfig.action} onPress={modeConfig.onPress} disabled={scanResult.isScanning || ocrQuerying} icon={<Ionicons name={modeConfig.icon} size={18} color={Palette.text.inverse} />} />
        ) : null}
        {results.length > 0 ? (
          <SecondaryButton label="清除辨識結果" onPress={clearScan} icon={<Ionicons name="trash-outline" size={16} color={Palette.text.secondary} />} />
        ) : null}
      </View>
    </>
  );

  const resultWorkspace = (
    <View style={styles.resultWorkspace}>
      <View style={styles.resultHeader}>
        <Text style={styles.sectionTitle}>辨識結果</Text>
        {results.length > 0 ? <DataPill tone="success">{results.length} 項</DataPill> : null}
      </View>
      <ScannerResults
        rs={rs}
        wp={wp}
        results={results}
        onAddRecord={handleAddRecord}
        onWeightChange={updateScanFoodWeight}
        submitting={cameraRecordSubmitting}
        disabled={recordActionsDisabled}
      />
      {ocrDraft ? (
        <OCRDraftCard
          draft={ocrDraft}
          foodNameError={ocrNameError}
          onFoodNameChange={handleOCRFoodNameChange}
          onFoodNameBlur={handleOCRFoodNameBlur}
          onSaveCustomFood={handleSaveCustomFood}
          onQuickAdd={handleQuickAddOCRFood}
          submitting={ocrRecordSubmitting}
          actionsDisabled={recordActionsDisabled}
        />
      ) : null}
      <ManualResultsList
        foods={manualResults}
        onAddFood={handleAddManualFood}
        submittingFoodId={submittingManualFoodId}
        actionsDisabled={recordActionsDisabled}
      />
    </View>
  );

  const safetyAndManual = (
    <>
      <View style={styles.conditionSummary}>
        <Ionicons name="shield-checkmark-outline" size={18} color={Palette.accent.green} />
        <View style={styles.conditionCopy}>
          <Text style={styles.conditionTitle}>安全條件已套用</Text>
          <Text style={styles.conditionText} numberOfLines={2}>疾病：{user.healthConditions.length ? user.healthConditions.join('、') : '未設定'} · 過敏原：{user.allergens.length ? user.allergens.join('、') : '未設定'}</Text>
        </View>
      </View>
      {scanMode === 'manual' ? (
        <ScannerManualTools rs={rs} manualQuery={manualQuery} onManualQueryChange={setManualQuery} manualSearching={manualSearching} onManualSearch={handleManualSearch} ocrQuerying={ocrQuerying} onOCRSearch={handleLabelOCRFromGallery} rejectedDetections={rejectedDetections} />
      ) : null}
    </>
  );

  return (
    <AppContainer keyboardShouldPersistTaps="handled">
      <ScreenHeader
        title="AI 食物辨識"
        subtitle="拍照、上傳相簿或掃描營養標示，系統會套用健康條件和過敏原做安全檢查。"
        badge="Gemini + TFDA"
        badgeTone="info"
      />

      {recordFeedback ? (
        <FeedbackBanner
          tone={recordFeedback.tone}
          title={recordFeedback.title}
          message={recordFeedback.message}
          onDismiss={() => setRecordFeedback(null)}
        />
      ) : null}

      {(syncingRecord || firstPendingRecord) ? (
        <View style={[styles.syncStatusCard, firstPendingRecord && styles.syncStatusWarning]}>
          {syncingRecord ? (
            <ActivityIndicator size="small" color={Palette.accent.green} />
          ) : (
            <Ionicons name="cloud-offline-outline" size={16} color={Palette.status.warning} />
          )}
          <View style={styles.syncStatusTextWrap}>
            <Text style={styles.syncStatusTitle}>
              {syncingRecord ? '正在同步飲食紀錄' : `有 ${userPendingRecords.length} 筆餐點尚未同步`}
            </Text>
            {firstPendingRecord ? (
              <Text style={styles.syncStatusMessage}>
                {firstPendingRecord.error}，已重試 {firstPendingRecord.attempts}/{MAX_RECORD_SYNC_ATTEMPTS} 次
              </Text>
            ) : null}
          </View>
          {firstPendingRecord && !syncingRecord ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="重試同步飲食紀錄"
              onPress={retryPendingRecordSync}
              style={styles.retryButton}
            >
              <Text style={styles.retryButtonText}>重試</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {isDesktop ? (
        <View style={styles.desktopColumns}>
          <View style={styles.desktopCapture}>{captureWorkspace}{safetyAndManual}</View>
          <View style={styles.desktopResults}>{resultWorkspace}</View>
        </View>
      ) : (
        <>{captureWorkspace}{resultWorkspace}{safetyAndManual}</>
      )}
    </AppContainer>
  );
}

function buildClientRecordId(): string {
  return `record_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function buildSubmissionKey(source: RecordSource): string {
  return `${source}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function getOrCreateClientRecordId(recordIds: Map<string, string>, submissionKey: string): string {
  const existingId = recordIds.get(submissionKey);
  if (existingId) return existingId;

  const clientRecordId = buildClientRecordId();
  recordIds.set(submissionKey, clientRecordId);
  return clientRecordId;
}

function getRecordSubmitErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message.trim() : '';
  if (/failed to fetch|network request failed|fetch failed|networkerror/i.test(message)) {
    return '目前無法連線到伺服器';
  }
  return (message || '目前無法儲存這筆飲食紀錄').replace(/[。.!?]+$/u, '');
}

const styles = StyleSheet.create({
  syncStatusCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  syncStatusWarning: { borderColor: 'rgba(245,158,11,0.26)', backgroundColor: Palette.accent.orangeDim },
  syncStatusTextWrap: { flex: 1 },
  syncStatusTitle: { ...Typography.caption, color: Palette.text.primary },
  syncStatusMessage: { ...Typography.small, color: Palette.text.tertiary },
  retryButton: {
    minHeight: 44,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
    justifyContent: 'center',
  },
  retryButtonText: { ...Typography.caption, color: Palette.status.warning },
  scanHero: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    padding: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.md,
    marginTop: Spacing.md,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.card,
  },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xl },
  desktopCapture: { flex: 1, minWidth: 0 },
  desktopResults: { flex: 1.08, minWidth: 0 },
  resultWorkspace: { minWidth: 0 },
  scanIcon: {
    width: 82,
    height: 82,
    borderRadius: 41,
    backgroundColor: Palette.bg.mint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scanTitle: { ...Typography.h2, color: Palette.text.primary, textAlign: 'center' },
  scanHint: { ...Typography.caption, color: Palette.text.secondary, textAlign: 'center' },
  conditionSummary: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm, backgroundColor: Palette.bg.card, borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.lg, padding: Spacing.md, marginBottom: Spacing.xl },
  conditionCopy: { flex: 1, gap: 2 },
  conditionTitle: { ...Typography.caption, color: Palette.text.primary },
  conditionText: { ...Typography.small, color: Palette.text.tertiary },
  resultHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  ocrBrandRow: { flexDirection: 'row', marginBottom: Spacing.md },
  ocrNameField: { minWidth: 0, gap: Spacing.xs, marginBottom: Spacing.md },
  ocrNameLabel: { ...Typography.caption, color: Palette.text.secondary },
  ocrNameInput: {
    width: '100%',
    minWidth: 0,
    minHeight: 48,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    ...Typography.body,
  },
  ocrNameInputError: { borderColor: Palette.status.error, backgroundColor: Palette.accent.pinkDim },
  ocrNameErrorRow: { minHeight: 20, flexDirection: 'row', alignItems: 'center', gap: Spacing.xs },
  ocrNameErrorText: { ...Typography.small, color: Palette.status.error, flex: 1 },
  controlDisabled: { opacity: 0.56 },
  ocrMetaText: { ...Typography.caption, color: Palette.text.tertiary, marginBottom: Spacing.md },
  nutritionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutritionItem: { flex: 1, minWidth: '30%', backgroundColor: Palette.bg.elevated, borderRadius: Radius.md, padding: Spacing.sm },
  nutritionLabel: { ...Typography.small, color: Palette.text.tertiary },
  nutritionValue: { ...Typography.caption, ...Typography.number },
  nutritionUnit: { ...Typography.small, color: Palette.text.tertiary },
  ocrActions: { gap: Spacing.sm, marginTop: Spacing.lg },
  manualResultsWrap: { gap: Spacing.md },
  manualFoodCard: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md, gap: Spacing.md },
  manualFoodTop: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  manualFoodCopy: { flex: 1 },
  manualFoodName: { ...Typography.bodyBold, color: Palette.text.primary },
  manualFoodHint: { ...Typography.small, color: Palette.text.tertiary },
  macroRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  macro: { ...Typography.small, color: Palette.text.secondary, backgroundColor: Palette.bg.card, borderRadius: Radius.full, paddingHorizontal: Spacing.sm, paddingVertical: 4 },
});
