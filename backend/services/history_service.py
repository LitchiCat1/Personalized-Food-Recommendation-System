from services.nutrient_service import NUTRITION_FIELDS


def build_history_response(storage, user_id: str, days: int):
    daily_data = storage.get_history(user_id, days)

    if daily_data:
        n = len(daily_data)
        total_records = sum(d.get("record_count", 0) for d in daily_data)
        avg = {
            **{
                f"avg_{nutrient}": round(
                    sum(d.get(nutrient, 0) for d in daily_data) / n,
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

    return {
        "user_id": user_id,
        "days": days,
        "daily": daily_data,
        "summary": avg,
    }
