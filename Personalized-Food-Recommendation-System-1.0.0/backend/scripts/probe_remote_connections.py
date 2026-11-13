"""Small read-only probe of held HTTP connection availability, capped at 20."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

import requests

BASE = "https://node.taile9a8dc.ts.net/health"
OUT = Path(__file__).resolve().parents[2] / "docs/stress-test/runs"


def main():
    sessions = []
    rows = []
    def probe(label, held):
        session = requests.Session()
        begin = time.perf_counter()
        try:
            response = session.get(BASE, timeout=(10, 15))
            ok = response.status_code == 200
            row = {"phase": label, "held_before": held, "status": response.status_code, "latency_ms": round((time.perf_counter()-begin)*1000, 2), "error": ""}
        except requests.RequestException as exc:
            ok = False
            row = {"phase": label, "held_before": held, "status": 0, "latency_ms": round((time.perf_counter()-begin)*1000, 2), "error": str(exc)[:600]}
        rows.append(row)
        print(label, held, row["status"], row["latency_ms"], flush=True)
        if ok:
            sessions.append(session)
        else:
            session.close()
        return ok
    try:
        for index in range(20):
            if not probe("hold", len(sessions)):
                if sessions:
                    sessions.pop().close()
                    time.sleep(2)
                    probe("after_releasing_one", len(sessions))
                break
    finally:
        for session in sessions:
            session.close()
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
        with (OUT / f"connection_probe_{stamp}.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print("ALL PROBE CONNECTIONS CLOSED", flush=True)


if __name__ == "__main__":
    main()
