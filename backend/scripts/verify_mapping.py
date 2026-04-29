import json
import sys
sys.path.insert(0, r'd:\VibeCoding\mcu\Personalized-Food-Recommendation-System\backend')

with open(r'd:\VibeCoding\mcu\Personalized-Food-Recommendation-System\backend\nutrition_db_tw.json', 'r', encoding='utf-8') as f:
    tw = json.load(f)

from yolo_tfda_mapping import YOLO_MANUAL_SEARCH_HINTS, YOLO_TO_TFDA

print('=== YOLO -> TFDA Mapping Verification ===')
for label, m in YOLO_TO_TFDA.items():
    key = m.get('tfda_key')
    if key and key in tw:
        food = tw[key]
        print(f'  OK   {label:12s} -> {key:20s}  cal={food["calories"]}, pro={food["protein"]}, fat={food["fat"]}, carbs={food["carbs"]}')
    elif key:
        print(f'  MISS {label:12s} -> {key} NOT FOUND!')
    else:
        print(f'  SKIP {label:12s} (no TFDA mapping)')

print('\n=== Manual Search Hints ===')
for label, hints in YOLO_MANUAL_SEARCH_HINTS.items():
    existing = [hint for hint in hints if any(hint in key or hint in (food.get('name_zh') or '') for key, food in tw.items())]
    missing = [hint for hint in hints if hint not in existing]
    status = 'OK' if existing else 'MISS'
    print(f'  {status:4s} {label:12s} hints={len(hints)} searchable={len(existing)} missing={missing}')
