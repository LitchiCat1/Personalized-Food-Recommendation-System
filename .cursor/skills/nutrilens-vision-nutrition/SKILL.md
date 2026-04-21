---
name: nutrilens-vision-nutrition
description: >-
  Guides development for NutriLens (Expo + Flask + YOLO): camera scan flow,
  /predict API, nutrition_db.json lookup, PRD-aligned safety rules, and
  non-hallucinated nutrition UX. Use when changing scanner.tsx, backend
  predict/nutrition logic, nutrition_db.json, or when the user asks about food
  photo recognition, calorie accuracy, or model vs database trust boundaries.
---

# NutriLens — Vision and nutrition pipeline

## Repo architecture (authoritative)

- **Frontend**: `frontend/` — Expo Router, `app/(tabs)/scanner.tsx` captures base64 image, `POST {apiBaseUrl}/predict`, maps `detections` to UI; web uses `SCANNER_DEMO_RESULTS` fallback.
- **Backend**: `backend/app.py` — Flask `POST /predict` decodes image, runs Ultralytics `YOLO(MODEL_PATH)`, maps `model.names[cls]` → `get_nutrients(label)` from `nutrition_db.json`, scales per `estimate_weight()` (bbox area × density).
- **Data**: `backend/nutrition_db.json` — per-100g reference macros + `density`, `gi`, `allergens`. Unknown labels use `UNKNOWN_NUTRIENTS` (null macros, note).
- **PRD**: `docs/PRD.md` — Vision Engine + Nutrient Analyzer + Recommendation Manager; BMR/TDEE; disease hard filters.

## Trust model (avoid “nutrition hallucination”)

1. **Numeric macros must not come from an LLM.** Keep the rule: **YOLO (or other detector) → label → `nutrition_db.json` only → scale by estimated grams.** If the label is unknown, return null/zeros with explicit `note` and UI copy that values are not verified.
2. **Separate “what food” from “how much.”** Classification/detection error and portion error are independent; surface **confidence** and **estimated_weight_g** as uncertain, never as exact medical truth.
3. **Confidence gating**: enforce minimum `box.conf` (and optionally IoU) before showing scaled nutrition; below threshold → “可能辨識錯誤” + suggest retake or manual pick from DB-backed list.
4. **Dataset honesty**: default `yolov8n.pt` is COCO-oriented, not a full food taxonomy; PRD “食物辨識” for production implies **fine-tuned food detection** or a food-specific model + expanded `nutrition_db.json` keyed to the same label set.
5. **External authority for numbers**: for higher credibility, map labels to **USDA FoodData Central / 衛福部 TFND** IDs and store `source` + `per_100g` + retrieval date in API responses (still no free-form generation of grams).
6. **User correction loop**: let users override label and portion; persist corrections to improve estimates (telemetry), not to silently invent DB rows without curation.

## Implementation touchpoints

- Scanner → API: `frontend/app/(tabs)/scanner.tsx` (`/predict` body: `image` base64; optionally pass `health_conditions`, `allergens` per PRD).
- Server predict: `backend/app.py` `predict()` — add gates, `source` metadata, or alternate detectors here; keep nutrition math next to `get_nutrients` / `scaled_nutrition`.

## Product copy

- Always disclose: **估計值**，受光線、角度、遮擋、混合餐與模型限制影響；慢性病飲食請以醫事人員建議為準。
