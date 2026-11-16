import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Palette, Radius, Spacing, Typography } from '@/constants/theme';
import PrimaryButton from '@/components/ui/primary-button';
import type { ScannerServerScanReference } from '@/store/useStore';
import {
  buildNutritionFdcConfirmationRequest,
  confirmNutritionFdcCandidates,
  type NutritionFdcConfirmationRequest,
  type NutritionFdcConfirmationResponse,
  type NutritionFdcDecision,
} from '@/lib/nutrition-fdc-confirmation-api';
import type { NutritionFdcCandidateSnapshotResponse } from '@/lib/nutrition-fdc-candidate-api';
import { getNutritionFdcRecovery } from '@/lib/nutrition-fdc-recovery';
import {
  buildNutritionFdcProfilePreviewRequest,
  NutritionFdcPreviewApiError,
  requestNutritionFdcProfilePreview,
  type NutritionFdcProfilePreviewResponse,
} from '@/lib/nutrition-fdc-preview-api';

type Props = {
  snapshot: NutritionFdcCandidateSnapshotResponse;
  reference: ScannerServerScanReference;
  enabled: boolean;
  completedResult?: NutritionFdcConfirmationResponse | null;
  previewEnabled: boolean;
  onConfirm: (reference: ScannerServerScanReference, snapshot: NutritionFdcCandidateSnapshotResponse,
    result: NutritionFdcConfirmationResponse) => void;
  isCurrentSnapshot: (reference: ScannerServerScanReference, snapshotDigest: string) => boolean;
  isCurrentPreview: (reference: ScannerServerScanReference, confirmationId: string,
    issuedRevision: number, snapshotDigest: string) => boolean;
  onUnavailable: (reference: ScannerServerScanReference, message: string) => void;
  apiBaseUrl: string;
  accessToken: string | null;
};

type Choice = Pick<NutritionFdcDecision, 'decision' | 'candidate_fdc_id'>;

