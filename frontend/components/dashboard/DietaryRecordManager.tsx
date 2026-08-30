import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Palette, Radius, Shadows, Spacing, Typography } from '@/constants/theme';
import { useResponsive } from '@/hooks/useResponsive';
import { useStore } from '@/store/useStore';
import {
  createDietaryRecord,
  deleteDietaryRecord,
  fetchAllRecords,
  updateDietaryRecord,
  type DietaryRecord,
} from '@/lib/api';
import {
  buildLocalTimestampForDate,
  calculateRecordFoodTotals,
  createManualRecordFoodDraft,
  createRecordFoodDrafts,
  filterAndSortRecords,
  formatDateInput,
  formatRecordDateTime,
  getDefaultRecordDateRange,
  getEditableRecordFoods,
  getLocalTodayDateKey,
  getRecordFoodNames,
  RECORD_NUTRIENT_FIELDS,
  validateRecordDate,
  validateRecordDateRange,
  validateRecordFoodDrafts,
  type RecordDateRange,
  type RecordDateRangeErrors,
  type RecordDraftErrors,
  type RecordFoodDraft,
  type RecordNutrientKey,
} from '@/lib/dietary-records';
import DataPill from '@/components/ui/data-pill';
import FeedbackBanner from '@/components/ui/feedback-banner';
import DatePicker from '@/components/ui/date-picker';
import FormInput from '@/components/ui/form-input';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';

type Props = {
  visible: boolean;
  onClose: () => void;
};

type ManagerFeedback = { tone: 'success' | 'error'; title: string; message?: string };
type ManagerView = 'list' | 'create' | 'edit';

