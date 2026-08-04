import React, { useMemo, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import { formatDateInput, formatLocalDateKey, parseDateInput } from '@/lib/dietary-records';

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  maximumDate?: string;
  minimumDate?: string;
  disabled?: boolean;
};

type CalendarMonth = { year: number; month: number };

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

export default function DatePicker({
  label,
  value,
  onChange,
  error,
  maximumDate,
  minimumDate,
  disabled,
}: Props) {
  const selectedDateKey = parseDateInput(value);
  const maximumDateKey = maximumDate ? parseDateInput(maximumDate) : null;
  const minimumDateKey = minimumDate ? parseDateInput(minimumDate) : null;
  const [visible, setVisible] = useState(false);
  const [calendarMonth, setCalendarMonth] = useState<CalendarMonth>(() => monthFromDateKey(selectedDateKey));
  const calendarDays = useMemo(
    () => buildCalendarDays(calendarMonth.year, calendarMonth.month),
    [calendarMonth]
  );
  const nextMonthDisabled = Boolean(
    maximumDateKey && monthKey(calendarMonth.year, calendarMonth.month + 1) > maximumDateKey.slice(0, 7)
  );
  const previousMonthDisabled = Boolean(
    minimumDateKey && monthKey(calendarMonth.year, calendarMonth.month - 1) < minimumDateKey.slice(0, 7)
  );

  const openCalendar = () => {
    if (disabled) return;
    setCalendarMonth(monthFromDateKey(selectedDateKey));
    setVisible(true);
  };

  const changeMonth = (offset: number) => {
    setCalendarMonth((current) => normalizeMonth(current.year, current.month + offset));
  };

  const selectDate = (dateKey: string) => {
    onChange(formatDateInput(dateKey));
    setVisible(false);
  };

  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`選擇${label}，目前為 ${selectedDateKey ? formatAccessibleDate(selectedDateKey) : '尚未選擇'}`}
        accessibilityState={{ disabled: Boolean(disabled), expanded: visible }}
        disabled={disabled}
        onPress={openCalendar}
        style={({ pressed }) => [
          styles.field,
          error && styles.fieldError,
          pressed && styles.pressed,
          disabled && styles.disabled,
        ]}
      >
        <Text style={[styles.value, !selectedDateKey && styles.placeholder]}>
          {selectedDateKey ? formatDateInput(selectedDateKey) : '選擇日期'}
        </Text>
        <Ionicons name="calendar-outline" size={20} color={error ? Palette.status.error : Palette.accent.green} />
      </Pressable>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}

      <Modal visible={visible} transparent animationType="fade" onRequestClose={() => setVisible(false)}>
        <View style={styles.modalLayer}>
          <Pressable accessibilityLabel="關閉日期選擇器" style={styles.backdrop} onPress={() => setVisible(false)} />
          <View accessibilityViewIsModal style={styles.calendarCard}>
            <View style={styles.calendarHeader}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="上一個月"
                accessibilityState={{ disabled: previousMonthDisabled }}
                disabled={previousMonthDisabled}
                onPress={() => changeMonth(-1)}
                style={({ pressed }) => [styles.navigationButton, pressed && styles.pressed, previousMonthDisabled && styles.disabled]}
              >
                <Ionicons name="chevron-back" size={22} color={Palette.text.secondary} />
              </Pressable>
              <Text style={styles.monthTitle}>{calendarMonth.year} 年 {calendarMonth.month + 1} 月</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="下一個月"
                accessibilityState={{ disabled: nextMonthDisabled }}
                disabled={nextMonthDisabled}
                onPress={() => changeMonth(1)}
                style={({ pressed }) => [styles.navigationButton, pressed && styles.pressed, nextMonthDisabled && styles.disabled]}
              >
                <Ionicons name="chevron-forward" size={22} color={Palette.text.secondary} />
              </Pressable>
            </View>

            <View style={styles.weekdayRow}>
              {WEEKDAYS.map((weekday) => (
                <View key={weekday} style={styles.calendarColumn}>
                  <Text style={styles.weekday}>{weekday}</Text>
                </View>
              ))}
            </View>

            <View style={styles.dayGrid}>
              {calendarDays.map((dateKey, index) => {
                if (!dateKey) return <View key={`empty-${index}`} style={styles.calendarColumn} />;
                const dayDisabled = Boolean(
                  (maximumDateKey && dateKey > maximumDateKey)
                  || (minimumDateKey && dateKey < minimumDateKey)
                );
                const selected = dateKey === selectedDateKey;
                const today = dateKey === formatLocalDateKey(new Date());
                return (
                  <View key={dateKey} style={styles.calendarColumn}>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`選擇 ${formatAccessibleDate(dateKey)}`}
                      accessibilityState={{ disabled: dayDisabled, selected }}
                      disabled={dayDisabled}
                      onPress={() => selectDate(dateKey)}
                      style={({ pressed }) => [
                        styles.dayButton,
                        today && styles.todayButton,
                        selected && styles.selectedDayButton,
                        pressed && !dayDisabled && styles.pressed,
                        dayDisabled && styles.dayButtonDisabled,
                      ]}
                    >
                      <Text style={[
                        styles.dayText,
                        today && styles.todayText,
                        selected && styles.selectedDayText,
                        dayDisabled && styles.dayTextDisabled,
                      ]}>
                        {Number(dateKey.slice(-2))}
                      </Text>
                    </Pressable>
                  </View>
                );
              })}
            </View>

            <Pressable
              accessibilityRole="button"
              accessibilityLabel="取消選擇日期"
              onPress={() => setVisible(false)}
              style={({ pressed }) => [styles.cancelButton, pressed && styles.pressed]}
            >
              <Text style={styles.cancelText}>取消</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function monthFromDateKey(dateKey: string | null): CalendarMonth {
  if (dateKey) {
    const [year, month] = dateKey.split('-').map(Number);
    return { year, month: month - 1 };
  }
  const today = new Date();
  return { year: today.getFullYear(), month: today.getMonth() };
}