export default function FdcCandidateReview({
  snapshot, reference, enabled, completedResult = null, previewEnabled, onConfirm,
  isCurrentSnapshot, isCurrentPreview, apiBaseUrl, accessToken,
  onUnavailable,
}: Props) {
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [pendingRequest, setPendingRequest] = useState<NutritionFdcConfirmationRequest | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [confirmationRetryable, setConfirmationRetryable] = useState(true);
  const [previews, setPreviews] = useState<Record<string, NutritionFdcProfilePreviewResponse>>({});
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({});
  const [previewBlocked, setPreviewBlocked] = useState<Record<string, boolean>>({});
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({});
  const pendingRequestRef = useRef<NutritionFdcConfirmationRequest | null>(null);
  const submissionInFlightRef = useRef(false);
  const previewRequestsRef = useRef(new Set<string>());
  const previewGenerationRef = useRef(0);
  const snapshotBody = snapshot.snapshot.snapshot;
  const hasPendingChoices = snapshotBody.items.every((item) => Boolean(choices[item.item_id]));
  const locked = Boolean(pendingRequest) || Boolean(completedResult);

  useEffect(() => {
    setChoices({});
    setPendingRequest(null);
    pendingRequestRef.current = null;
    submissionInFlightRef.current = false;
    setSubmitting(false);
    setErrorMessage(null);
    setConfirmationRetryable(true);
    setPreviews({});
    setPreviewErrors({});
    setPreviewBlocked({});
    setPreviewLoading({});
    previewRequestsRef.current.clear();
    previewGenerationRef.current += 1;
    return () => { previewGenerationRef.current += 1; };
  }, [snapshotBody.snapshot_digest, completedResult?.confirmation_id]);

  const loadPreview = async (itemId: string, expectedFdcId: string) => {
    if (!previewEnabled || completedResult?.issued_scan_revision == null || previewRequestsRef.current.has(itemId)) return;
    const generation = previewGenerationRef.current;
    const snapshotDigest = snapshotBody.snapshot_digest;
    const confirmationId = completedResult.confirmation_id;
    const issuedRevision = completedResult.issued_scan_revision;
    let request: ReturnType<typeof buildNutritionFdcProfilePreviewRequest>;
    try {
      request = buildNutritionFdcProfilePreviewRequest({
        confirmation_id: confirmationId,
        scan_id: completedResult.scan_id,
        issued_scan_revision: issuedRevision,
        item_id: itemId,
      });
    } catch (error) {
      setPreviewErrors((current) => ({
        ...current, [itemId]: error instanceof Error ? error.message : '預覽請求格式不正確',
      }));
      return;
    }
    previewRequestsRef.current.add(itemId);
    setPreviewLoading((current) => ({ ...current, [itemId]: true }));
    setPreviewErrors((current) => ({ ...current, [itemId]: '' }));
    const isCurrent = () => generation === previewGenerationRef.current &&
      isCurrentPreview(reference, confirmationId, issuedRevision, snapshotDigest);
    try {
      const result = await requestNutritionFdcProfilePreview(apiBaseUrl, request,
        { accessToken: accessToken || undefined }, { enabled: previewEnabled, isCurrentSession: isCurrent });
      if (!isCurrent()) return;
      const snapshotItem = snapshotBody.items.find((item) => item.item_id === itemId);
      if (!snapshotItem || result.snapshot_digest !== snapshotDigest || result.fdc_id !== expectedFdcId ||
          result.item_revision !== snapshotItem.item_revision ||
          result.weight_g !== result.preview.portion.weight_g) {
        throw new NutritionFdcPreviewApiError('預覽與已確認的候選、版本或伺服器份量不一致', 200, 'binding_mismatch');
      }
      setPreviews((current) => ({ ...current, [itemId]: result }));
    } catch (error) {
      if (!isCurrent()) return;
      const recovery = getNutritionFdcRecovery(error);
      if (recovery.rescan) {
        onUnavailable(reference, recovery.message);
        return;
      }
      setPreviewBlocked((current) => ({ ...current, [itemId]: !recovery.retryable }));
      setPreviewErrors((current) => ({
        ...current,
        [itemId]: recovery.message,
      }));
    } finally {
      previewRequestsRef.current.delete(itemId);
      if (generation === previewGenerationRef.current) {
        setPreviewLoading((current) => ({ ...current, [itemId]: false }));
      }
    }
  };

  const choose = (itemId: string, choice: Choice) => {
    if (locked) return;
    setChoices((current) => ({ ...current, [itemId]: choice }));
  };

  const submit = async () => {
    const existingRequest = pendingRequestRef.current ?? pendingRequest;
    if (!enabled || submissionInFlightRef.current || completedResult || (!existingRequest && !hasPendingChoices)) return;
    let request = existingRequest;
    if (!request) {
      const decisions = snapshotBody.items.map((item) => ({ item_id: item.item_id, ...choices[item.item_id] }));
      try {
        request = buildNutritionFdcConfirmationRequest({
          snapshot,
          idempotencyKey: buildConfirmationKey(reference),
          decisions,
        });
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : '候選決定格式不正確');
        return;
      }
      pendingRequestRef.current = request;
      setPendingRequest(request);
    }
    submissionInFlightRef.current = true;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const result = await confirmNutritionFdcCandidates(apiBaseUrl, request, snapshot,
        { accessToken: accessToken || undefined }, {
          enabled,
          isCurrentSession: () => isCurrentSnapshot(reference, snapshotBody.snapshot_digest),
        });
      if (!isCurrentSnapshot(reference, snapshotBody.snapshot_digest)) return;
      onConfirm(reference, snapshot, result);
    } catch (error) {
      if (!isCurrentSnapshot(reference, snapshotBody.snapshot_digest)) return;
      const recovery = getNutritionFdcRecovery(error);
      if (recovery.rescan) {
        onUnavailable(reference, recovery.message);
        return;
      }
      setConfirmationRetryable(recovery.retryable);
      setErrorMessage(recovery.message);
    } finally {
      submissionInFlightRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.section}>
      <View style={styles.header}>
        <View style={styles.headingCopy}>
          <Text style={styles.title}>USDA 候選核對</Text>
          <Text style={styles.subtitle}>
            候選僅供名稱比對，不含營養資料。確認後仍需固定資料明細檢查；影像信心度不會改變。
          </Text>
        </View>
        <Ionicons name="checkmark-done-outline" size={22} color={Palette.accent.blue} />
      </View>

      <View style={styles.contractNotice}>
        <Ionicons name="information-circle-outline" size={17} color={Palette.accent.blue} />
        <Text style={styles.contractText}>
          目前份量校正只用於本機飲食紀錄。後續資料預覽使用伺服器掃描估重，本階段不會套用營養素或寫入紀錄。
        </Text>
      </View>

      {snapshot.status === 'empty' ? (
        <View style={styles.emptyNotice}>
          <Ionicons name="search-outline" size={17} color={Palette.text.tertiary} />
          <Text style={styles.emptyText}>這次掃描沒有找到可供核對的 USDA 候選。</Text>
        </View>
      ) : null}

      {snapshotBody.items.map((item) => {
        const choice = choices[item.item_id];
        const completedItem = completedResult?.items.find((entry) => entry.item_id === item.item_id);
        return (
          <View key={item.item_id} style={styles.itemSection}>
            <View style={styles.itemHeader}>
              <Text style={styles.foodName}>{item.recognition_identity.name_zh}</Text>
              {completedItem ? <Text style={styles.itemStatus}>{statusLabel(completedItem.status)}</Text> : null}
            </View>

            {item.candidates.length === 0 ? (
              <Text style={styles.noCandidate}>沒有可確認候選；可保留待處理或標記不相符。</Text>
            ) : (
              <View style={styles.candidateList}>
                {item.candidates.map((candidate) => {
                  const selected = choice?.decision === 'confirm' && choice.candidate_fdc_id === candidate.fdcId;
                  return (
                    <Pressable
                      key={candidate.fdcId}
                      accessibilityRole="radio"
                      accessibilityState={{ checked: selected, disabled: locked }}
                      onPress={() => choose(item.item_id, { decision: 'confirm', candidate_fdc_id: candidate.fdcId })}
                      disabled={locked}
                      style={[styles.candidateRow, selected && styles.candidateSelected, locked && styles.disabled]}
                    >
                      <Ionicons
                        name={selected ? 'radio-button-on' : 'radio-button-off'}
                        size={19}
                        color={selected ? Palette.accent.green : Palette.text.tertiary}
                      />
                      <View style={styles.candidateCopy}>
                        <Text style={styles.candidateName}>{candidate.description}</Text>
                        <Text style={styles.candidateMeta}>
                          {candidate.dataType}{candidate.brandOwner ? ` · ${candidate.brandOwner}` : ''}
                          {candidate.foodCategory ? ` · ${candidate.foodCategory}` : ''}
                        </Text>
                      </View>
                    </Pressable>
                  );
                })}
              </View>
            )}

            {!completedItem ? (
              <View style={styles.decisionRow}>
                <ChoiceButton
                  label="稍後處理"
                  icon="time-outline"
                  selected={choice?.decision === 'defer'}
                  disabled={locked}
                  onPress={() => choose(item.item_id, { decision: 'defer', candidate_fdc_id: null })}
                />
                <ChoiceButton
                  label="都不相符"
                  icon="close-circle-outline"
                  selected={choice?.decision === 'reject'}
                  disabled={locked}
                  onPress={() => choose(item.item_id, { decision: 'reject', candidate_fdc_id: null })}
                />
              </View>
            ) : null}

            {completedItem?.status === 'confirmed_pending_revision' && completedResult?.issued_scan_revision != null ? (
              <FdcProfilePreview
                itemId={item.item_id}
                fallbackName={item.recognition_identity.name_zh}
                confirmedFdcId={completedItem.confirmed_fdc_id}
                preview={previews[item.item_id] ?? null}
                error={previewErrors[item.item_id] || null}
                loading={Boolean(previewLoading[item.item_id])}
                enabled={previewEnabled}
                blocked={Boolean(previewBlocked[item.item_id])}
                onLoad={() => {
                  if (completedItem.confirmed_fdc_id) void loadPreview(item.item_id, completedItem.confirmed_fdc_id);
                }}
              />
            ) : null}
          </View>
        );
      })}

      {completedResult ? (
        <View style={styles.resultNotice}>
          <Ionicons name="checkmark-circle-outline" size={18} color={Palette.status.success} />
          <View style={styles.resultCopy}>
            <Text style={styles.resultTitle}>候選決定已記錄</Text>
            <Text style={styles.resultText}>
              {completedResult.requires_detail_replay
                ? '確認的項目已綁定新的伺服器掃描版本，仍待取得並檢查固定資料明細。營養資料尚未套用。'
                : '尚未確認資料來源；保留與拒絕的項目不會建立營養資料。'}
            </Text>
          </View>
        </View>
      ) : (
        <>
          {!enabled ? <Text style={styles.disabledNotice}>候選確認功能目前未啟用。</Text> : null}
          {errorMessage ? <Text accessibilityRole="alert" style={styles.errorText}>{errorMessage}</Text> : null}
          <PrimaryButton
            label={submitting ? '送出確認中' : pendingRequest ? '使用同一決定重試' : '送出逐項決定'}
            onPress={submit}
            disabled={!enabled || submitting || !confirmationRetryable || (!pendingRequest && !hasPendingChoices)}
            icon={submitting
              ? <ActivityIndicator size="small" color={Palette.text.inverse} />
              : <Ionicons name="send-outline" size={17} color={Palette.text.inverse} />}
          />
        </>
      )}
    </View>
  );
}

