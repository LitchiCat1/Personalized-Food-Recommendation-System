import React, { useState, useRef, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  Alert, ActivityIndicator, Platform,
} from 'react-native';
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

export default function ScannerScreen() {
  const insets = useSafeAreaInsets();
  const { rs, wp, isSmall, isWeb } = useResponsive();
  const { scanResult, setScanResult, clearScan, setScanning, addMealFromScan, apiBaseUrl, isCameraActive, setCameraActive } = useStore();
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);

  // Fix #3+#4: Reset camera state when leaving this tab
  useFocusEffect(
    useCallback(() => {
      return () => {
        setCameraActive(false);
      };
    }, [])
  );

  const results = scanResult.detections;
  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);

  // ── 拍照 ──
  const handleCamera = async () => {
    if (isWeb) {
      // Web fallback: use demo data
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

  const takePicture = async () => {
    if (!cameraRef.current) return;
    setScanning(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.7 });
      setCameraActive(false);

      if (photo?.base64) {
        // Try backend API first
        try {
          const resp = await fetch(`${apiBaseUrl}/predict`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: photo.base64 }),
          });
          const data = await resp.json();
          if (data.detections?.length > 0) {
            const mapped: DetectedFood[] = data.detections.map((d: any, i: number) => ({
              id: `det_${i}`,
              foodName: d.name_zh || d.label,
              confidence: d.confidence * 100,
              boundingBox: d.bounding_box,
              estimatedWeight: d.estimated_weight_g,
              nutrition: d.nutrition,
              gi: d.gi || 'medium',
              allergens: d.allergens || [],
              warnings: d.warnings || [],
            }));
            setScanResult(mapped);
            return;
          }
        } catch {
          // Backend unavailable — fallback to demo
        }
      }
      // Fallback demo
      setScanResult(SCANNER_DEMO_RESULTS);
    } catch {
      Alert.alert('拍照失敗', '請再試一次');
      setScanning(false);
    }
  };

  // ── 相簿 ──
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
        const resp = await fetch(`${apiBaseUrl}/predict`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: asset.base64 }),
        });
        const data = await resp.json();
        if (data.detections?.length > 0) {
          const mapped: DetectedFood[] = data.detections.map((d: any, i: number) => ({
            id: `det_${i}`,
            foodName: d.name_zh || d.label,
            confidence: d.confidence * 100,
            boundingBox: d.bounding_box,
            estimatedWeight: d.estimated_weight_g,
            nutrition: d.nutrition,
            gi: d.gi || 'medium',
            allergens: d.allergens || [],
            warnings: d.warnings || [],
          }));
          setScanResult(mapped);
          return;
        }
      } catch {
        // fallback
      }
    }
    setScanResult(SCANNER_DEMO_RESULTS);
  };

  // ── 加入紀錄 ──
  const handleAddRecord = () => {
    if (results.length === 0) return;
    addMealFromScan(results);
    clearScan();
    Alert.alert('✅ 已加入', `${results.length} 項食物已加入今日紀錄`);
  };

  // ── Camera View (fullscreen, NO tab bar) ──
  if (isCameraActive && !isWeb) {
    return (
      <View style={[styles.screen, { paddingTop: insets.top }]}>
        <CameraView ref={cameraRef} style={styles.camera} facing="back">
          <View style={styles.cameraOverlay}>
            <View style={styles.cameraGuide}>
              <View style={[styles.corner, styles.cornerTL]} />
              <View style={[styles.corner, styles.cornerTR]} />
              <View style={[styles.corner, styles.cornerBL]} />
              <View style={[styles.corner, styles.cornerBR]} />
            </View>
            <Text style={[styles.cameraHint, { fontSize: rs(13) }]}>將食物對準框內</Text>
            <View style={styles.cameraActions}>
              <Pressable onPress={() => setCameraActive(false)} style={styles.cameraCancelBtn}>
                <Ionicons name="close" size={rs(24)} color={Palette.text.primary} />
              </Pressable>
              <Pressable onPress={takePicture} style={styles.shutterBtn}>
                <View style={styles.shutterInner} />
              </Pressable>
              <View style={{ width: rs(48) }} />
            </View>
          </View>
        </CameraView>
      </View>
    );
  }

  return (
    <AppContainer>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.title, { fontSize: rs(isSmall ? 22 : 26) }]}>AI 食物辨識</Text>
        <Text style={[styles.subtitle, { fontSize: rs(13) }]}>
          拍攝或上傳食物照片，YOLO 多目標偵測自動分析營養成分
        </Text>
      </View>

        {/* Viewfinder */}
        <View style={styles.viewfinderContainer}>
          <LinearGradient
            colors={['rgba(167, 139, 250, 0.08)', 'rgba(96, 165, 250, 0.04)', 'transparent']}
            style={[styles.viewfinder, { height: rs(180) }]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
          >
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
                <Text style={[styles.viewfinderHint, { fontSize: rs(11) }]}>
                  總計 {totalCal} kcal · 鈉 {totalSodium}mg
                </Text>
              </View>
            )}
          </LinearGradient>
        </View>

        {/* Actions */}
        <View style={styles.actionsContainer}>
          <Pressable
            onPress={handleCamera}
            style={({ pressed }) => [pressed && { transform: [{ scale: 0.95 }] }, { flex: 1 }]}
          >
            <LinearGradient
              colors={['#4ADE80', '#22D3EE']}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={[styles.cameraButton, { paddingVertical: rs(14) }]}
            >
              <Ionicons name="camera" size={rs(20)} color={Palette.text.inverse} />
              <Text style={[styles.cameraButtonText, { fontSize: rs(14) }]}>啟動相機</Text>
            </LinearGradient>
          </Pressable>

          <Pressable
            onPress={handleGallery}
            style={({ pressed }) => [
              styles.galleryButton,
              { paddingVertical: rs(14), flex: 1 },
              pressed && styles.galleryButtonPressed,
            ]}
          >
            <Ionicons name="images-outline" size={rs(18)} color={Palette.accent.purple} />
            <Text style={[styles.galleryButtonText, { fontSize: rs(14) }]}>相簿上傳</Text>
          </Pressable>
        </View>

        {/* Clear button */}
        {results.length > 0 && (
          <Pressable onPress={clearScan} style={styles.clearButton}>
            <Ionicons name="refresh" size={rs(14)} color={Palette.text.tertiary} />
            <Text style={[styles.clearText, { fontSize: rs(11) }]}>清除結果</Text>
          </Pressable>
        )}

        {/* Result header */}
        <View style={styles.resultHeader}>
          <Ionicons name="nutrition-outline" size={rs(16)} color={Palette.accent.cyan} />
          <Text style={[styles.resultTitle, { fontSize: rs(16) }]}>辨識結果</Text>
          {results.length > 0 && (
            <View style={styles.resultCountBadge}>
              <Text style={[styles.resultCountText, { fontSize: rs(11) }]}>{results.length} 項</Text>
            </View>
          )}
        </View>

        {/* Empty state */}
        {results.length === 0 ? (
          <View style={[styles.placeholderCard, { padding: rs(32) }]}>
            <Ionicons name="image-outline" size={rs(36)} color={Palette.text.tertiary} />
            <Text style={[styles.placeholderText, { fontSize: rs(13) }]}>
              尚未辨識，請拍攝或上傳食物照片
            </Text>
          </View>
        ) : (
          // Detection cards
          results.map((food) => (
            <View key={food.id} style={[styles.foodCard, { padding: rs(16) }]}>
              <View style={styles.foodTop}>
                <View style={styles.foodNameRow}>
                  <Text style={[styles.foodName, { fontSize: rs(16) }]}>{food.foodName}</Text>
                  <View style={styles.confidenceBadge}>
                    <Text style={[styles.confidenceText, { fontSize: rs(11) }]}>{food.confidence}%</Text>
                  </View>
                </View>
                <Text style={[styles.foodWeight, { fontSize: rs(11) }]}>
                  估算份量 {food.estimatedWeight}g · Bounding Box ({(food.boundingBox.w * 100).toFixed(0)}×{(food.boundingBox.h * 100).toFixed(0)})
                </Text>
              </View>

              {/* Tags */}
              <View style={styles.tagsRow}>
                <View style={[
                  styles.giTag,
                  food.gi === 'high' && styles.giHigh,
                  food.gi === 'medium' && styles.giMedium,
                  food.gi === 'low' && styles.giLow,
                ]}>
                  <Text style={[
                    styles.giText,
                    { fontSize: rs(11) },
                    food.gi === 'high' && { color: Palette.status.error },
                    food.gi === 'medium' && { color: Palette.status.warning },
                    food.gi === 'low' && { color: Palette.accent.green },
                  ]}>
                    GI {food.gi === 'high' ? '高' : food.gi === 'medium' ? '中' : '低'}
                  </Text>
                </View>
                {food.allergens.map((a) => (
                  <View key={a} style={styles.allergenTag}>
                    <Ionicons name="alert-circle" size={rs(10)} color={Palette.accent.orange} />
                    <Text style={[styles.allergenText, { fontSize: rs(10) }]}>{a}</Text>
                  </View>
                ))}
              </View>

              {/* Warnings */}
              {food.warnings.length > 0 && (
                <View style={styles.warningBanner}>
                  <Ionicons name="warning" size={rs(14)} color={Palette.status.warning} />
                  <Text style={[styles.warningText, { fontSize: rs(11) }]}>{food.warnings.join('；')}</Text>
                </View>
              )}

              {/* Nutrition grid */}
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
            </View>
          ))
        )}

        {/* Total summary */}
        {results.length > 0 && (
          <View style={[styles.totalCard, { padding: rs(20) }]}>
            <Text style={[styles.totalTitle, { fontSize: rs(16) }]}>合計攝取</Text>
            <View style={styles.totalRow}>
              <View style={styles.totalItem}>
                <Text style={[styles.totalLabel, { fontSize: rs(10) }]}>熱量</Text>
                <Text style={[styles.totalValue, { color: Palette.accent.green, fontSize: rs(15) }]}>{totalCal} kcal</Text>
              </View>
              <View style={styles.totalItem}>
                <Text style={[styles.totalLabel, { fontSize: rs(10) }]}>蛋白質</Text>
                <Text style={[styles.totalValue, { color: Palette.accent.blue, fontSize: rs(15) }]}>
                  {results.reduce((s, f) => s + f.nutrition.protein, 0)}g
                </Text>
              </View>
              <View style={styles.totalItem}>
                <Text style={[styles.totalLabel, { fontSize: rs(10) }]}>鈉</Text>
                <Text style={[styles.totalValue, {
                  color: totalSodium > 800 ? Palette.status.warning : Palette.accent.pink,
                  fontSize: rs(15),
                }]}>
                  {totalSodium}mg
                </Text>
              </View>
            </View>
            <Pressable onPress={handleAddRecord} style={styles.addButton}>
              <LinearGradient
                colors={['#4ADE80', '#22D3EE']}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={[styles.addButtonInner, { paddingVertical: rs(14) }]}
              >
                <Ionicons name="add-circle" size={rs(18)} color={Palette.text.inverse} />
                <Text style={[styles.addButtonText, { fontSize: rs(14) }]}>加入今日紀錄</Text>
              </LinearGradient>
            </Pressable>
          </View>
        )}
    </AppContainer>
  );
}

