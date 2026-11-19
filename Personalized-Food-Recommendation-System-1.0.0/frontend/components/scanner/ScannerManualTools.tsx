import React from 'react';
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import DataPill from '@/components/ui/data-pill';
import type { NutritionEnrichmentItem } from '@/lib/nutrition-enrichment-api';

type RejectedDetection = {
  item_id?: string;
  label: string;
  confidence: number;
  reason: string;
  search_hints?: string[];
};

type Props = {
  rs: (value: number) => number;
  manualQuery: string;
  onManualQueryChange: (value: string) => void;
  manualSearching: boolean;
  onManualSearch: () => void;
  ocrQuerying: boolean;
  onOCRSearch: () => void;
};

export function ScannerPendingFoods({
  rs, items, identityItems = [], identityEnabled = false, identityDrafts = {}, identityPending = {},
  identityErrors = {}, identityLocked = false, identitySubmitting = false,
  onIdentityDraftChange, onConfirmIdentity,
}: {
  rs: (value: number) => number;
  items: RejectedDetection[];
  identityItems?: NutritionEnrichmentItem[];
  identityEnabled?: boolean;
  identityDrafts?: Record<string, string>;
  identityPending?: Record<string, { name_zh: string }>;
  identityErrors?: Record<string, string>;
  identityLocked?: boolean;
  identitySubmitting?: boolean;
  onIdentityDraftChange?: (itemId: string, value: string) => void;
  onConfirmIdentity?: (itemId: string) => void;
}) {
  if (items.length === 0) return null;
  return (
        <View style={styles.rejectedCard}>
          <View style={styles.rejectedHeader}>
            <Ionicons name="alert-circle-outline" size={rs(16)} color={Palette.status.warning} />
            <Text style={styles.rejectedTitle}>需確認或補充營養資料的食物</Text>
          </View>
          {items.map((item, index) => (
            <View key={`${item.label}_${index}`} style={styles.rejectedItem}>
              <Text style={styles.rejectedText} selectable>
                {item.label} ({Math.round(item.confidence * 100)}%)：{item.reason}
              </Text>
              {(item.search_hints || []).length > 0 ? (
                <Text style={styles.searchHintText}>建議搜尋：{(item.search_hints || []).join('、')}</Text>
              ) : null}
              {identityEnabled && item.item_id ? (() => {
                const identity = identityItems.find((candidate) => candidate.item_id === item.item_id &&
                  candidate.identity_confirmation_required === true && candidate.validation_issues.length === 0);
                if (!identity) return null;
                const pending = identityPending[item.item_id];
                const value = pending?.name_zh ?? identityDrafts[item.item_id] ?? identity.name_zh;
                return (
                  <View style={styles.identityConfirmSection}>
                    <Text style={styles.identityConfirmLabel}>確認食材名稱</Text>
                    <TextInput
                      accessibilityLabel={`${item.label} 的食材名稱`}
                      value={value}
                      onChangeText={(next) => onIdentityDraftChange?.(item.item_id!, next)}
                      maxLength={120}
                      editable={!identityLocked}
                      autoCorrect={false}
                      style={[styles.identityConfirmInput, identityLocked && styles.identityDisabled]}
                    />
                    <Text style={styles.identityConfirmHint}>只確認名稱；不會提高影像信心或修改估計份量。</Text>
                    {identityErrors[item.item_id] ? (
                      <Text accessibilityRole="alert" style={styles.identityError}>{identityErrors[item.item_id]}</Text>
                    ) : null}
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={pending ? '以相同名稱重試' : '確認食材名稱並重新查找'}
                      onPress={() => onConfirmIdentity?.(item.item_id!)}
                      disabled={identitySubmitting || (identityLocked && !pending)}
                      style={[styles.identityConfirmButton,
                        (identitySubmitting || (identityLocked && !pending)) && styles.identityDisabled]}
                    >
                      {identitySubmitting ? <ActivityIndicator size="small" color={Palette.text.inverse} /> : (
                        <>
                          <Ionicons name="checkmark-circle-outline" size={17} color={Palette.text.inverse} />
                          <Text style={styles.identityConfirmButtonText}>{pending ? '以相同名稱重試' : '確認並重新查找'}</Text>
                        </>
                      )}
                    </Pressable>
                  </View>
                );
              })() : null}
            </View>
          ))}
        </View>
  );
}