export default function DietaryRecordManager({ visible, onClose }: Props) {
  const { width } = useResponsive();
  const isNarrow = width < 600;
  const isDateRangeStacked = width < 840;
  const { user, apiBaseUrl, accessToken, invalidateDietaryRecords } = useStore();
  const defaultRange = useMemo(() => getDefaultRecordDateRange(), []);
  const [range, setRange] = useState<RecordDateRange>(defaultRange);
  const [rangeErrors, setRangeErrors] = useState<RecordDateRangeErrors>({});
  const [activeDateKeys, setActiveDateKeys] = useState<{ startDate: string; endDate: string } | null>(null);
  const [records, setRecords] = useState<DietaryRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<ManagerFeedback | null>(null);
  const [viewMode, setViewMode] = useState<ManagerView>('list');
  const [editingRecord, setEditingRecord] = useState<DietaryRecord | null>(null);
  const [drafts, setDrafts] = useState<RecordFoodDraft[]>([]);
  const [draftErrors, setDraftErrors] = useState<RecordDraftErrors>({});
  const [saving, setSaving] = useState(false);
  const [createDate, setCreateDate] = useState(() => formatDateInput(getLocalTodayDateKey()));
  const [createDateError, setCreateDateError] = useState<string | undefined>();
  const [createDraft, setCreateDraft] = useState<RecordFoodDraft>(() => createManualRecordFoodDraft());
  const [createErrors, setCreateErrors] = useState<RecordDraftErrors>({});
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DietaryRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const wasVisibleRef = useRef(false);
  const savingRef = useRef(false);
  const creatingRef = useRef(false);
  const createClientRecordIdRef = useRef<string | null>(null);
  const deletingRef = useRef(false);

  const resetCreateForm = useCallback(() => {
    setCreateDate(formatDateInput(getLocalTodayDateKey()));
    setCreateDateError(undefined);
    setCreateDraft(createManualRecordFoodDraft());
    setCreateErrors({});
    createClientRecordIdRef.current = null;
  }, []);

  const runQuery = useCallback(async (queryRange: RecordDateRange) => {
    const validation = validateRecordDateRange(queryRange);
    setRangeErrors(validation.errors);
    setFeedback(null);
    if (!validation.dateKeys) return;

    const normalizedRange = {
      startDate: formatDateInput(validation.dateKeys.startDate),
      endDate: formatDateInput(validation.dateKeys.endDate),
    };
    setRange(normalizedRange);
    setActiveDateKeys(validation.dateKeys);
    setLoading(true);
    setLoadError(null);
    const requestId = ++requestIdRef.current;
    try {
      const allRecords = await fetchAllRecords(apiBaseUrl, user.userId, { accessToken });
      if (requestId !== requestIdRef.current) return;
      setRecords(filterAndSortRecords(
        allRecords,
        user.userId,
        validation.dateKeys.startDate,
        validation.dateKeys.endDate
      ));
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setRecords([]);
      setLoadError(error instanceof Error ? error.message : '無法載入飲食紀錄');
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [accessToken, apiBaseUrl, user.userId]);

  useEffect(() => {
    if (visible && !wasVisibleRef.current) {
      void runQuery(range);
    }
    if (!visible) {
      requestIdRef.current += 1;
      setViewMode('list');
      setEditingRecord(null);
      setDrafts([]);
      setDraftErrors({});
      setDeleteTarget(null);
      setFeedback(null);
      resetCreateForm();
    }
    wasVisibleRef.current = visible;
  }, [range, resetCreateForm, runQuery, visible]);

  const updateRange = (key: keyof RecordDateRange, value: string) => {
    setRange((current) => ({ ...current, [key]: value }));
    setRangeErrors((current) => ({ ...current, [key]: undefined }));
  };

  const openEditor = (record: DietaryRecord) => {
    if (!record.client_record_id) {
      setFeedback({ tone: 'error', title: '無法編輯這筆舊紀錄', message: '紀錄缺少識別碼，請重新整理後再試一次。' });
      return;
    }
    setEditingRecord(record);
    setDrafts(createRecordFoodDrafts(record));
    setDraftErrors({});
    setFeedback(null);
    setViewMode('edit');
  };

  const openCreator = () => {
    resetCreateForm();
    createClientRecordIdRef.current = createManualRecordClientId();
    setEditingRecord(null);
    setFeedback(null);
    setViewMode('create');
  };

  const returnToList = () => {
    if (saving || creating) return;
    setEditingRecord(null);
    setDrafts([]);
    setDraftErrors({});
    resetCreateForm();
    setFeedback(null);
    setViewMode('list');
  };

  const updateDraft = (index: number, key: keyof RecordFoodDraft, value: string) => {
    setDrafts((current) => current.map((draft, draftIndex) => (
      draftIndex === index ? { ...draft, [key]: value } : draft
    )));
    setDraftErrors((current) => {
      const next = { ...current };
      delete next[`foods.${index}.${key}`];
      return next;
    });
  };

  const updateCreateDraft = (key: keyof RecordFoodDraft, value: string) => {
    setCreateDraft((current) => ({ ...current, [key]: value }));
    setCreateErrors((current) => {
      const next = { ...current };
      delete next[`foods.0.${key}`];
      return next;
    });
  };

  const createRecord = async () => {
    if (creatingRef.current) return;
    const dateValidation = validateRecordDate(createDate);
    const foodValidation = validateRecordFoodDrafts([createDraft]);
    setCreateDateError(dateValidation.error);
    setCreateErrors(foodValidation.errors);
    if (!dateValidation.dateKey || !foodValidation.foods) return;

    const clientRecordId = createClientRecordIdRef.current || createManualRecordClientId();
    createClientRecordIdRef.current = clientRecordId;
    const totals = calculateRecordFoodTotals(foodValidation.foods);

    creatingRef.current = true;
    setCreating(true);
    setFeedback(null);
    try {
      await createDietaryRecord(apiBaseUrl, {
        user_id: user.userId,
        client_record_id: clientRecordId,
        timestamp: buildLocalTimestampForDate(dateValidation.dateKey),
        foods: foodValidation.foods,
        total_calories: totals.calories,
        total_protein: totals.protein,
        total_carbs: totals.carbs,
        total_sugar: totals.sugar,
        total_fat: totals.fat,
        total_saturated_fat: totals.saturated_fat,
        total_trans_fat: totals.trans_fat,
        total_sodium: totals.sodium,
        total_fiber: totals.fiber,
        source: 'manual',
      }, { accessToken });
      invalidateDietaryRecords();
      const selectedRange = {
        startDate: formatDateInput(dateValidation.dateKey),
        endDate: formatDateInput(dateValidation.dateKey),
      };
      setViewMode('list');
      resetCreateForm();
      await runQuery(selectedRange);
      setFeedback({
        tone: 'success',
        title: '飲食紀錄已新增',
        message: '已切換至紀錄日期，首頁與飲食趨勢也會同步更新。',
      });
    } catch (error) {
      setFeedback({
        tone: 'error',
        title: '新增失敗，內容已保留',
        message: error instanceof Error ? error.message : '請稍後重試',
      });
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  };

  const saveRecord = async () => {
    if (!editingRecord?.client_record_id || savingRef.current) return;
    const validation = validateRecordFoodDrafts(drafts);
    setDraftErrors(validation.errors);
    if (!validation.foods) return;

    savingRef.current = true;
    setSaving(true);
    setFeedback(null);
    try {
      const response = await updateDietaryRecord(
        apiBaseUrl,
        user.userId,
        editingRecord.client_record_id,
        validation.foods,
        { accessToken }
      );
      setRecords((current) => {
        const updated = current.map((record) => (
          record.client_record_id === response.record.client_record_id ? response.record : record
        ));
        if (!activeDateKeys) return updated;
        return filterAndSortRecords(updated, user.userId, activeDateKeys.startDate, activeDateKeys.endDate);
      });
      invalidateDietaryRecords();
      setEditingRecord(null);
      setViewMode('list');
      setFeedback({ tone: 'success', title: '飲食紀錄已更新', message: '列表與首頁營養趨勢已同步重新計算。' });
    } catch (error) {
      setFeedback({
        tone: 'error',
        title: '更新失敗，編輯內容已保留',
        message: error instanceof Error ? error.message : '請稍後重試',
      });
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const requestDelete = (record: DietaryRecord) => {
    if (!record.client_record_id) {
      setFeedback({ tone: 'error', title: '無法刪除這筆舊紀錄', message: '紀錄缺少識別碼，請重新整理後再試一次。' });
      return;
    }
    setDeleteTarget(record);
    setDeleteError(null);
  };

  const confirmDelete = async () => {
    if (!deleteTarget?.client_record_id || deletingRef.current) return;
    deletingRef.current = true;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteDietaryRecord(apiBaseUrl, user.userId, deleteTarget.client_record_id, { accessToken });
      setRecords((current) => current.filter((record) => record.client_record_id !== deleteTarget.client_record_id));
      invalidateDietaryRecords();
      setDeleteTarget(null);
      setFeedback({ tone: 'success', title: '飲食紀錄已刪除', message: '列表與首頁營養趨勢已同步重新計算。' });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : '刪除失敗，請稍後重試');
    } finally {
      deletingRef.current = false;
      setDeleting(false);
    }
  };

  const closeManager = () => {
    if (saving || creating || deleting) return;
    onClose();
  };

  return (
    <>
      <Modal visible={visible} transparent animationType="fade" onRequestClose={closeManager}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={styles.modalLayer}
        >
          <Pressable accessibilityLabel="關閉修改飲食紀錄" style={styles.backdrop} onPress={closeManager} />
          <View style={[styles.managerPanel, isNarrow && styles.managerPanelNarrow]}>
            {viewMode === 'edit' ? (
              <RecordFormHeader title="編輯飲食內容" subtitle="名稱與營養數值會寫回原紀錄。" onBack={returnToList} />
            ) : viewMode === 'create' ? (
              <RecordFormHeader title="新增飲食紀錄" subtitle="選擇日期並填寫一筆食物資料。" onBack={returnToList} />
            ) : (
              <ManagerHeader onClose={closeManager} />
            )}

            <ScrollView
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
              contentContainerStyle={styles.scrollContent}
            >
              {feedback ? (
                <FeedbackBanner
                  tone={feedback.tone}
                  title={feedback.title}
                  message={feedback.message}
                  onDismiss={() => setFeedback(null)}
                />
              ) : null}

              {viewMode === 'edit' && editingRecord ? (
                <RecordEditor
                  record={editingRecord}
                  drafts={drafts}
                  errors={draftErrors}
                  saving={saving}
                  isNarrow={isNarrow}
                  onChange={updateDraft}
                  onSave={saveRecord}
                />
              ) : viewMode === 'create' ? (
                <RecordCreator
                  date={createDate}
                  dateError={createDateError}
                  draft={createDraft}
                  errors={createErrors}
                  creating={creating}
                  isNarrow={isNarrow}
                  onDateChange={(value) => {
                    setCreateDate(value);
                    setCreateDateError(undefined);
                  }}
                  onChange={updateCreateDraft}
                  onSave={createRecord}
                />
              ) : (
                <>
                  <View style={[styles.dateRow, isDateRangeStacked && styles.stackRow]}>
                    <View style={styles.dateField}>
                      <DatePicker
                        label="開始日期"
                        value={range.startDate}
                        onChange={(value) => updateRange('startDate', value)}
                        error={rangeErrors.startDate}
                      />
                    </View>
                    <Text style={[styles.rangeSeparator, isDateRangeStacked && styles.rangeSeparatorNarrow]}>～</Text>
                    <View style={styles.dateField}>
                      <DatePicker
                        label="結束日期"
                        value={range.endDate}
                        onChange={(value) => updateRange('endDate', value)}
                        error={rangeErrors.endDate}
                      />
                    </View>
                    <View style={[styles.queryButton, isDateRangeStacked && styles.queryButtonStacked]}>
                      <PrimaryButton
                        label={loading ? '查詢中' : '查詢'}
                        onPress={() => void runQuery(range)}
                        disabled={loading}
                        icon={loading
                          ? <ActivityIndicator size="small" color={Palette.text.inverse} />
                          : <Ionicons name="search" size={18} color={Palette.text.inverse} />}
                      />
                    </View>
                  </View>

                  <View style={[styles.listToolbar, isNarrow && styles.listToolbarNarrow]}>
                    <View style={[styles.createButtonWrap, isNarrow && styles.createButtonWrapNarrow]}>
                      <PrimaryButton
                        label="新增飲食紀錄"
                        onPress={openCreator}
                        fullWidth={isNarrow}
                        icon={<Ionicons name="add" size={20} color={Palette.text.inverse} />}
                      />
                    </View>
                  </View>

                  {activeDateKeys ? (
                    <View style={styles.resultHeader}>
                      <View style={styles.resultHeaderCopy}>
                        <Text style={styles.resultTitle}>查詢結果</Text>
                        <Text style={styles.resultRange}>
                          {formatDateInput(activeDateKeys.startDate)} ～ {formatDateInput(activeDateKeys.endDate)}
                        </Text>
                      </View>
                      <DataPill tone="info">{records.length} 筆</DataPill>
                    </View>
                  ) : null}

                  {loading ? (
                    <RecordState loading icon="time-outline" title="正在讀取飲食紀錄" />
                  ) : loadError ? (
                    <RecordState
                      icon="cloud-offline-outline"
                      title="無法載入飲食紀錄"
                      message={loadError}
                      action={<PrimaryButton label="重新讀取" onPress={() => void runQuery(range)} icon={<Ionicons name="refresh" size={18} color={Palette.text.inverse} />} />}
                    />
                  ) : records.length === 0 ? (
                    <RecordState icon="receipt-outline" title="所選日期內沒有飲食紀錄" message="調整日期範圍後重新查詢。" />
                  ) : (
                    <View style={styles.recordList}>
                      {records.map((record, index) => (
                        <RecordCard
                          key={record.client_record_id || `${record.timestamp}-${index}`}
                          record={record}
                          deleting={deleting && deleteTarget?.client_record_id === record.client_record_id}
                          onEdit={() => openEditor(record)}
                          onDelete={() => requestDelete(record)}
                        />
                      ))}
                    </View>
                  )}
                </>
              )}
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      <DeleteConfirmation
        record={deleteTarget}
        deleting={deleting}
        error={deleteError}
        onCancel={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function ManagerHeader({ onClose }: { onClose: () => void }) {
  return (
    <View style={styles.modalHeader}>
      <View style={styles.modalTitleWrap}>
        <Text style={styles.modalTitle}>修改飲食紀錄</Text>
        <Text style={styles.modalSubtitle}>依日期查找已儲存的餐點，修改營養內容或刪除紀錄。</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel="關閉" onPress={onClose} style={styles.iconButton}>
        <Ionicons name="close" size={22} color={Palette.text.secondary} />
      </Pressable>
    </View>
  );
}

function RecordFormHeader({ title, subtitle, onBack }: { title: string; subtitle: string; onBack: () => void }) {
  return (
    <View style={styles.modalHeader}>
      <Pressable accessibilityRole="button" accessibilityLabel="返回紀錄列表" onPress={onBack} style={styles.iconButton}>
        <Ionicons name="arrow-back" size={22} color={Palette.text.secondary} />
      </Pressable>
      <View style={styles.modalTitleWrap}>
        <Text style={styles.modalTitle}>{title}</Text>
        <Text style={styles.modalSubtitle}>{subtitle}</Text>
      </View>
    </View>
  );
}

function RecordCard({ record, deleting, onEdit, onDelete }: {
  record: DietaryRecord;
  deleting: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const totals = getRecordTotals(record);
  return (
    <View style={styles.recordCard}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`編輯 ${getRecordFoodNames(record)}`}
        onPress={onEdit}
        style={({ pressed }) => [styles.recordMain, pressed && styles.pressed]}
      >
        <View style={styles.recordTop}>
          <View style={styles.recordCopy}>
            <Text style={styles.recordName}>{getRecordFoodNames(record)}</Text>
            <Text style={styles.recordTime}>{formatRecordDateTime(record.timestamp)}</Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color={Palette.text.tertiary} />
        </View>
        <View style={styles.nutrientSummary}>
          {[
            ['熱量', totals.calories, 'kcal'],
            ['蛋白質', totals.protein, 'g'],
            ['碳水', totals.carbs, 'g'],
            ['鈉', totals.sodium, 'mg'],
          ].map(([label, value, unit]) => (
            <View key={String(label)} style={styles.nutrientSummaryItem}>
              <Text style={styles.nutrientSummaryLabel}>{label}</Text>
              <Text style={styles.nutrientSummaryValue}>{formatNutrientNumber(Number(value))} {unit}</Text>
            </View>
          ))}
        </View>
      </Pressable>
      <View style={styles.recordActions}>
        <SecondaryButton label="編輯" onPress={onEdit} icon={<Ionicons name="create-outline" size={17} color={Palette.accent.green} />} />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`刪除 ${getRecordFoodNames(record)}`}
          accessibilityState={{ disabled: deleting }}
          disabled={deleting}
          onPress={onDelete}
          style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed, deleting && styles.disabled]}
        >
          {deleting ? <ActivityIndicator size="small" color={Palette.status.error} /> : <Ionicons name="trash-outline" size={18} color={Palette.status.error} />}
          <Text style={styles.deleteButtonText}>{deleting ? '刪除中' : '刪除'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function RecordEditor({ record, drafts, errors, saving, isNarrow, onChange, onSave }: {
  record: DietaryRecord;
  drafts: RecordFoodDraft[];
  errors: RecordDraftErrors;
  saving: boolean;
  isNarrow: boolean;
  onChange: (index: number, key: keyof RecordFoodDraft, value: string) => void;
  onSave: () => void;
}) {
  return (
    <View style={styles.editor}>
      <View style={styles.editorMeta}>
        <Ionicons name="time-outline" size={17} color={Palette.accent.green} />
        <Text style={styles.editorMetaText}>{formatRecordDateTime(record.timestamp)}</Text>
      </View>
      {drafts.map((draft, foodIndex) => (
        <RecordFoodFields
          key={foodIndex}
          title={`食物 ${foodIndex + 1}`}
          draft={draft}
          errors={errors}
          foodIndex={foodIndex}
          disabled={saving}
          isNarrow={isNarrow}
          onChange={(key, value) => onChange(foodIndex, key, value)}
        />
      ))}
      <PrimaryButton
        label={saving ? '儲存中' : '儲存修改'}
        onPress={onSave}
        disabled={saving}
        icon={saving
          ? <ActivityIndicator size="small" color={Palette.text.inverse} />
          : <Ionicons name="save-outline" size={18} color={Palette.text.inverse} />}
      />
    </View>
  );
}

function RecordCreator({ date, dateError, draft, errors, creating, isNarrow, onDateChange, onChange, onSave }: {
  date: string;
  dateError?: string;
  draft: RecordFoodDraft;
  errors: RecordDraftErrors;
  creating: boolean;
  isNarrow: boolean;
  onDateChange: (value: string) => void;
  onChange: (key: keyof RecordFoodDraft, value: string) => void;
  onSave: () => void;
}) {
  return (
    <View style={styles.editor}>
      <DatePicker
        label="紀錄日期"
        value={date}
        onChange={onDateChange}
        maximumDate={formatDateInput(getLocalTodayDateKey())}
        disabled={creating}
        error={dateError}
      />
      <RecordFoodFields
        title="食物內容"
        draft={draft}
        errors={errors}
        foodIndex={0}
        disabled={creating}
        isNarrow={isNarrow}
        onChange={onChange}
      />
      <PrimaryButton
        label={creating ? '新增中' : '新增紀錄'}
        onPress={onSave}
        disabled={creating}
        icon={creating
          ? <ActivityIndicator size="small" color={Palette.text.inverse} />
          : <Ionicons name="add-circle-outline" size={18} color={Palette.text.inverse} />}
      />
    </View>
  );
}

function RecordFoodFields({ title, draft, errors, foodIndex, disabled, isNarrow, onChange }: {
  title: string;
  draft: RecordFoodDraft;
  errors: RecordDraftErrors;
  foodIndex: number;
  disabled: boolean;
  isNarrow: boolean;
  onChange: (key: keyof RecordFoodDraft, value: string) => void;
}) {
  return (
    <View style={styles.foodEditor}>
      <View style={styles.foodEditorHeader}>
        <Text style={styles.foodEditorTitle}>{title}</Text>
        {draft.source ? <DataPill tone="info">{draft.source}</DataPill> : null}
      </View>
      <FormInput
        label="食物名稱"
        value={draft.name}
        onChangeText={(value) => onChange('name', value)}
        editable={!disabled}
        maxLength={100}
        returnKeyType="done"
        error={errors[`foods.${foodIndex}.name`]}
      />
      <View style={styles.nutrientFormGrid}>
        {RECORD_NUTRIENT_FIELDS.map((field) => (
          <View key={field.key} style={[styles.nutrientField, isNarrow && styles.nutrientFieldNarrow]}>
            <FormInput
              label={field.label}
              unit={field.unit}
              value={draft[field.key]}
              onChangeText={(value) => onChange(field.key, value)}
              editable={!disabled}
              keyboardType="decimal-pad"
              inputMode="decimal"
              maxLength={12}
              error={errors[`foods.${foodIndex}.${field.key}`]}
              style={styles.nutrientInput}
            />
          </View>
        ))}
      </View>
      <Pressable
        accessibilityRole="checkbox"
        accessibilityLabel="油炸食物"
        accessibilityState={{ checked: draft.is_fried === 'true', disabled }}
        disabled={disabled}
        onPress={() => onChange('is_fried', draft.is_fried === 'true' ? 'false' : 'true')}
        style={({ pressed }) => [
          styles.friedToggle,
          draft.is_fried === 'true' && styles.friedToggleChecked,
          pressed && styles.pressed,
          disabled && styles.disabled,
        ]}
      >
        <Ionicons
          name={draft.is_fried === 'true' ? 'checkbox' : 'square-outline'}
          size={22}
          color={draft.is_fried === 'true' ? Palette.status.warning : Palette.text.tertiary}
        />
        <Text style={styles.friedToggleText}>油炸食物</Text>
      </Pressable>
    </View>
  );
}

function RecordState({ loading, icon, title, message, action }: {
  loading?: boolean;
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  message?: string;
  action?: React.ReactNode;
}) {
  return (
    <View style={styles.stateCard}>
      {loading ? <ActivityIndicator size="large" color={Palette.accent.green} /> : <Ionicons name={icon} size={30} color={Palette.text.tertiary} />}
      <Text style={styles.stateTitle}>{title}</Text>
      {message ? <Text selectable style={styles.stateMessage}>{message}</Text> : null}
      {action}
    </View>
  );
}

function DeleteConfirmation({ record, deleting, error, onCancel, onConfirm }: {
  record: DietaryRecord | null;
  deleting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal visible={Boolean(record)} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.confirmLayer}>
        <Pressable accessibilityLabel="取消刪除" style={styles.backdrop} onPress={onCancel} />
        <View accessibilityRole="alert" style={styles.confirmCard}>
          <View style={styles.confirmIcon}>
            <Ionicons name="trash-outline" size={24} color={Palette.status.error} />
          </View>
          <Text style={styles.confirmTitle}>刪除這筆飲食紀錄？</Text>
          <Text style={styles.confirmMessage}>「{record ? getRecordFoodNames(record) : ''}」刪除後無法復原。</Text>
          {error ? <Text selectable style={styles.confirmError}>{error}</Text> : null}
          <View style={styles.confirmActions}>
            <View style={styles.confirmAction}>
              <SecondaryButton label="取消" onPress={onCancel} disabled={deleting} />
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="確認刪除飲食紀錄"
              accessibilityState={{ disabled: deleting }}
              disabled={deleting}
              onPress={onConfirm}
              style={({ pressed }) => [styles.confirmDeleteButton, pressed && styles.pressed, deleting && styles.disabled]}
            >
              {deleting ? <ActivityIndicator size="small" color={Palette.text.inverse} /> : <Ionicons name="trash" size={18} color={Palette.text.inverse} />}
              <Text style={styles.confirmDeleteText}>{deleting ? '刪除中' : '確認刪除'}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function getRecordTotals(record: DietaryRecord): Record<RecordNutrientKey, number> {
  const foods = getEditableRecordFoods(record);
  return RECORD_NUTRIENT_FIELDS.reduce((totals, field) => {
    const topLevelValue = record[`total_${field.key}` as keyof DietaryRecord];
    totals[field.key] = topLevelValue !== undefined
      ? Number(topLevelValue) || 0
      : foods.reduce((sum, food) => sum + (Number(food[field.key]) || 0), 0);
    return totals;
  }, {} as Record<RecordNutrientKey, number>);
}

function formatNutrientNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function createManualRecordClientId(): string {
  return `manual_record_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

const styles = StyleSheet.create({
  modalLayer: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.xl },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: Palette.overlay },
  managerPanel: {
    width: '100%',
    maxWidth: 820,
    maxHeight: '92%',
    minHeight: 360,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    overflow: 'hidden',
    ...Shadows.card,
  },
  managerPanelNarrow: { maxHeight: '96%', borderRadius: Radius.xl },
  modalHeader: {
    minHeight: 76,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    paddingHorizontal: Spacing.xl,
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Palette.border.subtle,
    backgroundColor: Palette.bg.wash,
  },
  modalTitleWrap: { flex: 1, minWidth: 0, gap: 2 },
  modalTitle: { ...Typography.h2, color: Palette.text.primary },
  modalSubtitle: { ...Typography.caption, color: Palette.text.secondary },
  iconButton: { width: 44, height: 44, borderRadius: Radius.full, alignItems: 'center', justifyContent: 'center' },
  scrollContent: { padding: Spacing.xl, paddingBottom: Spacing['3xl'] },
  dateRow: { flexDirection: 'row', alignItems: 'flex-end', gap: Spacing.sm, marginBottom: Spacing.xl },
  stackRow: { flexDirection: 'column', alignItems: 'stretch' },
  dateField: { flex: 1, minWidth: 0 },
  rangeSeparator: { ...Typography.bodyBold, color: Palette.text.tertiary, height: 48, textAlignVertical: 'center', paddingTop: 12 },
  rangeSeparatorNarrow: { height: 18, paddingTop: 0, alignSelf: 'center' },
  queryButton: { minWidth: 124 },
  queryButtonStacked: { width: '100%' },
  listToolbar: { flexDirection: 'row', justifyContent: 'flex-end', marginBottom: Spacing.lg },
  listToolbarNarrow: { alignItems: 'stretch' },
  createButtonWrap: { minWidth: 210 },
  createButtonWrapNarrow: { width: '100%' },
  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, marginBottom: Spacing.md },
  resultHeaderCopy: { flex: 1, minWidth: 0 },
  resultTitle: { ...Typography.h3, color: Palette.text.primary },
  resultRange: { ...Typography.caption, ...Typography.number, color: Palette.text.tertiary, marginTop: 2 },
  recordList: { gap: Spacing.md },
  recordCard: { backgroundColor: Palette.bg.card, borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.lg, overflow: 'hidden', ...Shadows.soft },
  recordMain: { padding: Spacing.lg, gap: Spacing.md },
  recordTop: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  recordCopy: { flex: 1, minWidth: 0, gap: 2 },
  recordName: { ...Typography.h3, color: Palette.text.primary, flexShrink: 1 },
  recordTime: { ...Typography.caption, ...Typography.number, color: Palette.text.tertiary },
  nutrientSummary: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutrientSummaryItem: { flexGrow: 1, flexBasis: 126, minWidth: 0, backgroundColor: Palette.bg.elevated, borderRadius: Radius.md, padding: Spacing.sm },
  nutrientSummaryLabel: { ...Typography.small, color: Palette.text.tertiary },
  nutrientSummaryValue: { ...Typography.caption, ...Typography.number, color: Palette.text.primary, marginTop: 2 },
  recordActions: { flexDirection: 'row', justifyContent: 'flex-end', flexWrap: 'wrap', gap: Spacing.sm, padding: Spacing.md, borderTopWidth: 1, borderTopColor: Palette.border.subtle, backgroundColor: Palette.bg.wash },
  deleteButton: { minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: Spacing.sm, paddingHorizontal: Spacing.lg, borderRadius: Radius.lg, borderWidth: 1, borderColor: 'rgba(226,85,85,0.28)', backgroundColor: 'rgba(226,85,85,0.06)' },
  deleteButtonText: { ...Typography.bodyBold, color: Palette.status.error },
  editor: { gap: Spacing.lg },
  editorMeta: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, backgroundColor: Palette.accent.greenDim, borderRadius: Radius.lg, paddingHorizontal: Spacing.md },
  editorMetaText: { ...Typography.caption, ...Typography.number, color: Palette.text.secondary },
  foodEditor: { gap: Spacing.md, backgroundColor: Palette.bg.wash, borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.lg, padding: Spacing.lg },
  foodEditorHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm },
  foodEditorTitle: { ...Typography.h3, color: Palette.text.primary },
  nutrientFormGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.md },
  nutrientField: { flexGrow: 1, flexBasis: 210, minWidth: 0 },
  nutrientFieldNarrow: { flexBasis: 132 },
  nutrientInput: { ...Typography.number },
  friedToggle: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, alignSelf: 'flex-start', paddingHorizontal: Spacing.md, borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.lg, backgroundColor: Palette.bg.card },
  friedToggleChecked: { borderColor: Palette.status.warning, backgroundColor: Palette.accent.orangeDim },
  friedToggleText: { ...Typography.bodyBold, color: Palette.text.primary },
  stateCard: { minHeight: 220, alignItems: 'center', justifyContent: 'center', gap: Spacing.sm, backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.xl },
  stateTitle: { ...Typography.bodyBold, color: Palette.text.primary, textAlign: 'center' },
  stateMessage: { ...Typography.caption, color: Palette.text.secondary, textAlign: 'center', maxWidth: 520 },
  confirmLayer: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.xl },
  confirmCard: { width: '100%', maxWidth: 420, alignItems: 'center', gap: Spacing.md, backgroundColor: Palette.bg.card, borderRadius: Radius.xl, borderWidth: 1, borderColor: Palette.border.subtle, padding: Spacing.xl, ...Shadows.card },
  confirmIcon: { width: 52, height: 52, borderRadius: Radius.full, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(226,85,85,0.09)' },
  confirmTitle: { ...Typography.h2, color: Palette.text.primary, textAlign: 'center' },
  confirmMessage: { ...Typography.body, color: Palette.text.secondary, textAlign: 'center' },
  confirmError: { ...Typography.caption, color: Palette.status.error, textAlign: 'center' },
  confirmActions: { width: '100%', flexDirection: 'row', gap: Spacing.sm, marginTop: Spacing.sm },
  confirmAction: { flex: 1 },
  confirmDeleteButton: { minHeight: 48, flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: Spacing.sm, borderRadius: Radius.lg, backgroundColor: Palette.status.error, paddingHorizontal: Spacing.md },
  confirmDeleteText: { ...Typography.bodyBold, color: Palette.text.inverse },
  pressed: { opacity: 0.76 },
  disabled: { opacity: 0.5 },
});
