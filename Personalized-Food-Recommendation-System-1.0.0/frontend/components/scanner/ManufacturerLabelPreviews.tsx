import { Link } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Radius, Spacing, Typography } from '@/constants/theme';
import type { ManufacturerLabelPreview } from '@/lib/scanner-manufacturer-label';

const formatNumber = (value: number) => value > 0 && value < 0.000001
  ? value.toPrecision(6) : value.toLocaleString('zh-TW', { maximumFractionDigits: 6 });

export default function ManufacturerLabelPreviews({ previews }: { previews: ManufacturerLabelPreview[] }) {
  return previews.map((preview) => (
    <View style={styles.card} key={preview.id}>
      <Text accessibilityRole="header" style={styles.title}>{preview.visualName} · 營養預覽</Text>
      <Text style={styles.metadata}>廠商營養標示：{preview.publisher}</Text>
      <Text style={styles.metadata}>來源產品：{preview.product}</Text>
      {preview.datasetName ? <Text style={styles.metadata}>刊載來源：{preview.datasetName}</Text> : null}
      {preview.traceCode ? <Text selectable style={styles.metadata}>產品追溯碼：{preview.traceCode}</Text> : null}
      <Link href={preview.url} target="_blank" rel="noopener noreferrer" style={styles.link}>
        <Ionicons name="open-outline" size={16} color={Palette.accent.blue} />
        {preview.datasetName ? ' 查看資料集' : ' 查看原始營養標示'}
      </Link>
      <Text style={styles.metadata}>{preview.basis === 'per_serving'
        ? `原表每份 ${formatNumber(preview.basisWeight)} g，以下換算為每 100 g`
        : '原表基準：每 100 g'}</Text>
      {preview.nutrients.map(({ key, name, value, bound, unit }) => (
        <View key={key} style={styles.row}>
          <Text style={styles.nutrientName}>{name}</Text>
          <Text style={styles.value}>{value !== null ? `${formatNumber(value)} ${unit}`
            : bound !== null ? `< ${formatNumber(bound)} ${unit}` : '未提供'}</Text>
        </View>
      ))}
      <Text style={styles.metadata}>僅供預覽，未計入攝取合計或飲食紀錄。</Text>
    </View>
  ));
}

const styles = StyleSheet.create({
  card: { backgroundColor: Palette.bg.card, borderColor: Palette.border.subtle, borderWidth: 1,
    borderRadius: Radius.sm, padding: Spacing.md, gap: Spacing.xs },
  title: { ...Typography.h3, color: Palette.text.primary },
  metadata: { ...Typography.caption, color: Palette.text.secondary },
  link: { alignSelf: 'flex-start', paddingVertical: Spacing.sm, minHeight: 44,
    color: Palette.accent.blue, textDecorationLine: 'underline' },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: Spacing.sm,
    paddingVertical: Spacing.xs, borderBottomWidth: 1, borderColor: Palette.border.subtle },
  nutrientName: { flexShrink: 1, color: Palette.text.secondary },
  value: { flexShrink: 1, textAlign: 'right', color: Palette.text.primary, fontVariant: ['tabular-nums'] },
});