function FdcProfilePreview({
  itemId, fallbackName, confirmedFdcId, preview, error, loading, enabled, blocked, onLoad,
}: {
  itemId: string;
  fallbackName: string;
  confirmedFdcId: string | null;
  preview: NutritionFdcProfilePreviewResponse | null;
  error: string | null;
  loading: boolean;
  enabled: boolean;
  blocked: boolean;
  onLoad: () => void;
}) {
  if (!preview) {
    return (
      <View style={styles.previewSection}>
        {!enabled ? <Text style={styles.disabledNotice}>固定資料營養預覽目前未啟用。</Text> : null}
        {error ? <Text accessibilityRole="alert" style={styles.errorText}>{error}</Text> : null}
        <PrimaryButton
          label={loading ? '載入固定資料中' : '預覽固定資料營養'}
          onPress={onLoad}
          disabled={!enabled || blocked || loading || !confirmedFdcId}
          icon={loading
            ? <ActivityIndicator size="small" color={Palette.text.inverse} />
            : <Ionicons name="reader-outline" size={17} color={Palette.text.inverse} />}
        />
      </View>
    );
  }

  const profile = preview.preview.nutrition_profile;
  const per100g = isRecord(profile.per_100g) ? profile.per_100g : {};
  const per100gBounds = isRecord(profile.upper_bounds_per_100g) ? profile.upper_bounds_per_100g : {};
  const portion = preview.preview.portion;
  const portionValues = isRecord(portion.values) ? portion.values : {};
  const portionBounds = isRecord(portion.upper_bounds) ? portion.upper_bounds : {};
  const sourceIdentity = preview.preview.source_identity;
  const displayName = readText(preview.preview.recognition_identity, 'name_zh') || fallbackName;
  const sourceName = readText(sourceIdentity, 'name') || `USDA FDC ${preview.fdc_id}`;
  const bounded = new Set(Array.isArray(profile.bounded_nutrition_fields)
    ? profile.bounded_nutrition_fields.filter((value): value is string => typeof value === 'string') : []);
  const missing = Array.isArray(profile.missing_nutrition_fields)
    ? profile.missing_nutrition_fields.filter((value): value is string => typeof value === 'string' && !bounded.has(value)) : [];

  return (
    <View style={styles.previewCard}>
      <View style={styles.previewHeading}>
        <View style={styles.previewTitleCopy}>
          <Text style={styles.previewTitle}>{displayName} · 營養預覽</Text>
          <Text style={styles.previewMeta}>{sourceName} · FDC {preview.fdc_id}</Text>
        </View>
        <Ionicons name="eye-outline" size={19} color={Palette.accent.blue} />
      </View>
      <Text style={styles.previewWeight}>伺服器估重 {formatNutrient(preview.weight_g)} g</Text>
      <Text style={styles.previewGroupLabel}>每 100 g</Text>
      <NutrientGrid values={per100g} upperBounds={per100gBounds} />
      <Text style={styles.previewGroupLabel}>本次份量 · {formatNutrient(preview.weight_g)} g</Text>
      <NutrientGrid values={portionValues} upperBounds={portionBounds} />
      {missing.length > 0 ? (
        <Text style={styles.previewMissing}>來源未提供：{missing.map(nutrientLabel).join('、')}</Text>
      ) : null}
      <View style={styles.previewFootnote}>
        <Ionicons name="information-circle-outline" size={16} color={Palette.text.secondary} />
        <Text style={styles.previewFootnoteText}>僅供核對，尚未套用至掃描結果或寫入飲食紀錄；影像信心度未變更。</Text>
      </View>
      <Text style={styles.previewReference}>Preview {preview.preview_id} · {itemId}</Text>
    </View>
  );
}

