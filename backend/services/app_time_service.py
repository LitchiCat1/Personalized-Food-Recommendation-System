"""App 本地時區工具。

飲食紀錄的 timestamp 帶本地時區偏移（台灣 +08:00），但伺服器（Render）跑在 UTC。
若用 UTC 判斷「今天」，本地 00:00–08:00 這段時間會抓到昨天的資料。
店家營業時間 (`open_hours`) 同樣是本地時間，拿 UTC 時鐘比對會判錯開店與否。

台灣沒有日光節約時間，所以用固定偏移量即可，不需要 tz database。
需要換地區時設定 `APP_UTC_OFFSET_HOURS`。
"""

import os
from datetime import datetime, timedelta, timezone

DEFAULT_UTC_OFFSET_HOURS = 8.0


def get_app_timezone() -> timezone:
    try:
        offset_hours = float(os.environ.get("APP_UTC_OFFSET_HOURS", DEFAULT_UTC_OFFSET_HOURS))
    except (TypeError, ValueError):
        offset_hours = DEFAULT_UTC_OFFSET_HOURS
    return timezone(timedelta(hours=offset_hours))


def app_now() -> datetime:
    """現在時間（帶 App 本地時區）。"""
    return datetime.now(get_app_timezone())


def to_app_time(value: datetime | None = None) -> datetime:
    """把時間換算成 App 本地時區；naive 值視為已是本地時間。"""
    if value is None:
        return app_now()
    if value.tzinfo is None:
        return value
    return value.astimezone(get_app_timezone())


def app_today(value: datetime | None = None) -> str:
    """本地日期字串 YYYY-MM-DD，與紀錄 timestamp 的日期前綴一致。"""
    return to_app_time(value).strftime("%Y-%m-%d")
