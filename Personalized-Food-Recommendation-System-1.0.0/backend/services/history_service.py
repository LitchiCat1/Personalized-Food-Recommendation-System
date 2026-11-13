from decimal import Decimal
import math

from services.nutrient_service import NUTRITION_FIELDS
from services.nutrition_profile_service import NutritionProfileError


def _known_number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 0


def _summary_coverage(daily_data):
    nutrients = {}
    for field in NUTRITION_FIELDS:
        rows = [day.get("nutrition_coverage", {}).get("nutrients", {}).get(field, {}) for day in daily_data]
        counts = {key: sum(row.get(key, 0) for row in rows)
                  for key in ("known_items", "eligible_items", "unresolved_items", "bounded_items", "legacy_items")}
        known_sum = sum((Decimal(str(_known_number(row.get("known_sum")))) for row in rows), Decimal(0))
        bounds_sum = sum((Decimal(str(_known_number(row.get("known_bounds_sum")))) for row in rows), Decimal(0))
        statuses = [row.get("status", "unknown") for row in rows]
        complete = bool(rows) and all(status == "complete" for status in statuses)
        bounded = (bool(rows) and counts["bounded_items"] > 0 and not counts["legacy_items"]
                   and counts["known_items"] + counts["bounded_items"] == counts["eligible_items"]
                   and all(row.get("eligible_items", 0) > 0 for row in rows))
        status = ("legacy_unknown" if "legacy_unknown" in statuses else "complete" if complete else
                  "partial" if counts["known_items"] or counts["bounded_items"] else "unknown")
        nutrients[field] = {
            **counts, "known_sum": float(known_sum), "known_bounds_sum": float(bounds_sum),
            "total_upper_bound": float(known_sum + bounds_sum) if bounded else None,
            "upper_bound_comparison": "less_than" if bounded else None, "status": status,
        }
        if any(value is not None and not math.isfinite(value) for value in
               (nutrients[field]["known_sum"], nutrients[field]["known_bounds_sum"],
                nutrients[field]["total_upper_bound"])):
            raise NutritionProfileError("numeric_range", "History sums exceed supported range")
    return {"schema_version": "NutritionCoverageV1", "nutrients": nutrients}


def build_history_response(storage, user_id: str, days: int, *, nutrition_contract_version=1):
    if nutrition_contract_version == 2:
        daily_data = storage.get_history(user_id, days, nutrition_contract_version=2)
    else:
        daily_data = storage.get_history(user_id, days)

    if daily_data:
        n = len(daily_data)
        total_records = sum(d.get("record_count", 0) for d in daily_data)
        avg = {
            **{
                f"avg_{nutrient}": round(
                    sum(_known_number(d.get(nutrient)) for d in daily_data) / n,
                    1,
                )
                for nutrient in NUTRITION_FIELDS
            },
            "recorded_days": n,
            "total_records": total_records,
            "avg_records_per_day": round(total_records / n, 1),
        }
    else:
        avg = {"recorded_days": 0, "total_records": 0, "avg_records_per_day": 0}

    response = {
        "user_id": user_id,
        "days": days,
        "daily": daily_data,
        "summary": avg,
    }
    if nutrition_contract_version == 2:
        response["nutrition_contract_version"] = 2
        avg["nutrition_coverage"] = _summary_coverage(daily_data)
        avg["avg_known_sum"] = {
            nutrient: round(avg["nutrition_coverage"]["nutrients"][nutrient]["known_sum"] / len(daily_data), 1)
            if daily_data else None for nutrient in NUTRITION_FIELDS
        }
        avg["aggregation_scope"] = "recorded_days_in_requested_range"
    return response