function NutrientGrid({ values, upperBounds }: {
  values: Record<string, unknown>;
  upperBounds: Record<string, unknown>;
}) {
  return (
    <View style={styles.nutrientGrid}>
      {NUTRIENT_DISPLAY_ORDER.map(({ key, label, unit }) => (
        <View key={key} style={styles.nutrientCell}>
          <Text style={styles.nutrientLabel}>{label}</Text>
          <Text style={styles.nutrientValue}>
            {typeof values[key] === 'number' && Number.isFinite(values[key])
              ? `${formatNutrient(values[key])} ${unit}`
              : typeof upperBounds[key] === 'number' && Number.isFinite(upperBounds[key])
                ? `< ${formatNutrient(upperBounds[key])} ${unit}` : '未提供'}
          </Text>
        </View>
      ))}
    </View>
  );
}

const NUTRIENT_DISPLAY_ORDER = [
  { key: 'calories', label: '熱量', unit: 'kcal' },
  { key: 'protein', label: '蛋白質', unit: 'g' },
  { key: 'carbs', label: '碳水', unit: 'g' },
  { key: 'fat', label: '脂肪', unit: 'g' },
  { key: 'sodium', label: '鈉', unit: 'mg' },
  { key: 'fiber', label: '膳食纖維', unit: 'g' },
  { key: 'sugar', label: '糖', unit: 'g' },
  { key: 'saturated_fat', label: '飽和脂肪', unit: 'g' },
  { key: 'trans_fat', label: '反式脂肪', unit: 'g' },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function readText(value: unknown, key: string): string | null {
  if (!isRecord(value)) return null;
  return typeof value[key] === 'string' && value[key].trim() ? value[key] as string : null;
}

function formatNutrient(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未提供';
  return new Intl.NumberFormat('zh-TW', { maximumFractionDigits: 2 }).format(value);
}

function nutrientLabel(key: string): string {
  return NUTRIENT_DISPLAY_ORDER.find((entry) => entry.key === key)?.label ?? key;
}

function ChoiceButton({ label, icon, selected, disabled, onPress }: {
  label: string;
  icon: React.ComponentProps<typeof Ionicons>['name'];
  selected: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected, disabled }}
      onPress={onPress}
      disabled={disabled}
      style={[styles.choiceButton, selected && styles.choiceSelected, disabled && styles.disabled]}
    >
      <Ionicons name={icon} size={16} color={selected ? Palette.accent.green : Palette.text.secondary} />
      <Text style={[styles.choiceLabel, selected && styles.choiceLabelSelected]}>{label}</Text>
    </Pressable>
  );
}

