import json
import sys
sys.path.insert(0, r'd:\VibeCoding\mcu\Personalized-Food-Recommendation-System\backend')

with open(r'd:\VibeCoding\mcu\Personalized-Food-Recommendation-System\backend\nutrition_db_tw.json', 'r', encoding='utf-8') as f:
    tw = json.load(f)

from yolo_tfda_mapping import YOLO_TO_TFDA

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
