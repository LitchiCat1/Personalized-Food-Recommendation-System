"""Exercise the mixed read/write cycle without making network requests."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading

from remote_population_load import LoadTest
import remote_population_load as load_module
from remote_population_test import Log, NUTRIENTS, records_match


class Response:
    headers = {}
    content = b"json"

    def __init__(self, code, data):
        self.status_code, self.data = code, data

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, item):
        self.item = item
        self.records = [self.saved(r) for r in item["records"]]

    def saved(self, record):
        return {**deepcopy(record), **{"total_"+k: round(sum(f[k] for f in record["foods"]), 2) for k in NUTRIENTS}}

    def request(self, method, url, **kwargs):
        if url.endswith("/auth/user"):
            return Response(200, {"user": {"id": self.item["uid"]}})
        if "/search/food" in url:
            return Response(200, {"results": []})
        if "/history/" in url:
            return Response(200, {"daily": []})
        if method == "GET":
            return Response(200, {"records": deepcopy(self.records)})
        if method == "POST":
            record = self.saved(kwargs["json"])
            self.records.append(record)
            return Response(201, {"record": deepcopy(record)})
        rid = url.rsplit("/", 1)[1]
        record = next(r for r in self.records if r["client_record_id"] == rid)
        if method == "PATCH":
            record.update(self.saved({**record, **kwargs["json"]}))
            return Response(200, {"record": deepcopy(record)})
        if method == "DELETE":
            self.records.remove(record)
            return Response(200, {"ok": True})
        raise AssertionError(method)


def main():
    path = Path(__file__).resolve().parents[2] / "docs/stress-test/runs/population-20261111-2230/population.json"
    population = json.loads(path.read_text(encoding="utf-8"))
    assert len(population["accounts"]) == 100 and all(a["verified"] for a in population["accounts"])
    ids = [r["client_record_id"] for a in population["accounts"] for r in a["records"]]
    assert len(ids) == len(set(ids)) == 300
    with tempfile.TemporaryDirectory(prefix="population-cycle-") as directory:
        experiment = LoadTest.__new__(LoadTest)
        experiment.out = Path(directory)
        experiment.log = Log(experiment.out, "fake.csv")
        experiment.lock, experiment.stop, experiment.pending = threading.Lock(), threading.Event(), set()
        experiment.load_id = "offline"
        item = population["accounts"][0]
        client = FakeSession(item)
        before = deepcopy(client.records)
        assert experiment.cycle(item, client, "burst", 1, 0, first_request=True)
        assert len(experiment.log.rows) == 8 and all(r["ok"] for r in experiment.log.rows)
        assert client.records == before and not experiment.pending
        assert records_match({"records": client.records}, item["records"])
        corrupted = deepcopy(client.records)
        corrupted[0]["total_calories"] += 1
        assert not records_match({"records": corrupted}, item["records"])
        # Previous burst errors must not abort a healthy persistent stage.
        experiment.phase, experiment.level = "steady", 1
        experiment.report = {"initial_health": {"started_at": "same-process"}, "generator_resources": []}
        sample = deepcopy(experiment.log.rows[0])
        experiment.log.rows.extend({**sample, "phase": "burst", "concurrency": 100, "status": 0, "ok": False} for _ in range(40))
        class OneIteration:
            done = False
            def is_set(self):
                return self.done
            def wait(self, seconds):
                self.done = True
        class HealthSession:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def request(self, *args, **kwargs):
                return Response(200, {"status": "ok", "started_at": "same-process"})
        experiment.monitor_done = OneIteration()
        def reject_false_stop(reason):
            raise AssertionError("Healthy steady phase stopped due to old burst errors: " + reason)
        experiment.stop_for = reject_false_stop
        previous_session = load_module.session
        try:
            load_module.session = HealthSession
            experiment.monitor()
        finally:
            load_module.session = previous_session
        assert not experiment.stop.is_set()
        experiment.log.close()
    print("OFFLINE CHECK PASSED: 100 accounts, 300 unique retained records, CRUD cycle, seed preservation, corruption detection, prior burst errors excluded from steady monitoring; no network.")


if __name__ == "__main__":
    main()