function normalizeMonth(year: number, month: number): CalendarMonth {
  const date = new Date(year, month, 1, 12);
  return { year: date.getFullYear(), month: date.getMonth() };
}

function monthKey(year: number, month: number): string {
  const normalized = normalizeMonth(year, month);
  return `${normalized.year}-${String(normalized.month + 1).padStart(2, '0')}`;
}

function buildCalendarDays(year: number, month: number): (string | null)[] {
  const firstWeekday = new Date(year, month, 1, 12).getDay();
  const daysInMonth = new Date(year, month + 1, 0, 12).getDate();
  return Array.from({ length: 42 }, (_, index) => {
    const day = index - firstWeekday + 1;
    if (day < 1 || day > daysInMonth) return null;
    return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  });
}

function formatAccessibleDate(dateKey: string): string {
  const [year, month, day] = dateKey.split('-').map(Number);
  return `${year} 年 ${month} 月 ${day} 日`;
}

const styles = StyleSheet.create({
  group: { minWidth: 0, gap: Spacing.xs },
  label: { ...Typography.small, color: Palette.text.secondary },
  field: {
    minHeight: 48,
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.sm,
    paddingHorizontal: Spacing.md,
    backgroundColor: Palette.bg.elevated,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    borderRadius: Radius.lg,
  },
  fieldError: { borderColor: Palette.status.error, backgroundColor: 'rgba(226,85,85,0.06)' },
  value: { ...Typography.body, ...Typography.number, color: Palette.text.primary, flex: 1 },
  placeholder: { color: Palette.text.muted },
  error: { ...Typography.small, color: Palette.status.error },
  modalLayer: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.lg },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: Palette.overlay },
  calendarCard: {
    width: '100%',
    maxWidth: 420,
    padding: Spacing.lg,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    backgroundColor: Palette.bg.card,
    ...Shadows.card,
  },
  calendarHeader: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginBottom: Spacing.sm },
  navigationButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: Radius.full },
  monthTitle: { ...Typography.h3, ...Typography.number, color: Palette.text.primary, flex: 1, textAlign: 'center' },
  weekdayRow: { flexDirection: 'row', marginBottom: Spacing.xs },
  weekday: { ...Typography.small, color: Palette.text.tertiary, textAlign: 'center' },
  dayGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  calendarColumn: { width: '14.2857%', minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  dayButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: Radius.full },
  todayButton: { borderWidth: 1, borderColor: Palette.accent.green },
  selectedDayButton: { backgroundColor: Palette.accent.green },
  dayButtonDisabled: { opacity: 0.34 },
  dayText: { ...Typography.caption, ...Typography.number, color: Palette.text.primary },
  todayText: { color: Palette.accent.green },
  selectedDayText: { color: Palette.text.inverse },
  dayTextDisabled: { color: Palette.text.muted },
  cancelButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', marginTop: Spacing.sm, borderRadius: Radius.lg },
  cancelText: { ...Typography.bodyBold, color: Palette.text.secondary },
  pressed: { opacity: 0.72 },
  disabled: { opacity: 0.42 },
});
