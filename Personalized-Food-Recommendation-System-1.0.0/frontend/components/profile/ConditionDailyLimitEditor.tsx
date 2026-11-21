import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';

import { Palette, Radius, Spacing, Typography } from '@/constants/theme';
import PrimaryButton from '@/components/ui/primary-button';
import {
  parseDailyLimitInput, resolveDailyLimitDraft, stepDailyLimitValue,
  type ConditionDailyLimits, type ConditionDailyLimitOverrides, type DailyLimitDraft,
  type DailyLimitNutrient,
} from '@/lib/daily-nutrient-limits';

const LABELS: Record<DailyLimitNutrient, string> = {
  carbs: '總碳水化合物', sugar: '精緻糖', fat: '總脂肪', saturated_fat: '飽和脂肪',
  protein: '蛋白質', sodium: '鈉',
};

type Props = {
  settings: ConditionDailyLimits;
  conditionLabel: string;
  conditionLabels: ReadonlyMap<string, string>;
  disabled: boolean;
  onSave: (values: ConditionDailyLimitOverrides) => Promise<boolean>;
};

export default function ConditionDailyLimitEditor({ settings, conditionLabel, conditionLabels, disabled, onSave }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<DailyLimitDraft>({});
  const [saved, setSaved] = useState(false);
  const dirty = Object.keys(draft).length > 0;
  const resolved = resolveDailyLimitDraft(draft, settings);
  const rows = Object.keys(LABELS) as DailyLimitNutrient[];

  const update = (nutrient: DailyLimitNutrient, raw: string | null) => {
    setSaved(false);
    setDraft((previous) => ({ ...previous, [nutrient]: raw }));
  };

  const save = async () => {
    if (!dirty || !resolved || disabled) return;
    if (await onSave(resolved)) {
      setDraft({});
      setSaved(true);
    }
  };

  return (
    <View style={styles.panel}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${conditionLabel}每日營養上限`}
        accessibilityState={{ expanded }}
        onPress={() => setExpanded((value) => !value)}
        style={styles.heading}
      >
        <Text style={styles.title}>每日營養上限{dirty ? ' · 未儲存' : ''}</Text>
        <Ionicons name={expanded ? 'chevron-up-outline' : 'chevron-down-outline'} size={18} color={Palette.text.secondary} />
      </Pressable>
      {expanded ? (
        <View style={styles.body}>
          {rows.map((nutrient) => {
            const setting = settings[nutrient];
            if (!setting) return null;
            const label = LABELS[nutrient];
            const raw = draft[nutrient];
            const value = raw === null ? String(setting.default_value) : raw ?? String(setting.value);
            const invalid = raw != null && parseDailyLimitInput(raw, setting) === null;
            const decrement = stepDailyLimitValue(value, -1, setting);
            const increment = stepDailyLimitValue(value, 1, setting);
            const sources = setting.effective_condition_ids.map((id) => conditionLabels.get(id) ?? id);
            return (
              <View key={nutrient} style={styles.row}>
                <Text style={styles.nutrient}>{label}</Text>
                <Text style={styles.muted}>
                  預設 {setting.default_value} {setting.unit} · {setting.source === 'custom' ? `個人設定 ${setting.value} ${setting.unit}` : '目前使用系統預設'}
                  {!setting.active ? ' · 此病況規則暫未生效' : ''}
                </Text>
                <View style={styles.controls}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`減少${label}每日上限`}
                    accessibilityHint={`每次減少 ${setting.step} ${setting.unit}`}
                    disabled={disabled || decrement === null || decrement === value}
                    onPress={() => { if (decrement !== null) update(nutrient, decrement); }}
                    style={({ pressed }) => [styles.control, (disabled || decrement === null || decrement === value) && styles.disabled, pressed && styles.pressed]}
                  >
                    <Ionicons name="remove-outline" size={20} color={Palette.text.primary} />
                  </Pressable>
                  <TextInput
                    accessibilityLabel={`${label}每日上限（${setting.unit}）`}
                    editable={!disabled}
                    keyboardType={setting.precision ? 'decimal-pad' : 'number-pad'}
                    inputMode={setting.precision ? 'decimal' : 'numeric'}
                    maxLength={16}
                    value={value}
                    onChangeText={(text) => update(nutrient, text)}
                    style={[styles.input, invalid && styles.invalid]}
                  />
                  <Text style={styles.muted} aria-hidden>{setting.unit}</Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`增加${label}每日上限`}
                    accessibilityHint={`每次增加 ${setting.step} ${setting.unit}`}
                    disabled={disabled || increment === null || increment === value}
                    onPress={() => { if (increment !== null) update(nutrient, increment); }}
                    style={({ pressed }) => [styles.control, (disabled || increment === null || increment === value) && styles.disabled, pressed && styles.pressed]}
                  >
                    <Ionicons name="add-outline" size={20} color={Palette.text.primary} />
                  </Pressable>
                </View>
                {invalid ? (
                  <Text style={styles.error}>{value.trim() ? `請輸入 ${setting.min} 至 ${setting.max} ${setting.unit}${setting.precision ? `，最多 ${setting.precision} 位小數` : '的整數'}。` : '請輸入上限，或恢復預設。'}</Text>
                ) : null}
                <View style={styles.result}>
                  <Text style={styles.applied}>首頁上限 {setting.effective_value} {setting.unit}{sources.length ? ` · ${sources.join('、')}` : ' · 系統上限'}</Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`恢復${label}預設`}
                    disabled={disabled || raw === null || (raw === undefined && setting.source === 'default')}
                    onPress={() => update(nutrient, null)}
                    style={({ pressed }) => [styles.reset, (disabled || raw === null || (raw === undefined && setting.source === 'default')) && styles.disabled, pressed && styles.pressed]}
                  >
                    <Ionicons name="refresh-outline" size={16} color={Palette.text.secondary} />
                    <Text style={styles.muted}>恢復預設</Text>
                  </Pressable>
                </View>
              </View>
            );
          })}
          {saved ? <Text accessibilityLiveRegion="polite" style={styles.saved}>已儲存每日營養上限</Text> : null}
          <PrimaryButton label={`儲存${conditionLabel}上限`} disabled={disabled || !dirty || resolved === null} onPress={() => { void save(); }} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { marginLeft: Spacing.md, borderLeftWidth: 1, borderLeftColor: Palette.border.subtle, paddingLeft: Spacing.md },
  heading: { minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm, paddingVertical: Spacing.sm },
  title: { ...Typography.bodyBold, flex: 1, color: Palette.text.primary },
  body: { gap: Spacing.sm, paddingBottom: Spacing.sm },
  row: { gap: Spacing.xs, borderTopWidth: 1, borderTopColor: Palette.border.subtle, paddingTop: Spacing.sm },
  nutrient: { ...Typography.bodyBold, color: Palette.text.primary },
  muted: { ...Typography.caption, color: Palette.text.secondary },
  controls: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  control: { width: 44, height: 44, borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.sm, alignItems: 'center', justifyContent: 'center', backgroundColor: Palette.bg.elevated },
  input: { ...Typography.body, ...Typography.number, minWidth: 58, flex: 1, height: 44, textAlign: 'center', borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.sm, paddingHorizontal: Spacing.xs, color: Palette.text.primary, backgroundColor: Palette.bg.card },
  result: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'space-between', columnGap: Spacing.sm },
  applied: { ...Typography.caption, ...Typography.number, color: Palette.text.secondary, flexGrow: 1, flexBasis: 120 },
  reset: { minHeight: 44, paddingHorizontal: Spacing.xs, flexDirection: 'row', alignItems: 'center', gap: Spacing.xs },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.72 },
  invalid: { borderColor: Palette.status.error },
  error: { ...Typography.caption, color: Palette.status.error },
  saved: { ...Typography.caption, color: Palette.status.success },
});
