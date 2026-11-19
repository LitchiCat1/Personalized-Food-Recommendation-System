import React, { useState, useRef, useCallback } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Keyboard, TextInput } from 'react-native';
import { useFocusEffect } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import * as ImagePicker from 'expo-image-picker';
import { Palette, Typography, Spacing, Radius, Shadows } from '@/constants/theme';
import type { DetectedFood } from '@/constants/mock-data';
import { allergenLabels, conditionLabels } from '@/lib/medical-labels';
import { useStore } from '@/store/useStore';
import { useResponsive } from '@/hooks/useResponsive';
import AppContainer from '@/components/AppContainer';
import ScreenHeader from '@/components/ui/screen-header';
import SectionBlock from '@/components/ui/section-block';
import DataPill from '@/components/ui/data-pill';
import PrimaryButton from '@/components/ui/primary-button';
import SecondaryButton from '@/components/ui/secondary-button';
import SegmentedControl from '@/components/ui/segmented-control';
import FeedbackBanner from '@/components/ui/feedback-banner';
import ScannerManualTools, { ScannerPendingFoods } from '@/components/scanner/ScannerManualTools';
import ScannerResults from '@/components/scanner/ScannerResults';
import FdcCandidateReview from '@/components/scanner/FdcCandidateReview';
import MenuCheckResults from '@/components/scanner/MenuCheckResults';
import { checkMenuPhoto, type MenuPhotoCheckResponse } from '@/lib/api';
import { resolveImageBase64 } from '@/lib/image';
import {
  buildOCRDetectedFood,
  formatScannerResultTitle,
  formatScannerSourceBadge,
  formatReviewedPendingFoods,
  FOOD_NAME_REQUIRED_MESSAGE,
  hasReviewableNutritionMiss,
  getUserConfirmableIdentityItems,
  hasUserConfirmableIdentity,
  manualSearchFood,
  normalizeFoodName,
  runNutritionLabelOCR,
  runPrediction,
  mergeNutritionEnrichmentResult,
  saveCustomFood,
  saveRecord,
  type OCRDraft,
  type RejectedDetection,
} from '@/lib/scanner';
import {
  buildNutritionEnrichmentRequest,
  requestNutritionEnrichment,
  NutritionEnrichmentApiError,
  type NutritionEnrichmentResponse,
  type NutritionScanContext,
} from '@/lib/nutrition-enrichment-api';
import {
  buildNutritionIdentityConfirmationRequest,
  confirmNutritionIdentity,
  NutritionIdentityConfirmationApiError,
  type NutritionIdentityConfirmationRequest,
} from '@/lib/nutrition-identity-confirmation-api';
import { createNutritionFdcCandidateSnapshot, selectReviewedNutritionFdcSource } from '@/lib/nutrition-fdc-candidate-api';
import { getNutritionFdcRecovery } from '@/lib/nutrition-fdc-recovery';
import { runScannerNutritionFallback } from '@/lib/scanner-nutrition-fallback';
import type { NutritionFdcConfirmationResponse } from '@/lib/nutrition-fdc-confirmation-api';
import type { NutritionFdcCandidateSnapshotResponse } from '@/lib/nutrition-fdc-candidate-api';
import type { ScannerServerScanReference } from '@/store/useStore';
import { getAutoMealType } from '@/lib/meal';
import { formatLocalTimestamp } from '@/lib/dietary-records';
import { createRecordSubmissionSession, RecordSubmissionError } from '@/lib/record-submission';
import {
  canRetryPendingRecordSync,
  assertPendingRecordSyncTarget,
  enqueuePendingRecordSync,
  getPendingRecordReplayMetadata,
  loadPendingRecordSyncQueue,
  markPendingRecordSyncFailed,
  MAX_RECORD_SYNC_ATTEMPTS,
  RecordSyncQueueError,
  removePendingRecordSync,
  removePendingRecordSyncByClientRecordId,
  type PendingRecordSync,
  type RecordSource,
} from '@/lib/recordSyncQueue';

type ScanMode = 'camera' | 'gallery' | 'label' | 'menu' | 'manual';

type RecordFeedback = {
  tone: 'success' | 'error';
  title: string;
  message: string;
};

type ActiveRecordSubmission = {
  key: string;
  source: RecordSource;
};

type FdcConfirmationDisplay = {
  reference: ScannerServerScanReference;
  snapshot: NutritionFdcCandidateSnapshotResponse;
  result: NutritionFdcConfirmationResponse;
};

function createIdentityConfirmationKey(reference: ScannerServerScanReference, itemId: string, itemRevision: number) {
  return `identity:${reference.scan_id}:${reference.scan_revision}:${itemId}:${itemRevision}:${Date.now()}:${Math.random().toString(36).slice(2, 10)}`;
}

const recordSubmissions = createRecordSubmissionSession({ mealType: getAutoMealType, timestamp: formatLocalTimestamp });

const SCAN_MODE_OPTIONS = [
  { value: 'camera', label: '拍照' },
  { value: 'gallery', label: '相簿' },
  { value: 'label', label: '營養標示' },
  { value: 'menu', label: '菜單' },
  { value: 'manual', label: '手動搜尋' },
];

function OCRDraftCard({
  draft,
  foodNameError,
  onFoodNameChange,
  onFoodNameBlur,
  onSaveCustomFood,
  onQuickAdd,
  submitting,
  actionsDisabled,
}: {
  draft: OCRDraft;
  foodNameError: string | null;
  onFoodNameChange: (value: string) => void;
  onFoodNameBlur: () => void;
  onSaveCustomFood: () => void;
  onQuickAdd: () => void;
  submitting: boolean;
  actionsDisabled: boolean;
}) {
  return (
    <SectionBlock title="營養標示辨識結果" subtitle="可直接加入今日紀錄，或儲存成自訂食品供下次搜尋。">
      {draft.brand ? (
        <View style={styles.ocrBrandRow}>
          <DataPill tone="info">{draft.brand}</DataPill>
        </View>
      ) : null}
      <View style={styles.ocrNameField}>
        <Text style={styles.ocrNameLabel}>食物名稱</Text>
        <TextInput
          value={draft.product_name || ''}
          onChangeText={onFoodNameChange}
          onBlur={onFoodNameBlur}
          onSubmitEditing={Keyboard.dismiss}
          placeholder="輸入食物名稱"
          placeholderTextColor={Palette.text.muted}
          selectionColor={Palette.accent.green}
          autoCorrect={false}
          autoCapitalize="none"
          autoComplete="off"
          returnKeyType="done"
          maxLength={80}
          editable={!actionsDisabled}
          accessibilityLabel="食物名稱"
          accessibilityHint={foodNameError || undefined}
          style={[
            styles.ocrNameInput,
            foodNameError && styles.ocrNameInputError,
            actionsDisabled && styles.controlDisabled,
          ]}
        />
        {foodNameError ? (
          <View style={styles.ocrNameErrorRow}>
            <Ionicons name="alert-circle-outline" size={15} color={Palette.status.error} />
            <Text style={styles.ocrNameErrorText} selectable>{foodNameError}</Text>
          </View>
        ) : null}
      </View>
      {draft.serving_size_g ? <Text style={styles.ocrMetaText}>每份 {draft.serving_size_g} g</Text> : null}
      <View style={styles.nutritionGrid}>
        {[
          { label: '熱量', value: draft.nutrition_per_serving?.calories ?? '--', unit: 'kcal', color: Palette.accent.green },
          { label: '蛋白質', value: draft.nutrition_per_serving?.protein ?? '--', unit: 'g', color: Palette.accent.blue },
          { label: '總碳水化合物', value: draft.nutrition_per_serving?.carbs ?? '--', unit: 'g', color: Palette.accent.orange },
          { label: '精緻糖', value: draft.nutrition_per_serving?.sugar ?? '--', unit: 'g', color: Palette.accent.orange },
          { label: '總脂肪', value: draft.nutrition_per_serving?.fat ?? '--', unit: 'g', color: Palette.accent.purple },
          { label: '飽和脂肪', value: draft.nutrition_per_serving?.saturated_fat ?? '--', unit: 'g', color: Palette.accent.purple },
          { label: '反式脂肪', value: draft.nutrition_per_serving?.trans_fat ?? '--', unit: 'g', color: Palette.status.error },
          { label: '膳食纖維', value: draft.nutrition_per_serving?.fiber ?? '--', unit: 'g', color: Palette.accent.cyan },
          { label: '鈉 (Sodium)', value: draft.nutrition_per_serving?.sodium ?? '--', unit: 'mg', color: Palette.accent.pink },
        ].map((item) => (
          <View key={item.label} style={styles.nutritionItem}>
            <Text style={styles.nutritionLabel}>{item.label}</Text>
            <Text style={[styles.nutritionValue, { color: item.color }]}>
              {item.value}
              <Text style={styles.nutritionUnit}> {item.unit}</Text>
            </Text>
          </View>
        ))}
      </View>
      <View style={styles.ocrActions}>
        <SecondaryButton label="儲存成自訂食品" onPress={onSaveCustomFood} disabled={actionsDisabled} icon={<Ionicons name="bookmark-outline" size={15} color={Palette.accent.green} />} />
        <PrimaryButton
          label={submitting ? '儲存中' : '直接加入今日紀錄'}
          onPress={onQuickAdd}
          disabled={actionsDisabled}
          icon={submitting
            ? <ActivityIndicator size="small" color={Palette.text.inverse} />
            : <Ionicons name="add-circle-outline" size={18} color={Palette.text.inverse} />}
        />
      </View>
    </SectionBlock>
  );
}

