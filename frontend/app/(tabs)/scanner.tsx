import React, { useState, useRef, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useFocusEffect } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import { SCANNER_DEMO_RESULTS } from '@/constants/mock-data';
import type { DetectedFood } from '@/constants/mock-data';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
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

function OCRDraftCard({
  rs,
  wp,
  draft,
  onSaveCustomFood,
  onQuickAdd,
}: {
  rs: (value: number) => number;
  wp: (value: number) => number;
  draft: OCRDraft;
  onSaveCustomFood: () => void;
  onQuickAdd: () => void;
}) {
  return (
    <View style={[styles.manualCard, { padding: rs(16) }]}> 
      <View style={styles.manualHeader}>
        <Ionicons name="document-text" size={rs(16)} color={Palette.accent.green} />
        <Text style={[styles.manualTitle, { fontSize: rs(15) }]}>營養標示辨識結果</Text>
      </View>
      <Text style={[styles.ocrProductName, { fontSize: rs(15) }]}>{draft.product_name || '未命名食品'}</Text>
      {draft.brand ? <Text style={[styles.ocrMetaText, { fontSize: rs(11) }]}>品牌：{draft.brand}</Text> : null}
      {draft.serving_size_g ? <Text style={[styles.ocrMetaText, { fontSize: rs(11) }]}>每份：{draft.serving_size_g} g</Text> : null}
      <View style={styles.nutritionGrid}>
        {[
          { label: '熱量', value: draft.nutrition_per_serving?.calories ?? '--', unit: 'kcal', color: Palette.accent.green },
          { label: '蛋白質', value: draft.nutrition_per_serving?.protein ?? '--', unit: 'g', color: Palette.accent.blue },
          { label: '碳水', value: draft.nutrition_per_serving?.carbs ?? '--', unit: 'g', color: Palette.accent.orange },
          { label: '脂肪', value: draft.nutrition_per_serving?.fat ?? '--', unit: 'g', color: Palette.accent.purple },
          { label: '鈉', value: draft.nutrition_per_serving?.sodium ?? '--', unit: 'mg', color: Palette.accent.pink },
          { label: '糖', value: draft.nutrition_per_serving?.sugar ?? '--', unit: 'g', color: Palette.accent.cyan },
        ].map((item) => (
          <View key={item.label} style={[styles.nutritionItem, { minWidth: wp(26) }]}> 
            <View style={[styles.nutritionDot, { backgroundColor: item.color }]} />
            <Text style={[styles.nutritionLabel, { fontSize: rs(10) }]}>{item.label}</Text>
            <Text style={[styles.nutritionValue, { color: item.color, fontSize: rs(13) }]}> 
              {item.value}
              <Text style={[styles.nutritionUnit, { fontSize: rs(9) }]}> {item.unit}</Text>
            </Text>
          </View>
        ))}
      </View>
      <View style={styles.ocrActions}>
        <Pressable onPress={onSaveCustomFood} style={styles.manualAddButton}>
          <Text style={[styles.manualAddButtonText, { fontSize: rs(12) }]}>儲存成自訂食品</Text>
        </Pressable>
        <Pressable onPress={onQuickAdd} style={styles.ocrQuickAddButton}>
          <Text style={[styles.ocrQuickAddText, { fontSize: rs(12) }]}>直接加入今日紀錄</Text>
        </Pressable>
      </View>
    </View>
  );
}

