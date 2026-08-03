import React from 'react';
import { StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';
import { Palette, Radius, Spacing, Typography } from '@/constants/theme';

type Props = TextInputProps & {
  label: string;
  error?: string;
  unit?: string;
};

export default function FormInput({ label, error, unit, style, ...inputProps }: Props) {
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.inputShell, error ? styles.inputShellError : undefined]}>
        <TextInput
          {...inputProps}
          accessibilityLabel={inputProps.accessibilityLabel || label}
          placeholderTextColor={Palette.text.muted}
          selectionColor={Palette.accent.green}
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
  inputShellError: { borderColor: Palette.status.error, backgroundColor: 'rgba(226,85,85,0.06)' },
  input: {
    minWidth: 0,
    minHeight: 46,
    flex: 1,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    ...Typography.body,
  },
  unit: { ...Typography.caption, ...Typography.number, color: Palette.text.tertiary, paddingRight: Spacing.md },
  error: { ...Typography.small, color: Palette.status.error },
});