function ManualResultsList({
  foods,
  onAddFood,
  submittingFoodId,
  actionsDisabled,
}: {
  foods: DetectedFood[];
  onAddFood: (food: DetectedFood) => void;
  submittingFoodId: string | null;
  actionsDisabled: boolean;
}) {
  if (foods.length === 0) return null;

  return (
    <SectionBlock title="手動搜尋結果" subtitle="以每 100g 營養資料顯示，加入後仍可在紀錄中校正。">
      <View style={styles.manualResultsWrap}>
        {foods.map((food) => (
          <View key={food.id} style={styles.manualFoodCard}>
            <View style={styles.manualFoodTop}>
              <View style={styles.manualFoodCopy}>
                <Text style={styles.manualFoodName}>{food.foodName}</Text>
                <Text style={styles.manualFoodHint}>每 100g · TFDA/自訂食品資料</Text>
              </View>
              <SecondaryButton
                label={submittingFoodId === food.id ? '儲存中' : '加入'}
                onPress={() => onAddFood(food)}
                disabled={actionsDisabled}
                icon={submittingFoodId === food.id
                  ? <ActivityIndicator size="small" color={Palette.accent.green} />
                  : undefined}
              />
            </View>
            <View style={styles.macroRow}>
              <Text style={styles.macro}>熱量 {food.nutrition.calories} kcal</Text>
              <Text style={styles.macro}>蛋白質 {food.nutrition.protein}g</Text>
              <Text style={styles.macro}>鈉 {food.nutrition.sodium}mg</Text>
            </View>
          </View>
        ))}
      </View>
    </SectionBlock>
  );
}

