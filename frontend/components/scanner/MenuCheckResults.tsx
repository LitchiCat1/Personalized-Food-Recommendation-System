import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import DataPill from '@/components/ui/data-pill';
import type { MenuPhotoCheckItem, MenuPhotoCheckResponse } from '@/lib/api';

type Props = {
  result: MenuPhotoCheckResponse;
};

/**
 * 拍菜單看能不能吃的結果：分成「可以吃」「要注意」「不建議」三區。
 * 每一區都列出全部品項，不只前幾名——使用者問的是「上面哪些可以吃」。
 */
export default function MenuCheckResults({ result }: Props) {
  const { safe_items: safe, caution_items: caution, not_recommended_items: blocked } = result;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>菜單上哪些可以吃</Text>
        <DataPill tone="info">{result.total_items} 道菜</DataPill>
      </View>
      <View style={styles.summaryRow}>
        <DataPill tone="success">可以吃 {safe.length}</DataPill>
        <DataPill tone="warning">要注意 {caution.length}</DataPill>
        <DataPill tone="danger">不建議 {blocked.length}</DataPill>
      </View>

      <Section
        icon="checkmark-circle-outline"
        color={Palette.status.success}
        title="可以吃"
        empty="沒有完全沒問題的菜，看看下面「要注意」的。"
        count={safe.length}
      >
        {safe.map((item) => <EdibleItem key={item.item_id || item.item_name} item={item} />)}
      </Section>

      <Section
        icon="alert-circle-outline"
        color={Palette.status.warning}
        title="可以吃，但要注意"
        empty="沒有需要特別注意的菜。"
        count={caution.length}
      >
        {caution.map((item) => <EdibleItem key={item.item_id || item.item_name} item={item} caution />)}
      </Section>

      <Section
        icon="close-circle-outline"
        color={Palette.status.error}
        title="不建議吃"
        empty="沒有需要避開的菜。"
        count={blocked.length}
      >
        {blocked.map((item, index) => (
          <View key={`${item.item_name}_${index}`} style={[styles.item, styles.itemBlocked]}>
            <View style={styles.itemTop}>
              <Text style={styles.itemName}>{item.item_name}</Text>
              {item.price ? <Text style={styles.price}>${item.price}</Text> : null}
            </View>
            <Text style={styles.blockedReason}>原因：{item.reasons.join('、')}</Text>
          </View>
        ))}
      </Section>

      <View style={styles.disclaimer}>
        <Ionicons name="information-circle-outline" size={15} color={Palette.text.tertiary} />
        <Text style={styles.disclaimerText}>{result.disclaimer}</Text>
      </View>
    </View>
  );
}

function Section({
  icon,
  color,
  title,
  empty,
  count,
  children,
}: {
  icon: React.ComponentProps<typeof Ionicons>['name'];
  color: string;
  title: string;
  empty: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Ionicons name={icon} size={18} color={color} />
        <Text style={[styles.sectionTitle, { color }]}>{title}</Text>
      </View>
      {count === 0 ? <Text style={styles.emptyText}>{empty}</Text> : <View style={styles.list}>{children}</View>}
    </View>
  );
}

function EdibleItem({ item, caution = false }: { item: MenuPhotoCheckItem; caution?: boolean }) {
  const cautionReasons = item.medical_risk?.caution_reasons || [];
  const notes = caution && cautionReasons.length > 0 ? cautionReasons : item.reasons || [];
  return (
    <View style={[styles.item, caution && styles.itemCaution]}>
      <View style={styles.itemTop}>
        <Text style={styles.itemName}>{item.item_name}</Text>
        {item.price ? <Text style={styles.price}>${item.price}</Text> : null}
      </View>
      <View style={styles.macroRow}>
        <Text style={styles.macro}>熱量 {Math.round(item.calories || 0)} kcal</Text>
        <Text style={styles.macro}>蛋白質 {Math.round(item.protein || 0)} g</Text>
        <Text style={styles.macro}>鈉 {Math.round(item.sodium || 0)} mg</Text>
      </View>
      {notes.length > 0 ? (
        <Text style={caution ? styles.cautionReason : styles.reason}>
          {caution ? '注意：' : ''}{notes.join('、')}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    padding: Spacing.lg,
    marginBottom: Spacing.xl,
    gap: Spacing.md,
    ...Shadows.card,
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm },
  title: { ...Typography.h3, color: Palette.text.primary, flexShrink: 1 },
  summaryRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  section: { gap: Spacing.sm, marginTop: Spacing.xs },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.xs },
  sectionTitle: { ...Typography.bodyBold },
  list: { gap: Spacing.sm },
  emptyText: { ...Typography.small, color: Palette.text.tertiary },
  item: {
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.elevated,
    padding: Spacing.md,
    gap: 4,
  },
  itemCaution: { borderColor: 'rgba(245,158,11,0.35)', backgroundColor: Palette.accent.orangeDim },
  itemBlocked: { borderColor: 'rgba(226,85,85,0.3)' },
  itemTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: Spacing.sm },
  itemName: { ...Typography.bodyBold, color: Palette.text.primary, flex: 1 },
  price: { ...Typography.caption, color: Palette.text.secondary },
  macroRow: { flexDirection: 'row', flexWrap: 'wrap', columnGap: Spacing.md, rowGap: 2 },
  macro: { ...Typography.small, color: Palette.text.secondary },
  reason: { ...Typography.small, color: Palette.accent.green },
  cautionReason: { ...Typography.small, color: Palette.status.warning },
  blockedReason: { ...Typography.small, color: Palette.status.error },
  disclaimer: { flexDirection: 'row', gap: Spacing.xs, alignItems: 'flex-start', marginTop: Spacing.xs },
  disclaimerText: { ...Typography.small, color: Palette.text.tertiary, flex: 1 },
});