function ManualResultsList({
  rs,
  wp,
  foods,
  onAddFood,
}: {
  rs: (value: number) => number;
  wp: (value: number) => number;
  foods: DetectedFood[];
  onAddFood: (food: DetectedFood) => void;
}) {
  if (foods.length === 0) return null;

  return (
    <View style={styles.manualResultsWrap}>
      {foods.map((food) => (
        <View key={food.id} style={[styles.foodCard, { padding: rs(16) }]}> 
          <View style={styles.foodTop}>
            <View style={styles.foodNameRow}>
              <Text style={[styles.foodName, { fontSize: rs(16) }]}>{food.foodName}</Text>
              <View style={styles.manualBadge}>
                <Text style={[styles.manualBadgeText, { fontSize: rs(10) }]}>手動 TFDA</Text>
              </View>
            </View>
            <Text style={[styles.foodWeight, { fontSize: rs(11) }]}>以每 100g 營養資料顯示，可先加入紀錄再後續校正份量</Text>
          </View>
          <View style={styles.nutritionGrid}>
            {[
              { label: '熱量', value: food.nutrition.calories, unit: 'kcal', color: Palette.accent.green },
              { label: '蛋白質', value: food.nutrition.protein, unit: 'g', color: Palette.accent.blue },
              { label: '碳水', value: food.nutrition.carbs, unit: 'g', color: Palette.accent.orange },
              { label: '脂肪', value: food.nutrition.fat, unit: 'g', color: Palette.accent.purple },
              { label: '鈉', value: food.nutrition.sodium, unit: 'mg', color: Palette.accent.pink },
              { label: '纖維', value: food.nutrition.fiber, unit: 'g', color: Palette.accent.cyan },
            ].map((item) => (
              <View key={item.label} style={[styles.nutritionItem, { minWidth: wp(26) }]}> 
                <View style={[styles.nutritionDot, { backgroundColor: item.color }]} />
                <Text style={[styles.nutritionLabel, { fontSize: rs(10) }]}>{item.label}</Text>
                <Text style={[styles.nutritionValue, { color: item.color, fontSize: rs(13) }]}> 
                  {item.value}
                  <Text style={[styles.nutritionUnit, { fontSize: rs(9) }]}> {item.unit}</Text>
                </Text>
              </View>
            ))}
          </View>
          <Pressable onPress={() => onAddFood(food)} style={styles.manualAddButton}>
            <Text style={[styles.manualAddButtonText, { fontSize: rs(12) }]}>加入今日紀錄</Text>
          </Pressable>
        </View>
      ))}
    </View>
  );
}

