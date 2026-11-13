"""Independently reconcile the report with CSV sources, without network I/O."""

import base64
from collections import Counter
import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import statistics
import sys


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.links = []
        self.details = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            self.images.append(attrs["src"])
        if tag == "a":
            self.links.append(attrs["href"])
        if tag == "details":
            self.details += 1


def main(out):
    report = out / "report"
    analysis = json.loads((report / "analysis.json").read_text(encoding="utf-8"))
    for path, digest in analysis["source_sha256"].items():
        assert hashlib.sha256((out/path).read_bytes()).hexdigest() == digest, path
    with (report / "requests_combined.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for stage in analysis["load"]["stages"]:
        if not stage.get("started"):
            continue
        selected = [r for r in rows if r["phase"] == stage["phase"] and int(r["concurrency"]) == stage["concurrency"] and r["run_id"] == stage["run_id"]]
        assert len(selected) == stage["requests"]
        assert sum(r["ok"] == "False" for r in selected) == stage["failed"]
        values = [float(r["latency_ms"]) for r in selected]
        p95 = statistics.quantiles(values, n=100, method="inclusive")[94] if len(values) > 1 else values[0]
        assert round(p95, 2) == stage["p95_ms"]
    burst100 = next(s for s in analysis["load"]["stages"] if s["phase"] == "burst" and s["concurrency"] == 100)
    assert burst100["users_with_successful_cycles"] == 39 and burst100["users_with_failed_cycles"] == 61
    assert sum(r["phase"] == "invalidated_steady" for r in rows) == 7
    with (report / "retained_records.csv").open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == len({r["record_id"] for r in records}) == 300
    assert set(Counter(r["account"] for r in records).values()) == {3}
    assert set(r["source"] for r in records) == {"manual"}
    verification = analysis["load"]["verification"]
    assert verification["accounts_checked"] == verification["accounts_valid"] == 100
    assert verification["pending_temporary_records"] == verification["outstanding_tokens"] == 0
    assert json.loads((out / "_active_sessions.json").read_text(encoding="utf-8")) == {}
    doc = (report / "index.html").read_text(encoding="utf-8")
    parser = ReportParser()
    parser.feed(doc)
    assert len(parser.images) == 4 and parser.details == 3
    for source in parser.images:
        assert base64.b64decode(source.split(",", 1)[1]).startswith(bytes([137,80,78,71,13,10,26,10]))
    for target in parser.links:
        if not target.startswith("https://"):
            assert (report / target).is_file(), target
    assert "NLStress" not in doc and "access_token" not in doc
    assert "我們怎麼測" in doc and "39 人完成" in doc and "61 人在一開始連線失敗" in doc
    assert analysis["maximum_supported_users"] is None
    print("VERIFIED: source hashes, every stage count/error/P95, 39/100 burst completion, 7 invalidated requests excluded, 300 unique retained records, 100 final account checks, 0 temp records/tokens, 4 embedded PNGs, plain-language method, 3 expandable technical sections, local links, no credentials.")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