export default function ScannerManualTools({
  rs,
  manualQuery,
  onManualQueryChange,
  manualSearching,
  onManualSearch,
  ocrQuerying,
  onOCRSearch,
}: Props) {
  return (
      <View style={styles.manualCard}>
        <View style={styles.manualHeader}>
          <View style={styles.iconCircle}>
            <Ionicons name="search-outline" size={rs(17)} color={Palette.accent.green} />
          </View>
          <View style={styles.manualHeaderCopy}>
            <Text style={styles.manualTitle}>手動備援</Text>
            <Text style={styles.manualHint}>辨識不穩時，使用 TFDA 或自訂食品資料庫補上紀錄。</Text>
          </View>
          <DataPill tone="info">TFDA</DataPill>
        </View>
        <View style={styles.manualSearchRow}>
          <TextInput
            accessibilityLabel="搜尋食品名稱"
            value={manualQuery}
            onChangeText={onManualQueryChange}
            onSubmitEditing={onManualSearch}
            returnKeyType="search"
            placeholder="輸入食品名稱，例如：白飯"
            placeholderTextColor={Palette.text.muted}
            style={styles.manualInput}
          />
          <Pressable accessibilityRole="button" accessibilityLabel="搜尋" aria-busy={manualSearching} onPress={onManualSearch} style={styles.manualButton}>
            {manualSearching ? (
              <ActivityIndicator size="small" color={Palette.text.inverse} />
            ) : (
              <Text style={styles.manualButtonText}>搜尋</Text>
            )}
          </Pressable>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="辨識營養標示照片" aria-busy={ocrQuerying} onPress={onOCRSearch} style={styles.ocrButton}>
          {ocrQuerying ? (
            <ActivityIndicator size="small" color={Palette.accent.blue} />
          ) : (
            <>
              <Ionicons name="document-text-outline" size={rs(16)} color={Palette.accent.blue} />
              <Text style={styles.ocrButtonText}>辨識營養標示照片</Text>
            </>
          )}
        </Pressable>
      </View>
  );
}

const styles = StyleSheet.create({
  rejectedCard: {
    backgroundColor: Palette.accent.orangeDim,
    borderRadius: Radius.lg,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: 'rgba(245,158,11,0.22)',
    padding: Spacing.md,
  },
  rejectedHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.sm },
  rejectedTitle: { ...Typography.bodyBold, color: Palette.status.warning },
  rejectedItem: { marginBottom: 6 },
  rejectedText: { ...Typography.small, color: Palette.text.secondary },
  searchHintText: { ...Typography.small, color: Palette.accent.blue, marginTop: 2 },
  identityConfirmSection: { marginTop: Spacing.sm, gap: Spacing.xs },
  identityConfirmLabel: { ...Typography.caption, color: Palette.text.primary },
  identityConfirmInput: {
    minHeight: 46, borderWidth: 1, borderColor: Palette.border.subtle,
    borderRadius: Radius.md, backgroundColor: Palette.bg.card, color: Palette.text.primary,
    paddingHorizontal: Spacing.sm, ...Typography.body,
  },
  identityConfirmHint: { ...Typography.caption, color: Palette.text.secondary },
  identityError: { ...Typography.caption, color: Palette.status.error },
  identityConfirmButton: {
    minHeight: 46, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: Spacing.xs,
    borderRadius: Radius.md, backgroundColor: Palette.accent.green, paddingHorizontal: Spacing.md,
  },
  identityConfirmButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
  identityDisabled: { opacity: 0.55 },
  manualCard: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.xl,
    gap: Spacing.md,
    ...Shadows.card,
  },
  manualHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  iconCircle: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Palette.accent.greenDim,
    alignItems: 'center',
    justifyContent: 'center',
  },
  manualHeaderCopy: { flex: 1, gap: 2 },
  manualTitle: { ...Typography.h3, color: Palette.text.primary },
  manualHint: { ...Typography.caption, color: Palette.text.secondary },
  manualSearchRow: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'center' },
  manualInput: {
    flex: 1,
    minHeight: 48,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    ...Typography.caption,
  },
  manualButton: {
    minHeight: 48,
    minWidth: 72,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.accent.green,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
  },
  manualButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
  ocrButton: {
    minHeight: 46,
    flexDirection: 'row',
    gap: Spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.accent.blueDim,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: 'rgba(47,128,237,0.18)',
  },
  ocrButtonText: { ...Typography.bodyBold, color: Palette.accent.blue },
});