const CORNER_SIZE = 24;
const CORNER_WIDTH = 3;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: Palette.bg.primary },
  scrollContent: { paddingBottom: Spacing['5xl'] },
  header: { marginTop: Spacing.lg, marginBottom: Spacing.xl },
  title: { ...Typography.h1, color: Palette.text.primary, marginBottom: Spacing.xs },
  subtitle: { ...Typography.body, color: Palette.text.tertiary, lineHeight: 22 },

  // Camera fullscreen
  camera: { flex: 1 },
  cameraOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 60 },
  cameraGuide: { width: 260, height: 260, position: 'absolute', top: '30%' },
  cameraHint: { ...Typography.body, color: '#fff', marginBottom: 40 },
  cameraActions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-around', width: '80%' },
  cameraCancelBtn: {
    width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterBtn: {
    width: 72, height: 72, borderRadius: 36, borderWidth: 4, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: '#fff' },

  // Viewfinder
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

  // Actions
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

  // Result
  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.lg },
  resultTitle: { ...Typography.h3, color: Palette.text.primary, flex: 1 },
  resultCountBadge: { backgroundColor: Palette.accent.cyanDim, paddingHorizontal: Spacing.sm, paddingVertical: 2, borderRadius: Radius.full },
  resultCountText: { ...Typography.small, color: Palette.accent.cyan },
  placeholderCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Palette.border.subtle, gap: Spacing.md,
  },
  placeholderText: { ...Typography.body, color: Palette.text.tertiary },

  // Food Card
  foodCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.md,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  foodTop: { marginBottom: Spacing.md },
  foodNameRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  foodName: { ...Typography.h3, color: Palette.text.primary },
  confidenceBadge: { backgroundColor: Palette.accent.greenDim, paddingHorizontal: Spacing.sm, paddingVertical: 2, borderRadius: Radius.full },
  confidenceText: { ...Typography.small, color: Palette.accent.green },
  foodWeight: { ...Typography.small, color: Palette.text.tertiary },
  tagsRow: { flexDirection: 'row', gap: Spacing.sm, marginBottom: Spacing.md, flexWrap: 'wrap' },
  giTag: { paddingHorizontal: Spacing.sm, paddingVertical: 3, borderRadius: Radius.sm },
  giHigh: { backgroundColor: 'rgba(248, 113, 113, 0.12)' },
  giMedium: { backgroundColor: 'rgba(251, 191, 36, 0.12)' },
  giLow: { backgroundColor: Palette.accent.greenDim },
  giText: { ...Typography.small, fontWeight: '600' },
  allergenTag: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: Palette.accent.orangeDim, paddingHorizontal: Spacing.sm, paddingVertical: 3, borderRadius: Radius.sm,
  },
  allergenText: { ...Typography.small, color: Palette.accent.orange },
  warningBanner: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.sm,
    backgroundColor: 'rgba(251, 191, 36, 0.08)', borderRadius: Radius.md,
    padding: Spacing.md, marginBottom: Spacing.md, borderWidth: 1, borderColor: 'rgba(251, 191, 36, 0.2)',
  },
  warningText: { ...Typography.caption, color: Palette.status.warning, flex: 1 },

  nutritionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutritionItem: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.md, padding: Spacing.sm, flex: 1 },
  nutritionDot: { width: 6, height: 6, borderRadius: 3, marginBottom: 4 },
  nutritionLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 2 },
  nutritionValue: { ...Typography.caption, fontWeight: '700' },
  nutritionUnit: { ...Typography.small, color: Palette.text.tertiary },

  totalCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    borderWidth: 1, borderColor: Palette.accent.greenDim, ...Shadows.card,
  },
  totalTitle: { ...Typography.h3, color: Palette.text.primary, marginBottom: Spacing.md },
  totalRow: { flexDirection: 'row', justifyContent: 'space-around', marginBottom: Spacing.xl },
  totalItem: { alignItems: 'center' },
  totalLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  totalValue: { ...Typography.bodyBold },
  addButton: { borderRadius: Radius.lg, overflow: 'hidden' },
  addButtonInner: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: Spacing.sm },
  addButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
});
