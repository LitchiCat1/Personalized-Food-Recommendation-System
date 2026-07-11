import React from 'react';
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import DataPill from '@/components/ui/data-pill';

type RejectedDetection = {
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
  rejectedDetections: RejectedDetection[];
};

export default function ScannerManualTools({
  rs,
  manualQuery,
  onManualQueryChange,
  manualSearching,
  onManualSearch,
  ocrQuerying,
  onOCRSearch,
  rejectedDetections,
}: Props) {
  return (
    <>
      {rejectedDetections.length > 0 && (
        <View style={styles.rejectedCard}>
          <View style={styles.rejectedHeader}>
            <Ionicons name="alert-circle-outline" size={rs(16)} color={Palette.status.warning} />
            <Text style={styles.rejectedTitle}>已忽略不可靠辨識</Text>
          </View>
          {rejectedDetections.map((item, index) => (
            <View key={`${item.label}_${index}`} style={styles.rejectedItem}>
              <Text style={styles.rejectedText} selectable>
                {item.label} ({Math.round(item.confidence * 100)}%)：{item.reason}
              </Text>
              {(item.search_hints || []).length > 0 ? (
                <Text style={styles.searchHintText}>建議搜尋：{(item.search_hints || []).join('、')}</Text>
              ) : null}
            </View>
          ))}
        </View>
      )}

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
            value={manualQuery}
            onChangeText={onManualQueryChange}
            placeholder="輸入食品名稱，例如：白飯"
            placeholderTextColor={Palette.text.muted}
            style={styles.manualInput}
          />
          <Pressable onPress={onManualSearch} style={styles.manualButton}>
            {manualSearching ? (
              <ActivityIndicator size="small" color={Palette.text.inverse} />
            ) : (
              <Text style={styles.manualButtonText}>搜尋</Text>
            )}
          </Pressable>
        </View>
        <Pressable onPress={onOCRSearch} style={styles.ocrButton}>
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
    </>
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
