import React from 'react';
import { View, Text, StyleSheet, Pressable, TextInput } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import type { DetectedFood } from '@/constants/mock-data';

type Props = {
  rs: (value: number) => number;
  wp: (value: number) => number;
  results: DetectedFood[];
  onAddRecord: () => void;
  onWeightChange: (foodId: string, nextWeight: number) => void;
};

export default function ScannerResults({ rs, wp, results, onAddRecord, onWeightChange }: Props) {
  if (results.length === 0) {
    return (
      <View style={[styles.placeholderCard, { padding: rs(32) }]}> 
        <Ionicons name="image-outline" size={rs(36)} color={Palette.text.tertiary} />
        <Text style={[styles.placeholderText, { fontSize: rs(13) }]}>尚未辨識，請拍攝或上傳食物照片</Text>
      </View>
    );
  }

  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);

  return (
    <>
      {results.map((food) => (
        <View key={food.id} style={[styles.foodCard, { padding: rs(16) }]}> 
          <View style={styles.foodTop}>
            <View style={styles.foodNameRow}>
              <Text style={[styles.foodName, { fontSize: rs(16) }]}>{food.foodName}</Text>
              <View style={styles.confidenceBadge}>
                <Text style={[styles.confidenceText, { fontSize: rs(11) }]}>{food.confidence}%</Text>
              </View>
            </View>
            <Text style={[styles.foodWeight, { fontSize: rs(11) }]}> 
              {food.portionAdjusted ? '已校正份量' : '估算份量'} {food.estimatedWeight}g · Bounding Box ({(food.boundingBox.w * 100).toFixed(0)}×{(food.boundingBox.h * 100).toFixed(0)})
            </Text>
            {food.source ? <Text style={[styles.foodMeta, { fontSize: rs(10) }]}>資料來源：{food.source}</Text> : null}
          </View>

          <View style={styles.portionCard}>
            <View style={styles.portionHeader}>
              <Ionicons name="scale-outline" size={rs(13)} color={Palette.accent.cyan} />
              <Text style={[styles.portionTitle, { fontSize: rs(12) }]}>份量校正</Text>
              {food.portionAdjusted ? <Text style={[styles.portionAdjustedText, { fontSize: rs(10) }]}>已重算營養</Text> : null}
            </View>
            <View style={styles.portionControls}>
              <Pressable onPress={() => onWeightChange(food.id, food.estimatedWeight - 10)} style={styles.portionButton}>
                <Text style={[styles.portionButtonText, { fontSize: rs(13) }]}>-10g</Text>
              </Pressable>
              <TextInput
                value={String(Math.round(food.estimatedWeight))}
                onChangeText={(value) => {
                  const next = Number(value.replace(/[^0-9]/g, ''));
                  if (Number.isFinite(next) && next > 0) onWeightChange(food.id, next);
                }}
                keyboardType="numeric"
                selectTextOnFocus
                style={[styles.portionInput, { fontSize: rs(13) }]}
              />
              <Text style={[styles.portionUnit, { fontSize: rs(11) }]}>g</Text>
              <Pressable onPress={() => onWeightChange(food.id, food.estimatedWeight + 10)} style={styles.portionButton}>
                <Text style={[styles.portionButtonText, { fontSize: rs(13) }]}>+10g</Text>
              </Pressable>
              {food.portionAdjusted ? (
                <Pressable onPress={() => onWeightChange(food.id, food.originalEstimatedWeight || food.estimatedWeight)} style={styles.resetButton}>
                  <Text style={[styles.resetButtonText, { fontSize: rs(11) }]}>還原</Text>
                </Pressable>
              ) : null}
            </View>
          </View>

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
            {food.needsConfirmation && (
              <View style={styles.confirmTag}>
                <Ionicons name="help-circle" size={rs(10)} color={Palette.status.warning} />
                <Text style={[styles.confirmTagText, { fontSize: rs(10) }]}>需人工確認</Text>
              </View>
            )}
          </View>

          {food.warnings.length > 0 && (
            <View style={styles.warningBanner}>
              <Ionicons name="warning" size={rs(14)} color={Palette.status.warning} />
              <Text style={[styles.warningText, { fontSize: rs(11) }]}>{food.warnings.join('；')}</Text>
            </View>
          )}

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
      ))}

      <View style={[styles.totalCard, { padding: rs(20) }]}> 
        <Text style={[styles.totalTitle, { fontSize: rs(16) }]}>合計攝取</Text>
        <View style={styles.totalRow}>
          <View style={styles.totalItem}>
            <Text style={[styles.totalLabel, { fontSize: rs(10) }]}>熱量</Text>
            <Text style={[styles.totalValue, { color: Palette.accent.green, fontSize: rs(15) }]}>{totalCal} kcal</Text>
          </View>
          <View style={styles.totalItem}>
            <Text style={[styles.totalLabel, { fontSize: rs(10) }]}>蛋白質</Text>
            <Text style={[styles.totalValue, { color: Palette.accent.blue, fontSize: rs(15) }]}>{results.reduce((s, f) => s + f.nutrition.protein, 0)}g</Text>
          </View>
          <View style={styles.totalItem}>
            <Text style={[styles.totalLabel, { fontSize: rs(10) }]}>鈉</Text>
            <Text style={[styles.totalValue, { color: totalSodium > 800 ? Palette.status.warning : Palette.accent.pink, fontSize: rs(15) }]}>{totalSodium}mg</Text>
          </View>
        </View>
        <Pressable onPress={onAddRecord} style={styles.addButton}>
          <LinearGradient colors={['#4ADE80', '#22D3EE']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[styles.addButtonInner, { paddingVertical: rs(14) }]}> 
            <Ionicons name="add-circle" size={rs(18)} color={Palette.text.inverse} />
            <Text style={[styles.addButtonText, { fontSize: rs(14) }]}>加入今日紀錄</Text>
          </LinearGradient>
        </Pressable>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  placeholderCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Palette.border.subtle, gap: Spacing.md,
  },
  placeholderText: { ...Typography.body, color: Palette.text.tertiary },
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
  foodMeta: { ...Typography.small, color: Palette.text.tertiary, marginTop: 4 },
  portionCard: {
    backgroundColor: 'rgba(34, 211, 238, 0.06)',
    borderRadius: Radius.md,
    padding: Spacing.md,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(34, 211, 238, 0.18)',
  },
  portionHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.xs, marginBottom: Spacing.sm },
  portionTitle: { ...Typography.bodyBold, color: Palette.text.secondary, flex: 1 },
  portionAdjustedText: { ...Typography.small, color: Palette.accent.green },
  portionControls: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, flexWrap: 'wrap' },
  portionButton: {
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.sm,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  portionButtonText: { ...Typography.bodyBold, color: Palette.accent.cyan },
  portionInput: {
    width: 72,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 6,
    textAlign: 'center',
  },
  portionUnit: { ...Typography.caption, color: Palette.text.tertiary, marginLeft: -4 },
  resetButton: { paddingHorizontal: Spacing.sm, paddingVertical: 6 },
  resetButtonText: { ...Typography.caption, color: Palette.status.warning },
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
  confirmTag: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: 'rgba(251, 191, 36, 0.12)', paddingHorizontal: Spacing.sm, paddingVertical: 3, borderRadius: Radius.sm,
  },
  confirmTagText: { ...Typography.small, color: Palette.status.warning },
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
