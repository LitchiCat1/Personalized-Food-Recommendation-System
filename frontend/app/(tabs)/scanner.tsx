import React, { useState, useRef, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { SCANNER_DEMO_RESULTS } from '@/constants/mock-data';
import type { DetectedFood } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import ScannerCameraView from '@/components/scanner/ScannerCameraView';
import ScannerManualTools from '@/components/scanner/ScannerManualTools';
import ScannerResults from '@/components/scanner/ScannerResults';
import {
  buildOCRDetectedFood,
  manualSearchFood,
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
  type PendingRecordSync,
  type RecordSource,
} from '@/lib/recordSyncQueue';

function OCRDraftCard({
  draft,
  onSaveCustomFood,
  onQuickAdd,
}: {
  draft: OCRDraft;
  onSaveCustomFood: () => void;
  onQuickAdd: () => void;
}) {
  return (
    <SectionBlock title="營養標示辨識結果" subtitle="可直接加入今日紀錄，或儲存成自訂食品供下次搜尋。">
      <View style={styles.ocrHeader}>
        <Text style={styles.ocrProductName}>{draft.product_name || '未命名食品'}</Text>
        {draft.brand ? <DataPill tone="info">{draft.brand}</DataPill> : null}
      </View>
      {draft.serving_size_g ? <Text style={styles.ocrMetaText}>每份 {draft.serving_size_g} g</Text> : null}
      <View style={styles.nutritionGrid}>
        {[
          { label: '熱量', value: draft.nutrition_per_serving?.calories ?? '--', unit: 'kcal', color: Palette.accent.green },
          { label: '蛋白質', value: draft.nutrition_per_serving?.protein ?? '--', unit: 'g', color: Palette.accent.blue },
          { label: '碳水', value: draft.nutrition_per_serving?.carbs ?? '--', unit: 'g', color: Palette.accent.orange },
          { label: '脂肪', value: draft.nutrition_per_serving?.fat ?? '--', unit: 'g', color: Palette.accent.purple },
          { label: '鈉', value: draft.nutrition_per_serving?.sodium ?? '--', unit: 'mg', color: Palette.accent.pink },
          { label: '糖', value: draft.nutrition_per_serving?.sugar ?? '--', unit: 'g', color: Palette.accent.cyan },
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
        <SecondaryButton label="儲存成自訂食品" onPress={onSaveCustomFood} icon={<Ionicons name="bookmark-outline" size={15} color={Palette.accent.green} />} />
        <PrimaryButton label="直接加入今日紀錄" onPress={onQuickAdd} icon={<Ionicons name="add-circle-outline" size={18} color={Palette.text.inverse} />} />
      </View>
    </SectionBlock>
  );
}

function ManualResultsList({
  foods,
  onAddFood,
}: {
  foods: DetectedFood[];
  onAddFood: (food: DetectedFood) => void;
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
              <SecondaryButton label="加入" onPress={() => onAddFood(food)} />
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
  const { rs, wp, isWeb } = useResponsive();
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
  } = useStore();
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const [manualQuery, setManualQuery] = useState('');
  const [manualResults, setManualResults] = useState<DetectedFood[]>([]);
  const [manualSearching, setManualSearching] = useState(false);
  const [rejectedDetections, setRejectedDetections] = useState<RejectedDetection[]>([]);
  const [ocrQuerying, setOcrQuerying] = useState(false);
  const [ocrDraft, setOcrDraft] = useState<OCRDraft | null>(null);
  const [syncingRecord, setSyncingRecord] = useState(false);
  const [pendingRecordQueue, setPendingRecordQueue] = useState<PendingRecordSync[]>([]);

  const results = scanResult.detections;
  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);
  const userPendingRecords = pendingRecordQueue.filter((item) => item.userId === user.userId);
  const firstPendingRecord = userPendingRecords[0];

  const handleCamera = async () => {
    if (isWeb) {
      setScanResult(SCANNER_DEMO_RESULTS);
      return;
    }

    if (!permission?.granted) {
      const res = await requestPermission();
      if (!res.granted) {
        Alert.alert('需要相機權限', '請在設定中允許 NutriLens 存取相機');
        return;
      }
    }
    setCameraActive(true);
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

  const takePicture = async () => {
    if (!cameraRef.current) return;
    setScanning(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.7 });
      setCameraActive(false);

      if (photo?.base64) {
        try {
          const ok = await handlePrediction(photo.base64);
          if (ok) return;
        } catch (error: any) {
          Alert.alert('AI 辨識暫時不可用', error?.message || '請先使用手動搜尋加入餐點。');
        }
      }

      setRejectedDetections([]);
      clearScan();
    } catch {
      Alert.alert('拍照失敗', '請再試一次');
      setScanning(false);
    }
  };

  const handleGallery = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      base64: true,
      quality: 0.7,
    });

    if (result.canceled) return;
    setScanning(true);

    const asset = result.assets[0];
    if (asset.base64) {
      try {
        const ok = await handlePrediction(asset.base64);
        if (ok) return;
      } catch (error: any) {
        Alert.alert('AI 辨識暫時不可用', error?.message || '請先使用手動搜尋加入餐點。');
      }
    }

    setRejectedDetections([]);
    clearScan();
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
      setOcrDraft(draft);
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

  const persistRecord = async (foods: DetectedFood[], source: RecordSource, clientRecordId = buildClientRecordId()) => {
    setSyncingRecord(true);
    try {
      await saveRecord({ apiBaseUrl, userId: user.userId, clientRecordId, foods, source, auth: { accessToken } });
      return true;
    } catch (error: any) {
      const nextQueue = await enqueuePendingRecordSync({
        userId: user.userId,
        clientRecordId,
        foods,
        source,
        error: error?.message || '後端暫時無法儲存這筆紀錄',
      });
      setPendingRecordQueue(nextQueue);
      return false;
    } finally {
      setSyncingRecord(false);
    }
  };

  const syncPendingRecords = useCallback(async (queue: PendingRecordSync[], options?: { manual?: boolean }) => {
    const userQueue = queue.filter((item) => item.userId === user.userId);
    const retryableQueue = options?.manual ? userQueue : userQueue.filter(canRetryPendingRecordSync);
    if (retryableQueue.length === 0) return 0;

    setSyncingRecord(true);
    let syncedCount = 0;
    try {
      for (const item of retryableQueue) {
        try {
          await saveRecord({ apiBaseUrl, userId: item.userId, clientRecordId: item.clientRecordId, foods: item.foods, source: item.source, auth: { accessToken } });
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
      setSyncingRecord(false);
    }

    return syncedCount;
  }, [accessToken, apiBaseUrl, user.userId]);

  const retryPendingRecordSync = async () => {
    const syncedCount = await syncPendingRecords(pendingRecordQueue, { manual: true });

    if (syncedCount > 0) {
      Alert.alert('同步完成', `${syncedCount} 筆待同步餐點已寫入後端紀錄。`);
    }
  };

  useFocusEffect(
    useCallback(() => {
      let active = true;
      loadPendingRecordSyncQueue().then((queue) => {
        if (!active) return;
        setPendingRecordQueue(queue);
        void syncPendingRecords(queue);
      });
      return () => {
        active = false;
        setCameraActive(false);
      };
    }, [setCameraActive, syncPendingRecords])
  );

  const handleAddRecord = () => {
    if (results.length === 0) return;
    addMealFromScan(results);
    persistRecord(results, 'camera').then((ok) => {
      if (!ok) Alert.alert('已加入本機畫面', '後端同步失敗，請稍後在辨識頁重試。');
    });
    clearScan();
    Alert.alert('已加入', `${results.length} 項食物已加入今日紀錄`);
  };

  const handleAddManualFood = (food: DetectedFood) => {
    addMealFromScan([food]);
    persistRecord([food], 'manual').then((ok) => {
      if (!ok) Alert.alert('已加入本機畫面', '後端同步失敗，請稍後在辨識頁重試。');
    });
    Alert.alert('已加入今日紀錄', `${food.foodName} 已以每 100g 份量加入今日紀錄`);
  };

  const handleSaveCustomFood = async () => {
    if (!ocrDraft) return;
    try {
      const data = await saveCustomFood({ apiBaseUrl, userId: user.userId, draft: ocrDraft, auth: { accessToken } });
      Alert.alert('自訂食品已儲存', `${data.food?.name_zh || ocrDraft.product_name} 之後可直接搜尋使用`);
    } catch {
      Alert.alert('儲存失敗', '請稍後再試');
    }
  };

  const handleQuickAddOCRFood = () => {
    if (!ocrDraft) return;
    const food = buildOCRDetectedFood(ocrDraft);
    addMealFromScan([food]);
    persistRecord([food], 'nutrition-label').then((ok) => {
      if (!ok) Alert.alert('已加入本機畫面', '後端同步失敗，請稍後在辨識頁重試。');
    });
    Alert.alert('已加入今日紀錄', `${food.foodName} 已依包裝營養標示加入紀錄`);
  };

  if (isCameraActive && !isWeb) {
    return (
      <ScannerCameraView
        cameraRef={cameraRef}
        rs={rs}
        topInset={insets.top}
        onClose={() => setCameraActive(false)}
        onCapture={takePicture}
      />
    );
  }

  return (
    <AppContainer>
      <ScreenHeader
        title="AI 食物辨識"
        subtitle="拍照、上傳相簿或掃描營養標示，系統會套用健康條件和過敏原做安全檢查。"
        badge="Gemini + TFDA"
        badgeTone="info"
      />

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
            <Pressable onPress={retryPendingRecordSync} style={styles.retryButton}>
              <Text style={styles.retryButtonText}>重試</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      <View style={styles.scanHero}>
        <View style={styles.scanIcon}>
          {scanResult.isScanning ? (
            <ActivityIndicator size="large" color={Palette.accent.green} />
          ) : results.length > 0 ? (
            <Ionicons name="checkmark-circle-outline" size={42} color={Palette.accent.green} />
          ) : (
            <Ionicons name="scan-outline" size={42} color={Palette.accent.green} />
          )}
        </View>
        <Text style={styles.scanTitle}>
          {scanResult.isScanning ? '正在分析照片' : results.length > 0 ? `已辨識 ${results.length} 項食物` : '掃描餐點建立今日紀錄'}
        </Text>
        <Text style={styles.scanHint}>
          {results.length > 0 ? `合計 ${totalCal} kcal，鈉 ${totalSodium}mg。請確認份量後加入。` : '建議拍攝完整餐盤，避免反光與遮擋。'}
        </Text>
        <PrimaryButton label={isWeb ? '載入 Web Demo 結果' : '啟動相機掃描'} onPress={handleCamera} icon={<Ionicons name="camera-outline" size={18} color={Palette.text.inverse} />} />
        <View style={styles.secondaryActions}>
          <SecondaryButton label="相簿上傳" onPress={handleGallery} icon={<Ionicons name="images-outline" size={16} color={Palette.accent.blue} />} />
          <SecondaryButton label="清除結果" onPress={clearScan} icon={<Ionicons name="refresh-outline" size={16} color={Palette.text.secondary} />} />
        </View>
      </View>

      <SectionBlock title="健康條件套用" subtitle="辨識與推薦會使用這些條件做安全過濾。">
        <View style={styles.conditionRow}>
          <DataPill tone={user.healthConditions.length ? 'warning' : 'success'}>疾病：{user.healthConditions.length > 0 ? user.healthConditions.join('、') : '未設定'}</DataPill>
          <DataPill tone={user.allergens.length ? 'warning' : 'success'}>過敏原：{user.allergens.length > 0 ? user.allergens.join('、') : '未設定'}</DataPill>
        </View>
      </SectionBlock>

      <View style={styles.resultHeader}>
        <Text style={styles.sectionTitle}>辨識結果</Text>
        {results.length > 0 ? <DataPill tone="success">{results.length} 項</DataPill> : null}
      </View>
      <ScannerResults rs={rs} wp={wp} results={results} onAddRecord={handleAddRecord} onWeightChange={updateScanFoodWeight} />

      <ScannerManualTools
        rs={rs}
        manualQuery={manualQuery}
        onManualQueryChange={setManualQuery}
        manualSearching={manualSearching}
        onManualSearch={handleManualSearch}
        ocrQuerying={ocrQuerying}
        onOCRSearch={handleLabelOCRFromGallery}
        rejectedDetections={rejectedDetections}
      />

      {ocrDraft ? (
        <OCRDraftCard
          draft={ocrDraft}
          onSaveCustomFood={handleSaveCustomFood}
          onQuickAdd={handleQuickAddOCRFood}
        />
      ) : null}

      <ManualResultsList foods={manualResults} onAddFood={handleAddManualFood} />
    </AppContainer>
  );
}

function buildClientRecordId(): string {
  return `record_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
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
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.xs,
  },
  retryButtonText: { ...Typography.caption, color: Palette.status.warning },
  scanHero: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    padding: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.md,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.card,
  },
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
  secondaryActions: { flexDirection: 'row', gap: Spacing.sm, width: '100%' },
  conditionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  resultHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  ocrHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm, marginBottom: Spacing.xs },
  ocrProductName: { ...Typography.bodyBold, color: Palette.text.primary, flex: 1 },
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