export default function ScannerScreen() {
  const insets = useSafeAreaInsets();
  const { rs, wp, isSmall, isWeb } = useResponsive();
  const {
    scanResult,
    setScanResult,
    updateScanFoodWeight,
    clearScan,
    setScanning,
    addMealFromScan,
    apiBaseUrl,
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

  useFocusEffect(
    useCallback(() => {
      return () => {
        setCameraActive(false);
      };
    }, [setCameraActive])
  );

  const results = scanResult.detections;
  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);

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
        } catch {
          // Backend unavailable — fallback to demo
        }
      }

      setRejectedDetections([]);
      setScanResult(SCANNER_DEMO_RESULTS);
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
      } catch {
        // fallback
      }
    }

    setRejectedDetections([]);
    setScanResult(SCANNER_DEMO_RESULTS);
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
      const foods = await manualSearchFood({ apiBaseUrl, keyword, limit: 6 });
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

  const persistRecord = async (foods: DetectedFood[], source: 'camera' | 'manual' | 'nutrition-label') => {
    try {
      await saveRecord({ apiBaseUrl, userId: user.userId, foods, source });
    } catch {
      // Keep local-first UX even if backend record persistence fails.
    }
  };

  const handleAddRecord = () => {
    if (results.length === 0) return;
    addMealFromScan(results);
    persistRecord(results, 'camera');
    clearScan();
    Alert.alert('✅ 已加入', `${results.length} 項食物已加入今日紀錄`);
  };

  const handleAddManualFood = (food: DetectedFood) => {
    addMealFromScan([food]);
    persistRecord([food], 'manual');
    Alert.alert('已加入今日紀錄', `${food.foodName} 已以每 100g 份量加入今日紀錄`);
  };

  const handleSaveCustomFood = async () => {
    if (!ocrDraft) return;
    try {
      const data = await saveCustomFood({ apiBaseUrl, userId: user.userId, draft: ocrDraft });
      Alert.alert('自訂食品已儲存', `${data.food?.name_zh || ocrDraft.product_name} 之後可直接搜尋使用`);
    } catch {
      Alert.alert('儲存失敗', '請稍後再試');
    }
  };

  const handleQuickAddOCRFood = () => {
    if (!ocrDraft) return;
    const food = buildOCRDetectedFood(ocrDraft);
    addMealFromScan([food]);
    persistRecord([food], 'nutrition-label');
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
      <View style={styles.header}>
        <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>AI 食物辨識</Text>
        <Text style={[styles.subtitle, { fontSize: rs(13) }]}>拍攝或上傳食物照片，YOLO 多目標偵測自動分析營養成分</Text>
      </View>

      <View style={styles.contextCard}>
        <Text style={[styles.contextTitle, { fontSize: rs(12) }]}>目前辨識會套用你的健康條件</Text>
        <Text style={[styles.contextText, { fontSize: rs(11) }]}>疾病：{user.healthConditions.length > 0 ? user.healthConditions.join('、') : '未設定'}</Text>
        <Text style={[styles.contextText, { fontSize: rs(11) }]}>過敏原：{user.allergens.length > 0 ? user.allergens.join('、') : '未設定'}</Text>
      </View>

      <View style={styles.viewfinderContainer}>
        <LinearGradient colors={['rgba(167, 139, 250, 0.08)', 'rgba(96, 165, 250, 0.04)', 'transparent']} style={[styles.viewfinder, { height: rs(180) }]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}>
          <View style={[styles.corner, styles.cornerTL]} />
          <View style={[styles.corner, styles.cornerTR]} />
          <View style={[styles.corner, styles.cornerBL]} />
          <View style={[styles.corner, styles.cornerBR]} />

          {scanResult.isScanning ? (
            <View style={styles.viewfinderInner}>
              <ActivityIndicator size="large" color={Palette.accent.cyan} />
              <Text style={[styles.viewfinderText, { fontSize: rs(14) }]}>辨識中...</Text>
            </View>
          ) : results.length === 0 ? (
            <View style={styles.viewfinderInner}>
              <View style={[styles.iconCircle, { width: rs(70), height: rs(70), borderRadius: rs(35) }]}>
                <Ionicons name="scan-outline" size={rs(40)} color={Palette.accent.purple} />
              </View>
              <Text style={[styles.viewfinderText, { fontSize: rs(14) }]}>將食物對準框內</Text>
              <Text style={[styles.viewfinderHint, { fontSize: rs(11) }]}>支援 YOLO 多目標即時偵測</Text>
            </View>
          ) : (
            <View style={styles.viewfinderInner}>
              <Ionicons name="checkmark-circle" size={rs(40)} color={Palette.accent.green} />
              <Text style={[styles.viewfinderText, { fontSize: rs(14) }]}>偵測到 {results.length} 項食物</Text>
              <Text style={[styles.viewfinderHint, { fontSize: rs(11) }]}>總計 {totalCal} kcal · 鈉 {totalSodium}mg</Text>
            </View>
          )}
        </LinearGradient>
      </View>

      <View style={styles.actionsContainer}>
        <Pressable onPress={handleCamera} style={({ pressed }) => [pressed && { transform: [{ scale: 0.95 }] }, { flex: 1 }]}>
          <LinearGradient colors={['#4ADE80', '#22D3EE']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[styles.cameraButton, { paddingVertical: rs(14) }]}> 
            <Ionicons name="camera" size={rs(20)} color={Palette.text.inverse} />
            <Text style={[styles.cameraButtonText, { fontSize: rs(14) }]}>啟動相機</Text>
          </LinearGradient>
        </Pressable>

        <Pressable onPress={handleGallery} style={({ pressed }) => [styles.galleryButton, { paddingVertical: rs(14), flex: 1 }, pressed && styles.galleryButtonPressed]}>
          <Ionicons name="images-outline" size={rs(18)} color={Palette.accent.purple} />
          <Text style={[styles.galleryButtonText, { fontSize: rs(14) }]}>相簿上傳</Text>
        </Pressable>
      </View>

      {results.length > 0 && (
        <Pressable onPress={clearScan} style={styles.clearButton}>
          <Ionicons name="refresh" size={rs(14)} color={Palette.text.tertiary} />
          <Text style={[styles.clearText, { fontSize: rs(11) }]}>清除結果</Text>
        </Pressable>
      )}

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

      {ocrDraft && (
        <OCRDraftCard
          rs={rs}
          wp={wp}
          draft={ocrDraft}
          onSaveCustomFood={handleSaveCustomFood}
          onQuickAdd={handleQuickAddOCRFood}
        />
      )}

      <ManualResultsList rs={rs} wp={wp} foods={manualResults} onAddFood={handleAddManualFood} />

      <View style={styles.resultHeader}>
        <Ionicons name="nutrition-outline" size={rs(16)} color={Palette.accent.cyan} />
        <Text style={[styles.resultTitle, { fontSize: rs(16) }]}>辨識結果</Text>
        {results.length > 0 && (
          <View style={styles.resultCountBadge}>
            <Text style={[styles.resultCountText, { fontSize: rs(11) }]}>{results.length} 項</Text>
          </View>
        )}
      </View>

      <ScannerResults rs={rs} wp={wp} results={results} onAddRecord={handleAddRecord} onWeightChange={updateScanFoodWeight} />
    </AppContainer>
  );
}

const CORNER_SIZE = 24;
const CORNER_WIDTH = 3;

