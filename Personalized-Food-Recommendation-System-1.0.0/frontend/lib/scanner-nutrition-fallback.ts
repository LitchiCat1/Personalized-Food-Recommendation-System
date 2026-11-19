import type { NutritionFdcCandidateSnapshotResponse } from './nutrition-fdc-candidate-api';

/** Keep reviewed selection and raw Search separate: they share an immutable snapshot. */
export async function runScannerNutritionFallback({
  mode,
  isCurrent,
  loadFdc,
  onSnapshot,
  requestEnrichment,
}: {
  mode: 'reviewed' | 'search';
  isCurrent: () => boolean;
  loadFdc: () => Promise<NutritionFdcCandidateSnapshotResponse>;
  onSnapshot: (snapshot: NutritionFdcCandidateSnapshotResponse) => void;
  requestEnrichment?: () => Promise<void>;
}): Promise<void> {
  if (!isCurrent()) return;
  const snapshot = await loadFdc();
  if (!isCurrent()) return;
  onSnapshot(snapshot);
  // An empty snapshot is not proof. The enrichment route checks durable Search evidence.
  if (mode === 'search' && snapshot.status === 'empty' && !snapshot.selection && isCurrent()) {
    await requestEnrichment?.();
  }
}