export default function ScannerScreen() {
  const { rs, wp, isDesktop } = useResponsive();
  const {
    scanResult,
    setScanResult,
    advanceFdcCandidateScanRevision,
    updateScanFoodWeight,
    clearScan,
    setScanning,
    apiBaseUrl,
    accessToken,
    user,
    dailyNutrition,
    invalidateDietaryRecords,
  } = useStore();
  const [manualQuery, setManualQuery] = useState('');
  const [manualResults, setManualResults] = useState<DetectedFood[]>([]);
  const [manualSearching, setManualSearching] = useState(false);
  const [rejectedDetections, setRejectedDetections] = useState<RejectedDetection[]>([]);
  const [identityScanContext, setIdentityScanContext] = useState<NutritionScanContext | null>(null);
  const [identityNameDrafts, setIdentityNameDrafts] = useState<Record<string, string>>({});
  const [identityRequestErrors, setIdentityRequestErrors] = useState<Record<string, string>>({});
  const [pendingIdentityRequests, setPendingIdentityRequests] = useState<
    Record<string, NutritionIdentityConfirmationRequest>
  >({});
  const [identitySubmittingItemId, setIdentitySubmittingItemId] = useState<string | null>(null);
  const pendingIdentityRequestsRef = useRef<Record<string, NutritionIdentityConfirmationRequest>>({});
  // 每道菜單獨都在額度內、加起來卻超過整餐上限——逐道的 warnings 看不出這件事
  const [mealWarnings, setMealWarnings] = useState<string[]>([]);
  const [ocrQuerying, setOcrQuerying] = useState(false);
  const [ocrDraft, setOcrDraft] = useState<OCRDraft | null>(null);
  const [ocrNameError, setOcrNameError] = useState<string | null>(null);
  const [menuChecking, setMenuChecking] = useState(false);
  const [menuCheck, setMenuCheck] = useState<MenuPhotoCheckResponse | null>(null);
  const [scanMode, setScanMode] = useState<ScanMode>('camera');
  const [syncingRecord, setSyncingRecord] = useState(false);
  const [activeRecordSubmission, setActiveRecordSubmission] = useState<ActiveRecordSubmission | null>(null);
  const [recordFeedback, setRecordFeedback] = useState<RecordFeedback | null>(null);
  const [fdcConfirmationDisplay, setFdcConfirmationDisplay] = useState<FdcConfirmationDisplay | null>(null);
  const [candidateFailure, setCandidateFailure] = useState<{
    reference: ScannerServerScanReference; recovery: ReturnType<typeof getNutritionFdcRecovery>;
  } | null>(null);
  const [candidateLoading, setCandidateLoading] = useState<ScannerServerScanReference | null>(null);
  const candidateRequestRef = useRef<ScannerServerScanReference | null>(null);
  const [pendingRecordQueue, setPendingRecordQueue] = useState<PendingRecordSync[]>([]);
  const recordSubmitInFlightRef = useRef(false);
  const recordSyncInFlightRef = useRef(false);
  const scanAttemptRef = useRef(0);
  const ocrSubmissionKeyRef = useRef(buildSubmissionKey('nutrition-label'));

  const results = scanResult.detections;
  const reviewedSelectionEnabled = process.env.EXPO_PUBLIC_FDC_REVIEWED_SELECTION_ENABLED?.trim().toLowerCase() === 'true';
  const candidateSearchEnabled = reviewedSelectionEnabled ||
    process.env.EXPO_PUBLIC_FDC_CANDIDATE_SEARCH_ENABLED?.trim().toLowerCase() === 'true';
  const identityConfirmationEnabled =
    process.env.EXPO_PUBLIC_NUTRITION_IDENTITY_CONFIRMATION_ENABLED?.trim().toLowerCase() === 'true';
  const enrichmentEnabled = process.env.EXPO_PUBLIC_NUTRITION_ENRICHMENT_ENABLED?.trim().toLowerCase() === 'true';
  const sourcePolicyId = process.env.EXPO_PUBLIC_NUTRITION_SOURCE_POLICY_ID?.trim();
  const revisionText = process.env.EXPO_PUBLIC_NUTRITION_SOURCE_POLICY_REVISION?.trim();
  const sourcePolicyRevision = revisionText ? Number(revisionText) : NaN;
  const enrichmentConfigured = enrichmentEnabled && Boolean(sourcePolicyId) &&
    Number.isSafeInteger(sourcePolicyRevision) && sourcePolicyRevision >= 0;
  const scanItemCount = results.length + rejectedDetections.length;
  const sourceBadge = formatScannerSourceBadge(results.map((food) => food.source), rejectedDetections.length);
  const resultTitle = formatScannerResultTitle(results.length, rejectedDetections.length);
  const serverScanReference = scanResult.serverScanReference;
  const activeIdentityContext = identityScanContext && serverScanReference &&
    identityScanContext.scan_id === serverScanReference.scan_id &&
    identityScanContext.scan_revision === serverScanReference.scan_revision
    ? identityScanContext : null;
  const confirmableIdentityItems = getUserConfirmableIdentityItems(rejectedDetections, activeIdentityContext);
  const fdcCandidateSnapshot = scanResult.fdcCandidateSnapshot ?? (
    fdcConfirmationDisplay && serverScanReference &&
    fdcConfirmationDisplay.reference.ownerUserId === user.userId &&
    fdcConfirmationDisplay.reference.apiBaseUrl === apiBaseUrl &&
    fdcConfirmationDisplay.reference.scan_id === serverScanReference.scan_id &&
    (fdcConfirmationDisplay.reference.scan_revision === serverScanReference.scan_revision ||
      fdcConfirmationDisplay.result.issued_scan_revision === serverScanReference.scan_revision)
      ? fdcConfirmationDisplay.snapshot : null
  );
  const completedFdcConfirmation = fdcCandidateSnapshot && fdcConfirmationDisplay &&
    fdcCandidateSnapshot.snapshot.snapshot_digest === fdcConfirmationDisplay.snapshot.snapshot.snapshot_digest
    ? fdcConfirmationDisplay.result : null;
  const totalCal = results.reduce((sum, f) => sum + f.nutrition.calories, 0);
  const totalSodium = results.reduce((sum, f) => sum + f.nutrition.sodium, 0);
  const userPendingRecords = pendingRecordQueue.filter((item) => item.userId === user.userId);
  const firstPendingRecord = userPendingRecords[0];
  const recordActionsDisabled = Boolean(activeRecordSubmission) || syncingRecord;
  const automaticNutritionPending = Boolean(candidateLoading && candidateLoading === serverScanReference &&
    !reviewedSelectionEnabled && enrichmentConfigured && activeIdentityContext?.authority_token);
  const cameraRecordSubmitting = activeRecordSubmission?.source === 'camera';
  const ocrRecordSubmitting = activeRecordSubmission?.source === 'nutrition-label';
  const submittingManualFoodId = activeRecordSubmission?.source === 'manual'
    ? activeRecordSubmission.key.slice('manual:'.length)
    : null;

  const clearScanAndInvalidate = () => {
    scanAttemptRef.current += 1;
    setFdcConfirmationDisplay(null);
    setCandidateFailure(null);
    setIdentityScanContext(null);
    setIdentityNameDrafts({});
    setIdentityRequestErrors({});
    pendingIdentityRequestsRef.current = {};
    setPendingIdentityRequests({});
    setIdentitySubmittingItemId(null);
    clearScan();
  };

  const updatePendingIdentityRequest = (itemId: string, request: NutritionIdentityConfirmationRequest | null) => {
    const next = { ...pendingIdentityRequestsRef.current };
    if (request) next[itemId] = request;
    else delete next[itemId];
    pendingIdentityRequestsRef.current = next;
    setPendingIdentityRequests(next);
  };

  const isCurrentFdcReference = (reference: ScannerServerScanReference) => {
    const current = useStore.getState();
    return current.user.userId === reference.ownerUserId && current.accessToken === accessToken &&
      current.apiBaseUrl === reference.apiBaseUrl && current.scanResult.serverScanReference === reference;
  };

  const handleFdcReferenceUnavailable = (reference: ScannerServerScanReference, message: string) => {
    if (!isCurrentFdcReference(reference)) return;
    useStore.getState().invalidateFdcScanReference(reference);
    setFdcConfirmationDisplay(null);
    setCandidateFailure(null);
    setRecordFeedback({ tone: 'error', title: '掃描參考已失效', message });
  };

  const loadFdcCandidates = async (
    reference: ScannerServerScanReference, context: NutritionScanContext | null = null,
  ) => {
    if (!accessToken || !isCurrentFdcReference(reference) || candidateRequestRef.current === reference) return;
    candidateRequestRef.current = reference;
    setCandidateLoading(reference);
    setCandidateFailure(null);
    try {
      const isCurrent = () => isCurrentFdcReference(reference);
      const load = reviewedSelectionEnabled ? selectReviewedNutritionFdcSource : createNutritionFdcCandidateSnapshot;
      const canEnrich = !reviewedSelectionEnabled && enrichmentConfigured && context?.authority_token &&
        context.scan_id === reference.scan_id && context.scan_revision === reference.scan_revision;
      await runScannerNutritionFallback({
        mode: reviewedSelectionEnabled ? 'reviewed' : 'search',
        isCurrent,
        loadFdc: () => load(reference.apiBaseUrl, {
          scan_id: reference.scan_id, scan_revision: reference.scan_revision,
        }, { accessToken }, { enabled: true, isCurrentSession: isCurrent }),
        onSnapshot: (snapshot) => useStore.getState().setFdcCandidateSnapshot(reference, snapshot),
        requestEnrichment: canEnrich ? () => applyEnrichment(context, isCurrent) : undefined,
      });
    } catch (error) {
      if (!isCurrentFdcReference(reference)) return;
      const recovery = getNutritionFdcRecovery(error);
      if (recovery.rescan) handleFdcReferenceUnavailable(reference, recovery.message);
      else setCandidateFailure({ reference, recovery });
    } finally {
      if (candidateRequestRef.current === reference) {
        candidateRequestRef.current = null;
        setCandidateLoading(null);
      }
    }
  };

  const isCurrentCandidateSnapshot = (reference: ScannerServerScanReference, snapshotDigest: string) => {
    const current = useStore.getState();
    const currentReference = current.scanResult.serverScanReference;
    const currentSnapshot = current.scanResult.fdcCandidateSnapshot;
    return current.user.userId === reference.ownerUserId && current.accessToken === accessToken &&
      current.apiBaseUrl === reference.apiBaseUrl && currentReference?.scan_id === reference.scan_id &&
      currentReference.scan_revision === reference.scan_revision && currentSnapshot?.snapshot.snapshot.snapshot_digest === snapshotDigest;
  };

  const isCurrentFdcPreview = (reference: ScannerServerScanReference, confirmationId: string,
    issuedRevision: number, snapshotDigest: string) => {
    const current = useStore.getState();
    const currentReference = current.scanResult.serverScanReference;
    const display = fdcConfirmationDisplay;
    return current.user.userId === reference.ownerUserId && current.accessToken === accessToken &&
      current.apiBaseUrl === reference.apiBaseUrl && currentReference?.ownerUserId === reference.ownerUserId &&
      currentReference.apiBaseUrl === reference.apiBaseUrl && currentReference.scan_id === reference.scan_id &&
      currentReference.scan_revision === issuedRevision && reference.scan_revision === issuedRevision &&
      display?.reference.ownerUserId === reference.ownerUserId && display.reference.apiBaseUrl === reference.apiBaseUrl &&
      display.reference.scan_id === reference.scan_id && display.result.confirmation_id === confirmationId &&
      display.result.issued_scan_revision === issuedRevision &&
      display.snapshot.snapshot.snapshot_digest === snapshotDigest;
  };

  const isCurrentIdentityReference = (reference: ScannerServerScanReference) => {
    const current = useStore.getState();
    const currentReference = current.scanResult.serverScanReference;
    return current.user.userId === reference.ownerUserId && current.accessToken === accessToken &&
      current.apiBaseUrl === reference.apiBaseUrl && currentReference?.scan_id === reference.scan_id &&
      currentReference.scan_revision === reference.scan_revision;
  };

  const handleIdentityDraftChange = (itemId: string, value: string) => {
    if (pendingIdentityRequestsRef.current[itemId]) return;
    setIdentityNameDrafts((current) => ({ ...current, [itemId]: value }));
    setIdentityRequestErrors((current) => {
      const next = { ...current };
      delete next[itemId];
      return next;
    });
  };

  const handleConfirmIdentity = async (itemId: string) => {
    const reference = useStore.getState().scanResult.serverScanReference;
    const context = identityScanContext;
    const item = context?.items.find((candidate) => candidate.item_id === itemId);
    if (!identityConfirmationEnabled || !accessToken || !reference || !context || !item ||
        !isCurrentIdentityReference(reference)) return;

    const previous = pendingIdentityRequestsRef.current[itemId];
    if (!previous && Object.keys(pendingIdentityRequestsRef.current).length > 0) return;
    let request = previous;
    if (!request) {
      try {
        request = buildNutritionIdentityConfirmationRequest({
          context,
          itemId,
          name: normalizeFoodName(identityNameDrafts[itemId] ?? item.name_zh),
          idempotencyKey: createIdentityConfirmationKey(reference, itemId, item.item_revision),
        });
      } catch (error) {
        setIdentityRequestErrors((current) => ({ ...current, [itemId]:
          error instanceof Error ? error.message : '食材名稱確認內容不正確' }));
        return;
      }
      updatePendingIdentityRequest(itemId, request);
    }

    setIdentitySubmittingItemId(itemId);
    setIdentityRequestErrors((current) => {
      const next = { ...current };
      delete next[itemId];
      return next;
    });
    try {
      const response = await confirmNutritionIdentity(
        reference.apiBaseUrl, request, { accessToken },
        { enabled: true, isCurrentSession: () => isCurrentIdentityReference(reference) },
      );
      if (!isCurrentIdentityReference(reference)) return;
      if (response.scan_id !== reference.scan_id || response.source_scan_revision !== reference.scan_revision ||
          response.item_id !== itemId || response.source_item_revision !== item.item_revision ||
          response.name_zh !== request.name_zh) {
        throw new NutritionIdentityConfirmationApiError(
          '名稱確認回應與目前掃描版本不一致，請重新掃描。', 200, 'binding_mismatch');
      }

      advanceFdcCandidateScanRevision(reference, response.issued_scan_revision);
      const nextReference = useStore.getState().scanResult.serverScanReference;
      if (!nextReference || nextReference.scan_id !== reference.scan_id ||
          nextReference.scan_revision !== response.issued_scan_revision) {
        throw new NutritionIdentityConfirmationApiError('掃描版本已變更，請重新載入結果。', 409, 'stale_revision');
      }
      const localItem = response.local_lookup.item;
      const localResponse: NutritionEnrichmentResponse | null = localItem ? {
        status: 'complete', request_id: null, replayed: response.replayed, error: null,
        result: { schema_version: 'NutritionEnrichmentRouteV1', items: [localItem], nutrition_coverage: {} },
      } : null;
      const latestDetections = useStore.getState().scanResult.detections;
      const nextDetections = localResponse
        ? mergeNutritionEnrichmentResult(latestDetections, localResponse)
        : latestDetections;
      const localAdded = Boolean(localItem && nextDetections.some((food) => food.id === itemId));
      if (localAdded) useStore.getState().setScanResult(nextDetections, nextReference);
      setRejectedDetections((current) => current.flatMap((entry) => {
        if (entry.item_id !== itemId) return [entry];
        if (localAdded) return [];
        const reason = response.local_lookup.status === 'matched'
          ? '本機找到參考資料，但必要營養欄位或有效重量不足；尚未計入營養合計'
          : '名稱已確認，TFDA／USDA 本機資料未找到相容營養，尚未計入合計';
        return [{ ...entry, label: response.name_zh, reason, search_hints: [] }];
      }));
      setIdentityScanContext((current) => current && current.scan_id === reference.scan_id
        ? {
          ...current,
          scan_revision: response.issued_scan_revision,
          authority_token: undefined,
          items: current.items.map((scanItem) => scanItem.item_id === itemId ? {
            ...scanItem,
            item_revision: response.issued_item_revision,
            name_zh: response.name_zh,
            identity_confirmation_required: false,
            identity_confirmation_source: 'user',
            identity_confirmation_id: response.identity_confirmation_id,
          } : scanItem),
        }
        : current);
      updatePendingIdentityRequest(itemId, null);
      setFdcConfirmationDisplay(null);
      setCandidateFailure(null);
      setRecordFeedback({
        tone: 'success',
        title: localAdded ? '已依確認名稱配對本機營養' : '食材名稱已確認',
        message: localAdded
          ? '營養資料來自本機資料庫；份量仍沿用原估計，請核對後再加入紀錄。'
          : '已完成本機營養比對，請查看此食材的配對結果。',
      });
      const otherPendingIds = rejectedDetections.some((entry) => entry.item_id && entry.item_id !== itemId);
      if (candidateSearchEnabled && accessToken && (!localAdded || otherPendingIds)) {
        void loadFdcCandidates(nextReference);
      }
    } catch (error) {
      if (!isCurrentIdentityReference(reference)) return;
      const invalidName = error instanceof NutritionIdentityConfirmationApiError &&
        error.status === 422 && error.code === 'invalid_identity';
      if (invalidName) updatePendingIdentityRequest(itemId, null);
      const message = invalidName ? '請輸入具體的食材名稱，例如青江菜。'
        : error instanceof NutritionIdentityConfirmationApiError
        ? error.message : error instanceof Error ? error.message : '食材名稱確認失敗';
      setIdentityRequestErrors((current) => ({ ...current, [itemId]: message }));
    } finally {
      setIdentitySubmittingItemId((current) => current === itemId ? null : current);
    }
  };

  const handleFdcCandidateConfirmation = (
    reference: ScannerServerScanReference,
    snapshot: NutritionFdcCandidateSnapshotResponse,
    result: NutritionFdcConfirmationResponse,
  ) => {
    setFdcConfirmationDisplay({ reference, snapshot, result });
    if (result.issued_scan_revision !== null) {
      advanceFdcCandidateScanRevision(reference, result.issued_scan_revision);
    }
  };

  const isCurrentScanSession = (attemptId: number, authRevision: number) => {
    const current = useStore.getState();
    return scanAttemptRef.current === attemptId && current.user.userId === user.userId &&
      current.accessToken === accessToken && current.apiBaseUrl === apiBaseUrl &&
      current.dietaryRecordsRevision === authRevision;
  };

  const applyEnrichment = async (
    context: NutritionScanContext,
    isCurrentSession: () => boolean,
  ) => {
    if (!isCurrentSession() || !context.authority_token || !sourcePolicyId) return;
    try {
      const request = buildNutritionEnrichmentRequest({
        userId: user.userId,
        context,
        sourcePolicyId,
        sourcePolicyRevision,
      });
      const response = await requestNutritionEnrichment(
        apiBaseUrl, request, { accessToken }, { enabled: true, isCurrentSession },
      );
      if (!isCurrentSession()) return;
      const { scanResult: current } = useStore.getState();
      const contextIds = new Set(context.items.map((item) => item.item_id));
      const existingIds = new Set(current.detections.map((food) => food.id));
      const additions = mergeNutritionEnrichmentResult([], response).filter((food) => {
        if (!contextIds.has(food.id) || existingIds.has(food.id)) return false;
        existingIds.add(food.id);
        return true;
      });
      if (additions.length === 0) return;
      useStore.setState({ scanResult: { ...current, detections: [...current.detections, ...additions] } });
      const addedIds = new Set(additions.map((food) => food.id));
      setRejectedDetections((pending) => pending.filter((item) => !addedIds.has(item.item_id || '')));
    } catch (error) {
      // Enrichment is additive. A provider or policy failure must leave the
      // original database-backed scan visible and must not block recording it.
      if (isCurrentSession() && error instanceof NutritionEnrichmentApiError && error.code === 'confirmation_required') {
        setRecordFeedback({
          tone: 'error', title: '需要先確認食物名稱',
          message: '影像辨識信心不足，網路營養資料未套用；請確認名稱或改用營養標示。',
        });
      }
    }
  };

  const handleCamera = async () => {
    setRecordFeedback(null);
    try {
      const cameraPermission = await ImagePicker.requestCameraPermissionsAsync();
      if (!cameraPermission.granted) {
        setRecordFeedback({
          tone: 'error',
          title: '需要相機權限',
          message: '請允許 NutriLens 使用相機，或改從相簿選擇餐點照片。',
        });
        return;
      }

      const picked = await ImagePicker.launchCameraAsync({ base64: true, quality: 0.7 });
      if (picked.canceled) return;
      const imageBase64 = await resolveImageBase64(picked.assets?.[0]);
      if (!imageBase64) {
        setRecordFeedback({ tone: 'error', title: '圖片無法讀取', message: '請重新拍攝，或改從相簿選擇餐點照片。' });
        return;
      }
      await analyzeImage(imageBase64);
    } catch (error: any) {
      setRecordFeedback({ tone: 'error', title: '拍照失敗', message: error?.message || '請再試一次，或改從相簿選擇餐點照片。' });
    }
  };

  const handlePrediction = async (imageBase64: string, isCurrentSession: () => boolean) => {
    const response = await runPrediction({
      apiBaseUrl,
      imageBase64,
      healthConditions: user.healthConditions,
      allergens: user.allergens,
      userId: user.userId,
      auth: { accessToken },
      isCurrentSession,
    });
    if (!isCurrentSession()) return false;
    setIdentityScanContext(response.scanContext);
    const detectedIds = new Set(response.detections.map((food) => food.id));
    setRejectedDetections(response.rejectedDetections.filter((item) => !detectedIds.has(item.item_id || '')));
    setMealWarnings(response.mealWarnings);
    const scanReference: ScannerServerScanReference | null = response.scanContext ? {
        ownerUserId: user.userId,
        apiBaseUrl,
        scan_id: response.scanContext.scan_id,
        scan_revision: response.scanContext.scan_revision,
      } : null;
    const canReviewNutritionMiss = candidateSearchEnabled && Boolean(accessToken && scanReference) &&
      hasReviewableNutritionMiss(response.rejectedDetections, response.scanContext);
    const canConfirmIdentity = identityConfirmationEnabled && Boolean(accessToken && scanReference) &&
      hasUserConfirmableIdentity(response.rejectedDetections, response.scanContext);
    if (response.detections.length > 0 || canReviewNutritionMiss || canConfirmIdentity) {
      setScanResult(response.detections, scanReference);
      setManualResults([]);
      if (canReviewNutritionMiss && candidateSearchEnabled && accessToken && scanReference) {
        void loadFdcCandidates(scanReference, response.scanContext);
      }
      return true;
    }
    return false;
  };

  const analyzeImage = async (imageBase64: string) => {
    setFdcConfirmationDisplay(null);
    setCandidateFailure(null);
    setIdentityScanContext(null);
    setIdentityNameDrafts({});
    setIdentityRequestErrors({});
    pendingIdentityRequestsRef.current = {};
    setPendingIdentityRequests({});
    setIdentitySubmittingItemId(null);
    const attemptId = scanAttemptRef.current + 1;
    scanAttemptRef.current = attemptId;
    const authRevision = useStore.getState().dietaryRecordsRevision;
    const isCurrentSession = () => isCurrentScanSession(attemptId, authRevision);
    if (!isCurrentSession()) return false;
    setScanning(true);
    setRecordFeedback(null);
    try {
      const ok = await handlePrediction(imageBase64, isCurrentSession);
      if (!isCurrentSession()) return false;
      if (!ok) {
        clearScanAndInvalidate();
        setRecordFeedback({ tone: 'error', title: '尚無可記錄的營養結果', message: '請查看下方待確認食物與缺少資料的原因，可用營養標示或手動搜尋補充。若未列出任何食物，請重新拍攝完整餐盤。' });
      }
      return ok;
    } catch (error: any) {
      if (!isCurrentSession()) return false;
      setRejectedDetections([]);
      clearScanAndInvalidate();
      setRecordFeedback({ tone: 'error', title: 'AI 辨識暫時不可用', message: error?.message || '請先使用手動搜尋加入餐點。' });
      return false;
    } finally {
      if (scanAttemptRef.current === attemptId) setScanning(false);
    }
  };

  const handleGallery = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      base64: true,
      quality: 0.7,
    });

    if (result.canceled) return;
    const asset = result.assets[0];
    if (asset.base64) {
      await analyzeImage(asset.base64);
      return;
    }
    setRecordFeedback({ tone: 'error', title: '圖片無法讀取', message: '請改選另一張圖片，或直接使用相機拍攝。' });
  };

  const handleLabelOCRFromGallery = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      base64: true,
      quality: 0.9,
    });

    if (result.canceled) return;
    const asset = result.assets[0];
    if (!asset.base64) {
      setRecordFeedback({ tone: 'error', title: '圖片無法讀取', message: '請改選另一張圖片' });
      return;
    }

    setOcrQuerying(true);
    try {
      const draft = await runNutritionLabelOCR({ apiBaseUrl, imageBase64: asset.base64, auth: { accessToken } });
      ocrSubmissionKeyRef.current = buildSubmissionKey('nutrition-label');
      setOcrDraft(draft);
      setOcrNameError(null);
      setRecordFeedback({ tone: 'success', title: '營養標示已辨識', message: '你可以直接儲存成自訂食品，之後就不必重複輸入。' });
    } catch (error: any) {
      setRecordFeedback({ tone: 'error', title: '營養標示辨識失敗', message: error?.message || '請確認後端已設定 Gemini API key' });
    } finally {
      setOcrQuerying(false);
    }
  };

  /** 拍任何一張菜單，不用先選店家：AI 讀出每道菜，再依疾病與過敏原分成可以吃／要注意／不建議。 */
  const handleMenuCheck = async (source: 'camera' | 'library') => {
    if (menuChecking) return;
    setRecordFeedback(null);
    try {
      let picked: ImagePicker.ImagePickerResult;
      if (source === 'camera') {
        const cameraPermission = await ImagePicker.requestCameraPermissionsAsync();
        if (!cameraPermission.granted) {
          setRecordFeedback({ tone: 'error', title: '需要相機權限', message: '請允許 NutriLens 使用相機，或改從相簿選擇菜單照片。' });
          return;
        }
        picked = await ImagePicker.launchCameraAsync({ base64: true, quality: 0.8 });
      } else {
        picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], base64: true, quality: 0.8 });
      }
      if (picked.canceled) return;
      const imageBase64 = await resolveImageBase64(picked.assets?.[0]);
      if (!imageBase64) {
        setRecordFeedback({ tone: 'error', title: '圖片無法讀取', message: '請重新拍攝，或改選另一張菜單照片。' });
        return;
      }

      setMenuChecking(true);
      setMenuCheck(null);
      const result = await checkMenuPhoto(apiBaseUrl, { menuImage: imageBase64, userId: user.userId }, { accessToken });
      if (result.total_items === 0) {
        setRecordFeedback({ tone: 'error', title: '沒有讀到菜名', message: '請拍清楚一點、讓菜單佔滿畫面，光線充足再試一次。' });
        return;
      }
      setMenuCheck(result);
      setRecordFeedback({
        tone: 'success',
        title: '菜單分析完成',
        message: `${result.total_items} 道菜：可以吃 ${result.safe_items.length}、要注意 ${result.caution_items.length}、不建議 ${result.not_recommended_items.length}。`,
      });
    } catch (error: any) {
      setRecordFeedback({ tone: 'error', title: '菜單辨識失敗', message: error?.message || '請稍後再試一次。' });
    } finally {
      setMenuChecking(false);
    }
  };

  const handleManualSearch = async () => {
    setRecordFeedback(null);
    const keyword = manualQuery.trim();
    if (!keyword) {
      setRecordFeedback({ tone: 'error', title: '請輸入關鍵字', message: '例如：白飯、雞胸肉、花椰菜' });
      return;
    }

    setManualSearching(true);
    try {
      const foods = await manualSearchFood({ apiBaseUrl, keyword, limit: 6, userId: user.userId, auth: { accessToken } });
      setManualResults(foods);
      if (foods.length === 0) {
        setRecordFeedback({ tone: 'error', title: '查無結果', message: '請試試更短的關鍵字或常見食品名稱' });
      }
    } catch {
      setRecordFeedback({ tone: 'error', title: '搜尋失敗', message: '目前無法連線到食品資料庫' });
    } finally {
      setManualSearching(false);
    }
  };

  const submitRecord = async ({
    foods,
    source,
    submissionKey,
    successTitle,
    successMessage,
    onSuccess,
  }: {
    foods: DetectedFood[];
    source: RecordSource;
    submissionKey: string;
    successTitle: string;
    successMessage: string;
    onSuccess: () => void;
  }) => {
    if (
      foods.length === 0
      || recordSubmitInFlightRef.current
      || recordSyncInFlightRef.current
    ) {
      return false;
    }

    recordSubmitInFlightRef.current = true;
    setActiveRecordSubmission({ key: submissionKey, source });
    setRecordFeedback(null);
    Keyboard.dismiss();

    const isCurrentSession = () => {
      const state = useStore.getState();
      return state.user.userId === user.userId && state.accessToken === accessToken && state.apiBaseUrl === apiBaseUrl;
    };
    let pendingId: string | undefined;
    let persisted = false;
    let recordSaved = false;

    try {
      const request = recordSubmissions.prepare({ apiBaseUrl, userId: user.userId, foods, source, submissionKey });
      const result = await recordSubmissions.deliver(request, {
        isCurrent: isCurrentSession,
        persist: async (snapshot) => {
          const nextQueue = await enqueuePendingRecordSync({
            userId: snapshot.userId, clientRecordId: snapshot.clientRecordId,
            apiBaseUrl: snapshot.apiBaseUrl,
            foods: snapshot.foods, source: snapshot.source, error: '',
            recordTimestamp: snapshot.timestamp, mealType: snapshot.mealType,
          });
          persisted = true;
          pendingId = nextQueue.find((item) => item.userId === snapshot.userId && item.clientRecordId === snapshot.clientRecordId)?.id;
          if (isCurrentSession()) setPendingRecordQueue(nextQueue);
        },
        send: async (snapshot) => {
          await saveRecord({ ...snapshot, auth: { accessToken }, isCurrentSession });
          recordSaved = true;
        },
        remove: async (snapshot) => {
          const nextQueue = await removePendingRecordSyncByClientRecordId(snapshot.userId, snapshot.clientRecordId);
          if (isCurrentSession()) setPendingRecordQueue(nextQueue);
        },
      });
      recordSaved = true;
      if (!isCurrentSession()) return false;
      // Refresh from the saved record; response time must not move an old meal into today.
      invalidateDietaryRecords();
      onSuccess();
      setRecordFeedback({
        tone: 'success', title: result.alreadySaved ? '這筆飲食紀錄已儲存' : successTitle,
        message: result.cleanupPending ? '後端已儲存；本機同步狀態稍後更新，請勿重複新增。' : successMessage,
      });
      return true;
    } catch (error: any) {
      if (!isCurrentSession()) return false;
      if (recordSaved) {
        setRecordFeedback({ tone: 'error', title: '紀錄已儲存，畫面更新失敗', message: '請重新整理確認最新紀錄，請勿再次新增。' });
        return false;
      }
      if (error instanceof RecordSubmissionError) {
        setRecordFeedback({ tone: 'error', title: '請先確認原紀錄', message: error.message });
        return false;
      }
      const errorMessage = getRecordSubmitErrorMessage(error);
      if (persisted && pendingId) {
        try {
          const nextQueue = await markPendingRecordSyncFailed(pendingId, errorMessage);
          if (isCurrentSession()) setPendingRecordQueue(nextQueue);
        } catch {
          // The original write-ahead snapshot remains the retry authority.
        }
      }
      if (!isCurrentSession()) return false;
      if (!persisted) {
        setRecordFeedback({
          tone: 'error',
          title: '本機紀錄尚未備妥',
          message: '這筆資料尚未送出。請保留目前畫面，稍後重試；原有待同步資料未清除。',
        });
        return false;
      }
      setRecordFeedback({
        tone: 'error',
        title: '飲食紀錄等待同步',
        message: `${errorMessage}。原內容與用餐時間已保留，可重試同步。`,
      });
      return false;
    } finally {
      recordSubmitInFlightRef.current = false;
      setActiveRecordSubmission(null);
    }
  };

  const syncPendingRecords = useCallback(async (queue: PendingRecordSync[], options?: { manual?: boolean }) => {
    if (recordSubmitInFlightRef.current || recordSyncInFlightRef.current) return 0;
    const userQueue = queue.filter((item) => item.userId === user.userId);
    const retryableQueue = options?.manual ? userQueue : userQueue.filter(canRetryPendingRecordSync);
    if (retryableQueue.length === 0) return 0;
    for (const item of retryableQueue) assertPendingRecordSyncTarget(item, apiBaseUrl);

    recordSyncInFlightRef.current = true;
    setSyncingRecord(true);
    let syncedCount = 0;
    const isCurrentSession = () => {
      const state = useStore.getState();
      return state.user.userId === user.userId && state.accessToken === accessToken && state.apiBaseUrl === apiBaseUrl;
    };
    try {
      for (const item of retryableQueue) {
        if (!isCurrentSession()) break;
        try {
          // 餐別和時間都要用當初入列的時間，不是補送的時間：早上排隊的早餐
          // 如果晚上才連上線，用「現在」判會變成晚餐；半夜排隊的隔天才送，
          // 不帶時間的話後端會把它存成隔天。
          await saveRecord({
            apiBaseUrl,
            userId: item.userId,
            clientRecordId: item.clientRecordId,
            foods: item.foods,
            source: item.source,
            auth: { accessToken },
            isCurrentSession,
            ...getPendingRecordReplayMetadata(item),
          });
          recordSubmissions.markSaved(apiBaseUrl, item.userId, item.clientRecordId);
          if (!isCurrentSession()) break;
          invalidateDietaryRecords();
          syncedCount += 1;
        } catch (error: any) {
          const nextQueue = await markPendingRecordSyncFailed(item.id, error?.message || '後端暫時無法儲存這筆紀錄');
          if (isCurrentSession()) setPendingRecordQueue(nextQueue);
          break;
        }
        try {
          const nextQueue = await removePendingRecordSync(item.id);
          if (isCurrentSession()) setPendingRecordQueue(nextQueue);
        } catch {
          // Remote success is already counted. Cleanup failure keeps the same idempotency ID.
          break;
        }
      }
    } finally {
      recordSyncInFlightRef.current = false;
      setSyncingRecord(false);
    }

    return syncedCount;
  }, [accessToken, apiBaseUrl, invalidateDietaryRecords, user.userId]);

  const retryPendingRecordSync = async () => {
    if (recordSubmitInFlightRef.current || recordSyncInFlightRef.current) return;
    const isCurrentSession = () => {
      const state = useStore.getState();
      return state.user.userId === user.userId && state.accessToken === accessToken && state.apiBaseUrl === apiBaseUrl;
    };
    setRecordFeedback(null);
    try {
      const syncedCount = await syncPendingRecords(pendingRecordQueue, { manual: true });
      if (!isCurrentSession()) return;

      if (syncedCount > 0) {
        setRecordFeedback({
          tone: 'success',
          title: '待同步紀錄已儲存',
          message: `${syncedCount} 筆餐點已寫入後端紀錄。`,
        });
        return;
      }

      const latestQueue = await loadPendingRecordSyncQueue();
      if (!isCurrentSession()) return;
      const latestPendingRecord = latestQueue.find((item) => item.userId === user.userId);
      if (latestPendingRecord) {
        setRecordFeedback({
          tone: 'error',
          title: '同步仍未完成',
          message: `${latestPendingRecord.error} 請稍後再試。`,
        });
      }
    } catch (error) {
      if (!isCurrentSession()) return;
      setRecordFeedback({
        tone: 'error',
        title: '同步仍未完成',
        message: `${getRecordSubmitErrorMessage(error)} 請稍後再試。`,
      });
    }
  };

  useFocusEffect(
    useCallback(() => {
      let active = true;
      loadPendingRecordSyncQueue().then((queue) => {
        if (!active) return;
        setPendingRecordQueue(queue);
        void syncPendingRecords(queue).catch((error) => {
          if (active) setRecordFeedback({ tone: 'error', title: '待同步紀錄需要確認', message: getRecordSubmitErrorMessage(error) });
        });
      }).catch(() => {
        if (!active) return;
        setRecordFeedback({
          tone: 'error',
          title: '待同步紀錄暫時無法讀取',
          message: '本機紀錄尚未同步。偵測到版本衝突或資料讀取問題，資料未清除。',
        });
      });
      return () => {
        active = false;
      };
    }, [syncPendingRecords])
  );

  const handleAddRecord = async () => {
    if (results.length === 0 || automaticNutritionPending) return;
    const submissionKey = `camera:${scanResult.timestamp || results.map((food) => food.id).join(',')}`;
    await submitRecord({
      foods: results,
      source: 'camera',
      submissionKey,
      successTitle: '飲食紀錄已新增',
      successMessage: `${results.length} 項食物已依原用餐時間加入飲食紀錄。`,
      onSuccess: () => {
        const current = useStore.getState().scanResult;
        const currentKey = `camera:${current.timestamp || current.detections.map((food) => food.id).join(',')}`;
        if (currentKey === submissionKey) clearScanAndInvalidate();
      },
    });
  };

  const handleAddManualFood = async (food: DetectedFood) => {
    await submitRecord({
      foods: [food],
      source: 'manual',
      submissionKey: `manual:${food.id}`,
      successTitle: '飲食紀錄已新增',
      successMessage: `${food.foodName} 已以每 100g 份量加入飲食紀錄。`,
      onSuccess: () => setManualResults((current) => current.filter((item) => item.id !== food.id)),
    });
  };

  const handleSaveCustomFood = async () => {
    const draft = getValidatedOCRDraft();
    if (!draft) return;
    try {
      const data = await saveCustomFood({ apiBaseUrl, userId: user.userId, draft, auth: { accessToken } });
      setRecordFeedback({ tone: 'success', title: '自訂食品已儲存', message: `${data.food?.name_zh || draft.product_name} 之後可直接搜尋使用` });
    } catch (error: any) {
      setRecordFeedback({ tone: 'error', title: '儲存失敗', message: error?.message || '請稍後再試' });
    }
  };

  const handleQuickAddOCRFood = async () => {
    const draft = getValidatedOCRDraft();
    if (!draft) return;
    const submissionKey = ocrSubmissionKeyRef.current;
    const food = { ...buildOCRDetectedFood(draft), id: submissionKey };
    await submitRecord({
      foods: [food],
      source: 'nutrition-label',
      submissionKey,
      successTitle: '飲食紀錄已新增',
      successMessage: `${food.foodName} 已依包裝營養標示加入紀錄。`,
      onSuccess: () => {
        if (ocrSubmissionKeyRef.current !== submissionKey) return;
        setOcrDraft(null);
        setOcrNameError(null);
      },
    });
  };

  const handleOCRFoodNameChange = (value: string) => {
    setOcrDraft((current) => current ? { ...current, product_name: value } : current);
    if (ocrNameError && normalizeFoodName(value)) {
      setOcrNameError(null);
    }
  };

  const handleOCRFoodNameBlur = () => {
    if (!ocrDraft) return;
    const foodName = normalizeFoodName(ocrDraft.product_name);
    if (!foodName) {
      setOcrNameError(FOOD_NAME_REQUIRED_MESSAGE);
      return;
    }
    setOcrDraft({ ...ocrDraft, product_name: foodName });
    setOcrNameError(null);
  };

  const getValidatedOCRDraft = (): OCRDraft | null => {
    if (!ocrDraft) return null;
    const foodName = normalizeFoodName(ocrDraft.product_name);
    if (!foodName) {
      setOcrNameError(FOOD_NAME_REQUIRED_MESSAGE);
      return null;
    }
    const normalizedDraft = { ...ocrDraft, product_name: foodName };
    setOcrDraft(normalizedDraft);
    setOcrNameError(null);
    return normalizedDraft;
  };

  const modeConfig = {
    camera: { icon: 'camera-outline' as const, title: '拍攝完整餐盤', hint: '保持光線充足並避免遮擋，拍攝後會立即送出 AI 分析。', action: '啟動相機', onPress: handleCamera },
    gallery: { icon: 'images-outline' as const, title: '從相簿選擇餐點', hint: '可使用已拍攝的餐點照片，不需要重新開啟相機。', action: '選擇餐點照片', onPress: handleGallery },
    label: { icon: 'document-text-outline' as const, title: '辨識包裝營養標示', hint: '選擇清晰的營養標示照片，可建立自訂食品或直接加入紀錄。', action: ocrQuerying ? '辨識中' : '選擇標示照片', onPress: handleLabelOCRFromGallery },
    menu: { icon: 'restaurant-outline' as const, title: '拍菜單看能不能吃', hint: '拍下任何一張菜單，AI 會讀出每道菜，依你的疾病與過敏原分成可以吃、要注意、不建議。大約需要 20~40 秒。', action: menuChecking ? '分析中' : '拍攝菜單', onPress: () => handleMenuCheck('camera') },
    manual: { icon: 'search-outline' as const, title: '從食品資料庫搜尋', hint: '辨識結果不確定時，可直接從 TFDA 與自訂食品中補上餐點。', action: '', onPress: handleManualSearch },
  }[scanMode];

  const captureWorkspace = (
    <>
      <SegmentedControl options={SCAN_MODE_OPTIONS} value={scanMode} onChange={(value) => setScanMode(value as ScanMode)} />
      <View style={styles.scanHero}>
        <View style={styles.scanIcon}>
          {scanResult.isScanning || ocrQuerying || menuChecking ? (
            <ActivityIndicator size="large" color={Palette.accent.green} />
          ) : results.length > 0 && rejectedDetections.length === 0 && scanMode !== 'menu' ? (
            <Ionicons name="checkmark-circle-outline" size={42} color={Palette.accent.green} />
          ) : scanItemCount > 0 && scanMode !== 'menu' ? (
            <Ionicons name="alert-circle-outline" size={42} color={Palette.status.warning} />
          ) : (
            <Ionicons name={modeConfig.icon} size={42} color={Palette.accent.green} />
          )}
        </View>
        <Text style={styles.scanTitle}>
          {menuChecking ? '正在用 AI 分析菜單' : scanResult.isScanning ? '正在分析照片' : resultTitle && scanMode !== 'menu' ? resultTitle : modeConfig.title}
        </Text>
        <Text style={styles.scanHint}>{scanItemCount > 0 && scanMode !== 'menu'
          ? results.length > 0
            ? `${rejectedDetections.length > 0 ? '已配對項目合計' : '估計合計'} ${totalCal} kcal，鈉 ${totalSodium}mg。${rejectedDetections.length > 0 ? `另有 ${rejectedDetections.length} 項待確認，尚未計入。` : '請確認份量後加入。'}`
            : `目前沒有配對營養資料；${rejectedDetections.length} 項待確認，尚未計入。`
          : modeConfig.hint}</Text>
        {scanMode !== 'manual' ? (
          <PrimaryButton label={modeConfig.action} onPress={modeConfig.onPress} disabled={scanResult.isScanning || ocrQuerying || menuChecking} icon={<Ionicons name={modeConfig.icon} size={18} color={Palette.text.inverse} />} />
        ) : null}
        {scanMode === 'menu' ? (
          <SecondaryButton label="從相簿選擇菜單照片" onPress={() => handleMenuCheck('library')} disabled={menuChecking} icon={<Ionicons name="images-outline" size={16} color={Palette.accent.green} />} />
        ) : null}
        {scanMode === 'menu' && menuCheck ? (
          <SecondaryButton label="清除菜單結果" onPress={() => setMenuCheck(null)} disabled={menuChecking} icon={<Ionicons name="trash-outline" size={16} color={Palette.text.secondary} />} />
        ) : null}
        {(results.length > 0 || rejectedDetections.length > 0 || serverScanReference) && scanMode !== 'menu' ? (
          <SecondaryButton label="清除辨識結果" onPress={() => {
            clearScanAndInvalidate();
            setRejectedDetections([]);
            setMealWarnings([]);
          }} icon={<Ionicons name="trash-outline" size={16} color={Palette.text.secondary} />} />
        ) : null}
      </View>
    </>
  );

  const resultWorkspace = scanMode === 'menu' ? (
    <View style={styles.resultWorkspace}>
      {menuCheck ? <MenuCheckResults result={menuCheck} /> : null}
    </View>
  ) : (
    <View style={styles.resultWorkspace}>
      <View style={styles.resultHeader}>
        <Text style={styles.sectionTitle}>辨識結果</Text>
        {scanItemCount > 0 ? <DataPill tone={rejectedDetections.length > 0 ? 'warning' : 'success'}>{scanItemCount} 項食物</DataPill> : null}
      </View>
      <ScannerPendingFoods
        rs={rs}
        items={formatReviewedPendingFoods(rejectedDetections, fdcCandidateSnapshot)}
        identityItems={confirmableIdentityItems}
        identityEnabled={identityConfirmationEnabled}
        identityDrafts={identityNameDrafts}
        identityPending={pendingIdentityRequests}
        identityErrors={identityRequestErrors}
        identityLocked={Object.keys(pendingIdentityRequests).length > 0}
        identitySubmitting={identitySubmittingItemId !== null}
        onIdentityDraftChange={handleIdentityDraftChange}
        onConfirmIdentity={(itemId) => void handleConfirmIdentity(itemId)}
      />
      {candidateLoading === serverScanReference && candidateLoading ? (
        <View accessibilityRole="progressbar"><ActivityIndicator color={Palette.accent.blue} /><Text>{reviewedSelectionEnabled ? '正在配對營養來源' : automaticNutritionPending ? '正在查詢營養來源' : '正在取得 USDA 候選'}</Text></View>
      ) : null}
      {candidateFailure && candidateFailure.reference === serverScanReference ? (
        <View>
          <FeedbackBanner tone="error" title={reviewedSelectionEnabled ? '營養來源配對暫時無法完成' : 'USDA 候選查詢失敗'} message={candidateFailure.recovery.message} />
          {candidateFailure.recovery.retryable ? (
            <SecondaryButton label={reviewedSelectionEnabled ? '重試營養來源配對' : '重試 USDA 候選查詢'} onPress={() => void loadFdcCandidates(candidateFailure.reference, activeIdentityContext)}
              icon={<Ionicons name="refresh-outline" size={17} color={Palette.text.secondary} />} />
          ) : null}
        </View>
      ) : null}
      <ScannerResults
        hasUnmatchedFoods={rejectedDetections.length > 0}
        rs={rs}
        wp={wp}
        results={results}
        onAddRecord={handleAddRecord}
        onWeightChange={updateScanFoodWeight}
        submitting={cameraRecordSubmitting}
        disabled={recordActionsDisabled}
        addDisabled={automaticNutritionPending}
        sodiumDailyTarget={dailyNutrition.sodium.target}
        mealWarnings={mealWarnings}
      />
      {fdcCandidateSnapshot && serverScanReference ? (
        <FdcCandidateReview
          snapshot={fdcCandidateSnapshot}
          reference={serverScanReference}
          enabled={process.env.EXPO_PUBLIC_FDC_CONFIRMATION_ENABLED?.trim().toLowerCase() === 'true'}
          previewEnabled={process.env.EXPO_PUBLIC_FDC_PROFILE_PREVIEW_ENABLED?.trim().toLowerCase() === 'true'}
          completedResult={completedFdcConfirmation}
          onConfirm={handleFdcCandidateConfirmation}
          onUnavailable={handleFdcReferenceUnavailable}
          isCurrentSnapshot={isCurrentCandidateSnapshot}
          isCurrentPreview={isCurrentFdcPreview}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
        />
      ) : null}
      {ocrDraft ? (
        <OCRDraftCard
          draft={ocrDraft}
          foodNameError={ocrNameError}
          onFoodNameChange={handleOCRFoodNameChange}
          onFoodNameBlur={handleOCRFoodNameBlur}
          onSaveCustomFood={handleSaveCustomFood}
          onQuickAdd={handleQuickAddOCRFood}
          submitting={ocrRecordSubmitting}
          actionsDisabled={recordActionsDisabled}
        />
      ) : null}
      <ManualResultsList
        foods={manualResults}
        onAddFood={handleAddManualFood}
        submittingFoodId={submittingManualFoodId}
        actionsDisabled={recordActionsDisabled}
      />
    </View>
  );

  const conditionSummary = (
    <View style={styles.conditionSummary}>
      <Ionicons name="shield-checkmark-outline" size={18} color={Palette.accent.green} />
      <View style={styles.conditionCopy}>
        <Text style={styles.conditionTitle}>安全條件已套用</Text>
        <Text style={styles.conditionText} numberOfLines={2}>疾病：{conditionLabels(user.healthConditions)} · 過敏原：{allergenLabels(user.allergens)}</Text>
      </View>
    </View>
  );

  /**
   * 「手動搜尋」分頁的說明卡沒有按鈕（其他模式那裡是「啟動相機」之類的動作），
   * 而搜尋框先前排在「辨識結果」與「安全條件」之後，要捲兩段才看得到，
   * 使用者會以為這個分頁壞了。改成緊接在說明卡下面。
   */
  const manualTools = scanMode === 'manual' ? (
    <ScannerManualTools rs={rs} manualQuery={manualQuery} onManualQueryChange={setManualQuery} manualSearching={manualSearching} onManualSearch={handleManualSearch} ocrQuerying={ocrQuerying} onOCRSearch={handleLabelOCRFromGallery} />
  ) : null;

  return (
    <AppContainer keyboardShouldPersistTaps="handled">
      <ScreenHeader
        title="AI 食物辨識"
        subtitle="拍照、上傳相簿或掃描營養標示，系統會套用健康條件和過敏原做安全檢查。"
        badge={sourceBadge}
        badgeTone="info"
      />

      {recordFeedback ? (
        <FeedbackBanner
          tone={recordFeedback.tone}
          title={recordFeedback.title}
          message={recordFeedback.message}
          onDismiss={() => setRecordFeedback(null)}
        />
      ) : null}

      {(syncingRecord || firstPendingRecord) ? (
        <View style={[styles.syncStatusCard, firstPendingRecord && styles.syncStatusWarning]}>
          {syncingRecord ? (
            <ActivityIndicator size="small" color={Palette.accent.green} />
          ) : (
            <Ionicons name="cloud-offline-outline" size={16} color={Palette.status.warning} />
          )}
          <View style={styles.syncStatusTextWrap}>
            <Text style={styles.syncStatusTitle}>
              {syncingRecord ? '正在同步飲食紀錄' : `有 ${userPendingRecords.length} 筆餐點尚未同步`}
            </Text>
            {firstPendingRecord ? (
              <Text style={styles.syncStatusMessage}>
                {firstPendingRecord.error || '等待後端確認'}，已重試 {firstPendingRecord.attempts}/{MAX_RECORD_SYNC_ATTEMPTS} 次
              </Text>
            ) : null}
          </View>
          {firstPendingRecord && !syncingRecord ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="重試同步飲食紀錄"
              onPress={retryPendingRecordSync}
              style={styles.retryButton}
            >
              <Text style={styles.retryButtonText}>重試</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      <View style={[styles.desktopColumns, !isDesktop && styles.mobileColumns]}>
        <View style={isDesktop ? styles.desktopCapture : styles.mobileCapture}>
          {captureWorkspace}{manualTools}{conditionSummary}
        </View>
        <View style={isDesktop ? styles.desktopResults : styles.mobileResults}>
          {resultWorkspace}
        </View>
      </View>
    </AppContainer>
  );
}

function buildSubmissionKey(source: RecordSource): string {
  return `${source}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function getRecordSubmitErrorMessage(error: unknown): string {
  if (error instanceof RecordSyncQueueError) {
    if (error.code === 'target_unverified') return '舊紀錄的原儲存位置尚未確認，資料已保留，暫不補送';
    if (error.code === 'target_mismatch') return '這筆紀錄屬於其他伺服器，請切回原設定後再同步；資料已保留';
    if (error.code === 'storage_coordination_unavailable') return '目前瀏覽器無法安全讀取待同步紀錄，資料未清除；請保持畫面並稍後重試';
  }
  const message = error instanceof Error ? error.message.trim() : '';
  if (/failed to fetch|network request failed|fetch failed|networkerror/i.test(message)) {
    return '目前無法連線到伺服器';
  }
  return (message || '目前無法儲存這筆飲食紀錄').replace(/[。.!?]+$/u, '');
}

const styles = StyleSheet.create({
  syncStatusCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
  },
  syncStatusWarning: { borderColor: 'rgba(245,158,11,0.26)', backgroundColor: Palette.accent.orangeDim },
  syncStatusTextWrap: { flex: 1 },
  syncStatusTitle: { ...Typography.caption, color: Palette.text.primary },
  syncStatusMessage: { ...Typography.small, color: Palette.text.tertiary },
  retryButton: {
    minHeight: 44,
    backgroundColor: Palette.bg.card,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    paddingHorizontal: Spacing.md,
    justifyContent: 'center',
  },
  retryButtonText: { ...Typography.caption, color: Palette.status.warning },
  scanHero: {
    backgroundColor: Palette.bg.card,
    borderRadius: Radius['2xl'],
    padding: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.md,
    marginTop: Spacing.md,
    marginBottom: Spacing.xl,
    borderWidth: 1,
    borderColor: Palette.border.subtle,
    ...Shadows.card,
  },
  desktopColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.xl },
  mobileColumns: { flexDirection: 'column', alignItems: 'stretch' },
  desktopCapture: { flex: 1, minWidth: 0 },
  mobileCapture: { minWidth: 0 },
  desktopResults: { flex: 1.08, minWidth: 0 },
  mobileResults: { minWidth: 0 },
  resultWorkspace: { minWidth: 0 },
  scanIcon: {
    width: 82,
    height: 82,
    borderRadius: 41,
    backgroundColor: Palette.bg.mint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scanTitle: { ...Typography.h2, color: Palette.text.primary, textAlign: 'center' },
  scanHint: { ...Typography.caption, color: Palette.text.secondary, textAlign: 'center' },
  conditionSummary: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm, backgroundColor: Palette.bg.card, borderWidth: 1, borderColor: Palette.border.subtle, borderRadius: Radius.lg, padding: Spacing.md, marginBottom: Spacing.xl },
  conditionCopy: { flex: 1, gap: 2 },
  conditionTitle: { ...Typography.caption, color: Palette.text.primary },
  conditionText: { ...Typography.small, color: Palette.text.tertiary },
  resultHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.lg },
  sectionTitle: { ...Typography.h3, color: Palette.text.primary },
  ocrBrandRow: { flexDirection: 'row', marginBottom: Spacing.md },
  ocrNameField: { minWidth: 0, gap: Spacing.xs, marginBottom: Spacing.md },
  ocrNameLabel: { ...Typography.caption, color: Palette.text.secondary },
  ocrNameInput: {
    width: '100%',
    minWidth: 0,
    minHeight: 48,
    backgroundColor: Palette.bg.elevated,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.border.medium,
    color: Palette.text.primary,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    ...Typography.body,
  },
  ocrNameInputError: { borderColor: Palette.status.error, backgroundColor: Palette.accent.pinkDim },
  ocrNameErrorRow: { minHeight: 20, flexDirection: 'row', alignItems: 'center', gap: Spacing.xs },
  ocrNameErrorText: { ...Typography.small, color: Palette.status.error, flex: 1 },
  controlDisabled: { opacity: 0.56 },
  ocrMetaText: { ...Typography.caption, color: Palette.text.tertiary, marginBottom: Spacing.md },
  nutritionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  nutritionItem: { flex: 1, minWidth: '30%', backgroundColor: Palette.bg.elevated, borderRadius: Radius.md, padding: Spacing.sm },
  nutritionLabel: { ...Typography.small, color: Palette.text.tertiary },
  nutritionValue: { ...Typography.caption, ...Typography.number },
  nutritionUnit: { ...Typography.small, color: Palette.text.tertiary },
  ocrActions: { gap: Spacing.sm, marginTop: Spacing.lg },
  manualResultsWrap: { gap: Spacing.md },
  manualFoodCard: { backgroundColor: Palette.bg.elevated, borderRadius: Radius.lg, padding: Spacing.md, gap: Spacing.md },
  manualFoodTop: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  manualFoodCopy: { flex: 1 },
  manualFoodName: { ...Typography.bodyBold, color: Palette.text.primary },
  manualFoodHint: { ...Typography.small, color: Palette.text.tertiary },
  macroRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  macro: { ...Typography.small, color: Palette.text.secondary, backgroundColor: Palette.bg.card, borderRadius: Radius.full, paddingHorizontal: Spacing.sm, paddingVertical: 4 },
});
