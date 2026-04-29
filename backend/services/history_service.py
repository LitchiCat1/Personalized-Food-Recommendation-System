def build_history_response(storage, user_id: str, days: int):
    daily_data = storage.get_history(user_id, days)

    if daily_data:
        n = len(daily_data)
        total_records = sum(d.get("record_count", 0) for d in daily_data)
        avg = {
            "avg_calories": round(sum(d["calories"] for d in daily_data) / n),
            "avg_protein": round(sum(d["protein"] for d in daily_data) / n),
            "avg_carbs": round(sum(d["carbs"] for d in daily_data) / n),
            "avg_fat": round(sum(d["fat"] for d in daily_data) / n),
            "avg_sodium": round(sum(d["sodium"] for d in daily_data) / n),
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
