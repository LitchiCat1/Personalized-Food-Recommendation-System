import React, { useState } from 'react';
import { Platform, StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';
import { Palette, Radius, Spacing, Typography } from '@/constants/theme';

type Props = TextInputProps & {
  label: string;
  error?: string;
  unit?: string;
};

export default function FormInput({ label, error, unit, style, onFocus, onBlur, ...inputProps }: Props) {
  const [focused, setFocused] = useState(false);

  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View
        style={[
          styles.inputShell,
          focused ? styles.inputShellFocused : undefined,
          error ? styles.inputShellError : undefined,
        ]}
      >
        <TextInput
          {...inputProps}
          accessibilityLabel={inputProps.accessibilityLabel || label}
          // 讀屏軟體要知道這一格是不是有問題，不能只靠邊框變色。
          aria-invalid={Boolean(error)}
          placeholderTextColor={Palette.text.muted}
          selectionColor={Palette.accent.green}
          onFocus={(event) => {
            setFocused(true);
            onFocus?.(event);
          }}
          onBlur={(event) => {
            setFocused(false);
            onBlur?.(event);
          }}
          style={[styles.input, style]}
        />
        {unit ? <Text style={styles.unit}>{unit}</Text> : null}
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { minWidth: 0, gap: Spacing.xs },
  label: { ...Typography.small, color: Palette.text.secondary },
  inputShell: {
    minHeight: 48,
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Palette.bg.elevated,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    borderRadius: Radius.lg,
  },
  /**
   * 焦點框畫在外殼上，不是畫在 TextInput 上。
   *
   * 先前用的是瀏覽器預設的 outline，它只框住 flex:1 的輸入框本身，
   * 而且會畫在同一列的單位文字上面——輸入熱量時「kcal」被邊框蓋掉一半。
   */
  inputShellFocused: { borderColor: Palette.accent.green },
  inputShellError: { borderColor: Palette.status.error, backgroundColor: Palette.status.errorDim },
  input: {
    minWidth: 0,
    minHeight: 46,
    flex: 1,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    ...Typography.body,
    ...Platform.select({ web: { outlineStyle: 'none' as any }, default: {} }),
  },
  unit: { ...Typography.caption, ...Typography.number, color: Palette.text.tertiary, paddingRight: Spacing.md },
  error: { ...Typography.small, color: Palette.status.error },
});