const styles = StyleSheet.create({
  header: { marginTop: Spacing.lg, marginBottom: Spacing.xl },
  title: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  subtitle: { ...Typography.body, color: Palette.text.tertiary, lineHeight: 22 },

  viewfinderContainer: { marginBottom: Spacing.xl },
  viewfinder: {
    borderRadius: Radius.xl, borderWidth: 1, borderColor: Palette.border.medium,
    justifyContent: 'center', alignItems: 'center', position: 'relative', overflow: 'hidden',
  },
  viewfinderInner: { alignItems: 'center' },
  iconCircle: {
    backgroundColor: Palette.accent.purpleDim, alignItems: 'center', justifyContent: 'center', marginBottom: Spacing.md,
  },
  viewfinderText: { ...Typography.bodyBold, color: Palette.text.secondary, marginTop: Spacing.sm, marginBottom: Spacing.xs },
  viewfinderHint: { ...Typography.small, color: Palette.text.tertiary },
  corner: { position: 'absolute', width: CORNER_SIZE, height: CORNER_SIZE },
  cornerTL: { top: 12, left: 12, borderTopWidth: CORNER_WIDTH, borderLeftWidth: CORNER_WIDTH, borderColor: Palette.accent.purple, borderTopLeftRadius: 4 },
  cornerTR: { top: 12, right: 12, borderTopWidth: CORNER_WIDTH, borderRightWidth: CORNER_WIDTH, borderColor: Palette.accent.purple, borderTopRightRadius: 4 },
  cornerBL: { bottom: 12, left: 12, borderBottomWidth: CORNER_WIDTH, borderLeftWidth: CORNER_WIDTH, borderColor: Palette.accent.cyan, borderBottomLeftRadius: 4 },
  cornerBR: { bottom: 12, right: 12, borderBottomWidth: CORNER_WIDTH, borderRightWidth: CORNER_WIDTH, borderColor: Palette.accent.cyan, borderBottomRightRadius: 4 },

  actionsContainer: { flexDirection: 'row', gap: Spacing.md, marginBottom: Spacing.lg },
  cameraButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    borderRadius: Radius.lg, gap: Spacing.sm, ...Shadows.card,
  },
  cameraButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
  galleryButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    borderRadius: Radius.lg, backgroundColor: Palette.accent.purpleDim,
    borderWidth: 1, borderColor: 'rgba(167, 139, 250, 0.25)', gap: Spacing.sm,
  },
  galleryButtonPressed: { backgroundColor: 'rgba(167, 139, 250, 0.25)', transform: [{ scale: 0.95 }] },
  galleryButtonText: { ...Typography.bodyBold, color: Palette.accent.purple },

  clearButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 4, marginBottom: Spacing.lg, alignSelf: 'center',
  },
  clearText: { ...Typography.small, color: Palette.text.tertiary },

  contextCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  contextTitle: { ...Typography.caption, color: Palette.text.primary, marginBottom: 4 },
  contextText: { ...Typography.small, color: Palette.text.tertiary },

  manualCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  manualHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.sm },
  manualTitle: { ...Typography.h3, color: Palette.text.primary, flex: 1 },
  manualResultsWrap: { marginBottom: Spacing.xl },
  manualBadge: {
    backgroundColor: Palette.accent.cyanDim,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: Radius.full,
  },
  manualBadgeText: { ...Typography.small, color: Palette.accent.cyan },
  manualAddButton: {
    marginTop: Spacing.md,
    borderRadius: Radius.md,
    backgroundColor: Palette.accent.greenDim,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.md,
  },
  manualAddButtonText: { ...Typography.bodyBold, color: Palette.accent.green },
  ocrProductName: { ...Typography.bodyBold, color: Palette.text.primary, marginBottom: Spacing.xs },
  ocrMetaText: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 2 },
  ocrActions: { gap: Spacing.sm, marginTop: Spacing.md },
  ocrQuickAddButton: {
    borderRadius: Radius.md,
    backgroundColor: Palette.accent.cyanDim,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.md,
  },
  ocrQuickAddText: { ...Typography.bodyBold, color: Palette.accent.cyan },

  foodCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.md,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  foodTop: { marginBottom: Spacing.md },
  foodNameRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  foodName: { ...Typography.h3, color: Palette.text.primary },
  foodWeight: { ...Typography.small, color: Palette.text.tertiary },

  nutritionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutritionItem: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.md, padding: Spacing.sm, flex: 1 },
  nutritionDot: { width: 6, height: 6, borderRadius: 3, marginBottom: 4 },
  nutritionLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 2 },
  nutritionValue: { ...Typography.caption, fontWeight: '700' },
  nutritionUnit: { ...Typography.small, color: Palette.text.tertiary },

  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.lg },
  resultTitle: { ...Typography.h3, color: Palette.text.primary, flex: 1 },
  resultCountBadge: { backgroundColor: Palette.accent.cyanDim, paddingHorizontal: Spacing.sm, paddingVertical: 2, borderRadius: Radius.full },
  resultCountText: { ...Typography.small, color: Palette.accent.cyan },
});
