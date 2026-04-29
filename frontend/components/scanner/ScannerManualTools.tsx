import React from 'react';
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';

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
        <View style={[styles.rejectedCard, { padding: rs(14) }]}> 
          <View style={styles.rejectedHeader}>
            <Ionicons name="alert-circle" size={rs(15)} color={Palette.status.warning} />
            <Text style={[styles.rejectedTitle, { fontSize: rs(13) }]}>已忽略不可靠辨識</Text>
          </View>
          {rejectedDetections.map((item, index) => (
            <View key={`${item.label}_${index}`} style={styles.rejectedItem}>
              <Text style={[styles.rejectedText, { fontSize: rs(11) }]}> 
                {item.label} ({Math.round(item.confidence * 100)}%)：{item.reason}
              </Text>
              {(item.search_hints || []).length > 0 ? (
                <Text style={[styles.searchHintText, { fontSize: rs(10) }]}>建議搜尋：{(item.search_hints || []).join('、')}</Text>
              ) : null}
            </View>
          ))}
        </View>
      )}

      <View style={[styles.manualCard, { padding: rs(16) }]}> 
        <View style={styles.manualHeader}>
          <Ionicons name="search" size={rs(16)} color={Palette.accent.cyan} />
          <Text style={[styles.manualTitle, { fontSize: rs(15) }]}>辨識不穩時改用 TFDA 手動搜尋</Text>
        </View>
        <Text style={[styles.manualHint, { fontSize: rs(11) }]}>適合處理飲料、容器、便當配菜或模型無法正確辨識的食物。</Text>
        <View style={styles.manualSearchRow}>
          <TextInput
            value={manualQuery}
            onChangeText={onManualQueryChange}
            placeholder="輸入食品名稱，例如：白飯"
            placeholderTextColor={Palette.text.tertiary}
            style={[styles.manualInput, { fontSize: rs(13) }]}
          />
          <Pressable onPress={onManualSearch} style={styles.manualButton}>
            {manualSearching ? (
              <ActivityIndicator size="small" color={Palette.text.inverse} />
            ) : (
              <Text style={[styles.manualButtonText, { fontSize: rs(12) }]}>搜尋</Text>
            )}
          </Pressable>
        </View>
        <Pressable onPress={onOCRSearch} style={styles.ocrButton}>
          {ocrQuerying ? (
            <ActivityIndicator size="small" color={Palette.text.inverse} />
          ) : (
            <>
              <Ionicons name="scan" size={rs(15)} color={Palette.text.inverse} />
              <Text style={[styles.ocrButtonText, { fontSize: rs(12) }]}>辨識營養標示照片</Text>
            </>
          )}
        </Pressable>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  rejectedCard: {
    backgroundColor: 'rgba(251, 191, 36, 0.08)', borderRadius: Radius.lg, marginBottom: Spacing.lg,
    borderWidth: 1, borderColor: 'rgba(251, 191, 36, 0.22)',
  },
  rejectedHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.sm },
  rejectedTitle: { ...Typography.bodyBold, color: Palette.status.warning },
  rejectedItem: { marginBottom: 6 },
  rejectedText: { ...Typography.small, color: Palette.text.secondary },
  searchHintText: { ...Typography.small, color: Palette.accent.cyan, marginTop: 2 },

  manualCard: {
    backgroundColor: Palette.bg.card, borderRadius: Radius.xl, marginBottom: Spacing.xl,
    borderWidth: 1, borderColor: Palette.border.subtle, ...Shadows.card,
  },
  manualHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.sm },
  manualTitle: { ...Typography.h3, color: Palette.text.primary, flex: 1 },
  manualHint: { ...Typography.small, color: Palette.text.tertiary, lineHeight: 18, marginBottom: Spacing.md },
  manualSearchRow: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'center' },
  manualInput: {
    flex: 1, backgroundColor: Palette.bg.elevated, borderRadius: Radius.md,
    borderWidth: 1, borderColor: Palette.border.subtle, color: Palette.text.primary,
    paddingHorizontal: Spacing.md, paddingVertical: Spacing.md,
  },
  manualButton: {
    minWidth: 72, alignItems: 'center', justifyContent: 'center', backgroundColor: Palette.accent.cyan,
    borderRadius: Radius.md, paddingHorizontal: Spacing.md, paddingVertical: Spacing.md,
  },
  manualButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
  ocrButton: {
    marginTop: Spacing.md, flexDirection: 'row', gap: Spacing.sm,
    alignItems: 'center', justifyContent: 'center', backgroundColor: Palette.accent.purple,
    borderRadius: Radius.md, paddingVertical: Spacing.md,
  },
  ocrButtonText: { ...Typography.bodyBold, color: Palette.text.inverse },
});