function statusLabel(status: NutritionFdcConfirmationResponse['items'][number]['status']): string {
  if (status === 'confirmed_pending_revision') return '已確認候選';
  if (status === 'rejected') return '已標記不相符';
  return '保留待處理';
}

function buildConfirmationKey(reference: ScannerServerScanReference): string {
  return `fdc-confirmation:${reference.scan_id}:${reference.scan_revision}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

const styles = StyleSheet.create({
  section: {
    backgroundColor: Palette.bg.card,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    borderRadius: Radius.md,
    padding: Spacing.lg,
    gap: Spacing.md,
    marginBottom: Spacing.md,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.md },
  headingCopy: { flex: 1, gap: Spacing.xs },
  title: { ...Typography.h3, color: Palette.text.primary },
  subtitle: { ...Typography.caption, color: Palette.text.secondary, lineHeight: 20 },
  contractNotice: {
    flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm,
    backgroundColor: Palette.accent.blueDim, borderRadius: Radius.sm, padding: Spacing.md,
  },
  contractText: { ...Typography.small, color: Palette.text.secondary, flex: 1, lineHeight: 18 },
  emptyNotice: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.sm,
    borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.sm, padding: Spacing.md,
  },
  emptyText: { ...Typography.caption, color: Palette.text.secondary, flex: 1 },
  itemSection: { gap: Spacing.sm, borderTopWidth: 1, borderTopColor: Palette.border.subtle, paddingTop: Spacing.md },
  itemHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.sm },
  foodName: { ...Typography.bodyBold, color: Palette.text.primary, flex: 1 },
  itemStatus: { ...Typography.small, color: Palette.status.success },
  noCandidate: { ...Typography.small, color: Palette.text.tertiary },
  candidateList: { gap: Spacing.xs },
  candidateRow: {
    minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: Spacing.sm,
    borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.sm, padding: Spacing.sm,
  },
  candidateSelected: { borderColor: Palette.accent.green, backgroundColor: Palette.accent.greenDim },
  candidateCopy: { flex: 1, gap: 3 },
  candidateName: { ...Typography.caption, color: Palette.text.primary },
  candidateMeta: { ...Typography.small, color: Palette.text.tertiary },
  decisionRow: { flexDirection: 'row', gap: Spacing.sm, flexWrap: 'wrap' },
  choiceButton: {
    minHeight: 40, flexDirection: 'row', alignItems: 'center', gap: Spacing.xs,
    borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.sm, paddingHorizontal: Spacing.md,
  },
  choiceSelected: { borderColor: Palette.accent.green, backgroundColor: Palette.accent.greenDim },
  choiceLabel: { ...Typography.small, color: Palette.text.secondary },
  choiceLabelSelected: { color: Palette.accent.green },
  disabled: { opacity: 0.55 },
  resultNotice: {
    flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm,
    backgroundColor: Palette.accent.greenDim, borderRadius: Radius.sm, padding: Spacing.md,
  },
  resultCopy: { flex: 1, gap: 2 },
  resultTitle: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  resultText: { ...Typography.small, color: Palette.text.secondary, lineHeight: 18 },
  previewSection: { gap: Spacing.sm, borderTopWidth: 1, borderTopColor: Palette.border.subtle, paddingTop: Spacing.sm },
  previewCard: {
    gap: Spacing.sm, borderWidth: 1, borderColor: Palette.accent.blue,
    borderRadius: Radius.sm, padding: Spacing.md, backgroundColor: Palette.bg.elevated,
  },
  previewHeading: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm },
  previewTitleCopy: { flex: 1, gap: 2 },
  previewTitle: { ...Typography.caption, color: Palette.text.primary, fontWeight: '700' },
  previewMeta: { ...Typography.small, color: Palette.text.secondary },
  previewWeight: { ...Typography.caption, color: Palette.accent.blue, fontWeight: '700' },
  previewGroupLabel: { ...Typography.small, color: Palette.text.secondary, fontWeight: '700', marginTop: Spacing.xs },
  nutrientGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.xs },
  nutrientCell: {
    flexBasis: '31%', flexGrow: 1, minWidth: 88, minHeight: 46,
    borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.sm,
    paddingHorizontal: Spacing.sm, paddingVertical: Spacing.xs, justifyContent: 'center',
  },
  nutrientLabel: { ...Typography.small, color: Palette.text.tertiary },
  nutrientValue: { ...Typography.caption, color: Palette.text.primary, fontWeight: '600', fontVariant: ['tabular-nums'] },
  previewMissing: { ...Typography.small, color: Palette.status.warning },
  previewFootnote: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xs },
  previewFootnoteText: { ...Typography.small, color: Palette.text.secondary, flex: 1, lineHeight: 18 },
  previewReference: { ...Typography.small, color: Palette.text.tertiary },
  errorText: { ...Typography.caption, color: Palette.status.error },
  disabledNotice: { ...Typography.small, color: Palette.text.tertiary },
});
