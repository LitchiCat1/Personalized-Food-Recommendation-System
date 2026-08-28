import React from 'react';
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import type { DetectedFood } from '@/constants/mock-data';

type Props = {
  rs: (value: number) => number;
  wp: (value: number) => number;
  results: DetectedFood[];
  onAddRecord: () => void;
  onWeightChange: (foodId: string, nextWeight: number) => void;
  onToggleFavorite?: (foodKey: string) => void;
  isFavorite?: (foodKey: string) => boolean;
  submitting?: boolean;
  disabled?: boolean;
};

export default function ScannerResults({ rs, wp, results, onAddRecord, onWeightChange, onToggleFavorite, isFavorite, submitting = false, disabled = false }: Props) {
  const controlsDisabled = submitting || disabled;

  if (results.length === 0) {
    return (
      <View style={styles.placeholderCard}>
        <Ionicons name="image-outline" size={rs(34)} color={Palette.text.tertiary} />
        <Text style={styles.placeholderTitle}>尚未產生辨識結果</Text>
        <Text style={styles.placeholderText}>拍攝餐點、上傳相簿或使用手動搜尋後，結果會出現在這裡。</Text>
      </View>
    );
  }

  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalProtein = Math.round(results.reduce((s, f) => s + f.nutrition.protein, 0) * 10) / 10;
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);

  return (
    <>
      {results.map((food) => {
        const foodKey = food.foodName;
        const favorited = isFavorite?.(foodKey) ?? false;
        return (
        <View key={food.id} style={styles.foodCard}>
          <View style={styles.foodTop}>
            <View style={styles.foodInfo}>
              <Text style={styles.foodName}>{food.foodName}</Text>
              <Text style={styles.foodWeight}>
                {food.portionAdjusted ? '已校正份量' : '估算份量'} {food.estimatedWeight}g
              </Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Pressable
                onPress={() => onToggleFavorite?.(foodKey)}
                accessibilityLabel={favorited ? `移除 ${food.foodName} 收藏` : `收藏 ${food.foodName}`}
                style={styles.favButton}
              >
                <Ionicons name={favorited ? 'star' : 'star-outline'} size={20} color={favorited ? '#FBBF24' : Palette.text.tertiary} />
              </Pressable>
              <DataPill tone={food.confidence >= 80 ? 'success' : 'warning'}>{food.confidence}%</DataPill>
            </View>
          </View>

          <View style={styles.portionCard}>
            <View style={styles.portionHeader}>
              <Ionicons name="scale-outline" size={14} color={Palette.accent.green} />
              <Text style={styles.portionTitle}>份量校正</Text>
              {food.portionAdjusted ? <Text style={styles.portionAdjustedText}>已重算營養</Text> : null}
            </View>
            <View style={styles.portionControls}>
              <Pressable
                onPress={() => onWeightChange(food.id, food.estimatedWeight - 10)}
                disabled={controlsDisabled}
                accessibilityRole="button"
                accessibilityLabel={`${food.foodName} 減少 10 克`}
                accessibilityState={{ disabled: controlsDisabled }}
                style={[styles.portionButton, controlsDisabled && styles.controlDisabled]}
              >
                <Text style={styles.portionButtonText}>-10g</Text>
              </Pressable>
              <TextInput
                value={String(Math.round(food.estimatedWeight))}
                onChangeText={(value) => {
                  const next = Number(value.replace(/[^0-9]/g, ''));
                  if (Number.isFinite(next) && next > 0) onWeightChange(food.id, next);
                }}
                keyboardType="numeric"
                selectTextOnFocus
                editable={!controlsDisabled}
                style={[styles.portionInput, controlsDisabled && styles.controlDisabled]}
              />
              <Text style={styles.portionUnit}>g</Text>
              <Pressable
                onPress={() => onWeightChange(food.id, food.estimatedWeight + 10)}
                disabled={controlsDisabled}
                accessibilityRole="button"
                accessibilityLabel={`${food.foodName} 增加 10 克`}
                accessibilityState={{ disabled: controlsDisabled }}
                style={[styles.portionButton, controlsDisabled && styles.controlDisabled]}
              >
                <Text style={styles.portionButtonText}>+10g</Text>
              </Pressable>
              {food.portionAdjusted ? (
                <Pressable
                  onPress={() => onWeightChange(food.id, food.originalEstimatedWeight || food.estimatedWeight)}
                  disabled={controlsDisabled}
                  accessibilityRole="button"
                  accessibilityLabel={`${food.foodName} 還原估算份量`}
                  accessibilityState={{ disabled: controlsDisabled }}
                  style={[styles.resetButton, controlsDisabled && styles.controlDisabled]}
                >
                  <Text style={styles.resetButtonText}>還原</Text>
                </Pressable>
              ) : null}
            </View>
          </View>

          <View style={styles.tagsRow}>
            <DataPill tone={food.gi === 'high' ? 'danger' : food.gi === 'medium' ? 'warning' : 'success'}>
              GI {food.gi === 'high' ? '高' : food.gi === 'medium' ? '中' : '低'}
            </DataPill>
            {food.source ? <DataPill tone="info">{food.source}</DataPill> : null}
            {food.nutrition.is_fried ? <DataPill tone="danger">油炸食物</DataPill> : null}
            {food.needsConfirmation ? <DataPill tone="warning">需人工確認</DataPill> : null}
            {food.allergens.map((a) => <DataPill key={a} tone="warning">{a}</DataPill>)}
          </View>

          {food.warnings.length > 0 ? (
            <View style={styles.warningBanner}>
              <Ionicons name="warning-outline" size={15} color={Palette.status.warning} />
              <Text style={styles.warningText}>{food.warnings.join('；')}</Text>
            </View>
          ) : null}

          {food.swap_suggestion ? (
            <View style={styles.swapBanner}>
              <Ionicons name="swap-horizontal-outline" size={15} color={Palette.accent.cyan} />
              <View style={{ flex: 1 }}>
                <Text style={styles.swapTitle}>更健康替換：{food.swap_suggestion.name}</Text>
                <Text style={styles.swapReason}>{food.swap_suggestion.reason}</Text>
              </View>
            </View>
          ) : null}

          <View style={styles.nutritionGrid}>
            {[
              { label: '熱量', value: food.nutrition.calories, unit: 'kcal', color: Palette.accent.green },
              { label: '蛋白質', value: food.nutrition.protein, unit: 'g', color: Palette.accent.blue },
              { label: '總碳水化合物', value: food.nutrition.carbs, unit: 'g', color: Palette.accent.orange },
              { label: '精緻糖', value: food.nutrition.sugar ?? 0, unit: 'g', color: Palette.accent.orange },
              { label: '總脂肪', value: food.nutrition.fat, unit: 'g', color: Palette.accent.purple },
              { label: '飽和脂肪', value: food.nutrition.saturated_fat ?? 0, unit: 'g', color: Palette.accent.purple },
              { label: '反式脂肪', value: food.nutrition.trans_fat ?? 0, unit: 'g', color: Palette.accent.purple },
              { label: '膳食纖維', value: food.nutrition.fiber, unit: 'g', color: Palette.accent.cyan },
              { label: '鈉 (Sodium)', value: food.nutrition.sodium, unit: 'mg', color: food.nutrition.sodium > 800 ? Palette.status.warning : Palette.accent.pink },
              { label: '鈣 (Calcium)', value: food.nutrition.calcium ?? 0, unit: 'mg', color: Palette.accent.cyan },
              { label: '鐵 (Iron)', value: food.nutrition.iron ?? 0, unit: 'mg', color: Palette.accent.cyan },
            ].map((item) => (
              <View key={item.label} style={[styles.nutritionItem, { minWidth: wp(26) }]}>
                <Text style={styles.nutritionLabel}>{item.label}</Text>
                <Text style={[styles.nutritionValue, { color: item.color }]}>
                  {item.value}
                  <Text style={styles.nutritionUnit}> {item.unit}</Text>
                </Text>
              </View>
            ))}
          </View>
        </View>
        );
      })}

      <View style={styles.totalCard}>
        <View style={styles.totalHeader}>
          <Text style={styles.totalTitle}>合計攝取</Text>
          <DataPill tone={totalSodium > 1200 ? 'warning' : 'success'}>鈉 {totalSodium}mg</DataPill>
        </View>
        <View style={styles.totalRow}>
          <View style={styles.totalItem}>
            <Text style={styles.totalLabel}>熱量</Text>
            <Text style={[styles.totalValue, { color: Palette.accent.green }]}>{totalCal} kcal</Text>
          </View>
          <View style={styles.totalItem}>
            <Text style={styles.totalLabel}>蛋白質</Text>
            <Text style={[styles.totalValue, { color: Palette.accent.blue }]}>{totalProtein} g</Text>
          </View>
          <View style={styles.totalItem}>
            <Text style={styles.totalLabel}>項目</Text>
            <Text style={[styles.totalValue, { color: Palette.text.primary }]}>{results.length} 項</Text>
          </View>
        </View>
        <PrimaryButton
          label={submitting ? '儲存中' : '加入今日紀錄'}
          onPress={onAddRecord}
          disabled={controlsDisabled}
          icon={submitting
            ? <ActivityIndicator size="small" color={Palette.text.inverse} />
            : <Ionicons name="add-circle-outline" size={18} color={Palette.text.inverse} />}
        />
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  placeholderCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    gap: Spacing.sm,
    padding: Spacing['3xl'],
    marginBottom: Spacing.xl,
    ...Shadows.soft,
  },
  placeholderTitle: { ...Typography.bodyBold, color: Palette.text.primary },
  placeholderText: { ...Typography.caption, color: Palette.text.tertiary, textAlign: 'center' },
  foodCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.xl,
    gap: Spacing.md,
    ...Shadows.card,
  },
  foodTop: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.md },
  foodInfo: { flex: 1, gap: 4 },
  foodName: { ...Typography.h3, color: Palette.text.primary },
  foodWeight: { ...Typography.caption, color: Palette.text.tertiary },
  portionCard: {
    backgroundColor: Palette.bg.mint,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(31,157,114,0.16)',
    gap: Spacing.sm,
  },
  portionHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.xs },
  portionTitle: { ...Typography.bodyBold, color: Palette.text.secondary, flex: 1 },
  portionAdjustedText: { ...Typography.small, color: Palette.accent.green },
  portionControls: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, flexWrap: 'wrap' },
  portionButton: {
    minHeight: 44,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.sm,
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  portionButtonText: { ...Typography.bodyBold, color: Palette.accent.green },
  portionInput: {
    width: 72,
    minHeight: 44,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 10,
    textAlign: 'center',
    ...Typography.caption,
  },
  portionUnit: { ...Typography.caption, color: Palette.text.tertiary, marginLeft: -4 },
  resetButton: { minHeight: 44, paddingHorizontal: Spacing.sm, justifyContent: 'center' },
  resetButtonText: { ...Typography.caption, color: Palette.status.warning },
  controlDisabled: { opacity: 0.48 },
  tagsRow: { flexDirection: 'row', gap: Spacing.sm, flexWrap: 'wrap' },
  warningBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.accent.orangeDim,
    borderRadius: Radius.md,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.2)',
  },
  warningText: { ...Typography.caption, color: Palette.status.warning, flex: 1 },
  nutritionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutritionItem: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.md, padding: Spacing.sm, flex: 1 },
  nutritionLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 2 },
  nutritionValue: { ...Typography.caption, ...Typography.number },
  nutritionUnit: { ...Typography.small, color: Palette.text.tertiary },
  totalCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: 'rgba(31,157,114,0.18)',
    padding: Spacing.xl,
    gap: Spacing.lg,
    ...Shadows.card,
  },
  totalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.md },
  totalTitle: { ...Typography.h3, color: Palette.text.primary },
  totalRow: { flexDirection: 'row', justifyContent: 'space-between', gap: Spacing.sm },
  totalItem: { flex: 1, backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md },
  totalLabel: { ...Typography.small, color: Palette.text.tertiary, marginBottom: 4 },
  totalValue: { ...Typography.bodyBold, ...Typography.number },
});
