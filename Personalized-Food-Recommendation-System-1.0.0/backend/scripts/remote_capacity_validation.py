"""Compare per-user connections with a bounded shared pool on this same client."""

import argparse
from datetime import datetime
from pathlib import Path
import threading

from requests.adapters import HTTPAdapter

from remote_direct_capacity import DirectCapacityTest
from remote_population_test import now


class CapacityValidation(DirectCapacityTest):
    shared_adapter = None
    ramp_seconds = 0

    def authorized_session(self, item):
        client = super().authorized_session(item)
        if self.shared_adapter is not None:
            client.adapters["https://"].close()
            client.mount("https://", self.shared_adapter)
        return client

    def cycle(self, item, client, phase, level, number, first_request=False):
        if first_request and self.ramp_seconds:
            position = self.arrival_position[item["account"]]
            self.stop.wait(self.ramp_seconds * position / max(1, level-1))
        return super().cycle(item, client, phase, level, number, first_request)

    def trial(self, level, seconds, purpose, strategy, ramp_seconds=0):
        self.ramp_seconds = ramp_seconds
        self.arrival_position = {a["account"]: i for i,a in enumerate(self.accounts[:level])}
        self.shared_adapter = HTTPAdapter(pool_connections=1, pool_maxsize=16, pool_block=True, max_retries=0) if strategy == "shared_pool" else None
        try:
            result = self.measure(level, seconds, purpose)
            if result:
                result.update({"connection_strategy": strategy, "pool_max_connections": 16 if self.shared_adapter else None,
                    "arrival_ramp_seconds": ramp_seconds,
                    "pool_wait_included_in_latency": True if self.shared_adapter else None})
                self.save()
            return result
        finally:
            if self.shared_adapter:
                self.shared_adapter.close()
            self.shared_adapter = None
            self.ramp_seconds = 0

    def validate(self):
        monitor = None
        self.report.update({
            "method": "Same local generator and target; independent per-user sessions vs 16-connection shared HTTP/1.1 pool; unique accounts and per-user Authorization headers",
            "note": "Shared-pool virtual users are not separate client devices or IPs. Connection queue time is included in per-request latency. No claim of system-wide maximum is inferred.",
            "long_confirmation_seconds": 180,
        })
        try:
            self.preflight()
            if not self.ensure_accounts(30):
                return
            monitor = threading.Thread(target=self.monitor, daemon=True)
            monitor.start()
            baseline = self.trial(19, 30, "independent_baseline", "independent")
            if not baseline or not baseline["reference_pass"] or self.stop.is_set():
                self.report["search_end"] = "19-user baseline did not pass; inspect changing conditions"
                return
            for attempt in range(2):
                if self.stop.is_set():
                    return
                self.trial(20, 20, f"independent_20_repeat_{attempt+1}", "independent")
            independent_best = 19
            for level in (20, 25, 40, 60, 80, 100):
                if self.stop.is_set():
                    return
                result = self.trial(level, 30, "staggered_arrivals", "independent", ramp_seconds=10)
                if result and result["reference_pass"]:
                    independent_best = level
                else:
                    break
            if not self.stop.is_set():
                result = self.trial(independent_best, 180, "independent_long_confirmation", "independent", ramp_seconds=10)
                self.report["independent_confirmed_users"] = independent_best if result and result["reference_pass"] else None
            if self.stop.is_set():
                return
            best, upper = None, None
            for level in (30, 50, 75, 100):
                result = self.trial(level, 30, "pooled_capacity_search", "shared_pool")
                if self.stop.is_set():
                    return
                if result and result["reference_pass"]:
                    best = level
                else:
                    upper = level
                    break
            if best is None and not self.stop.is_set():
                result = self.trial(20, 30, "pooled_find_baseline", "shared_pool")
                if result and result["reference_pass"]:
                    best = 20
            while best and upper and upper-best > 1 and not self.stop.is_set():
                middle = (best+upper)//2
                result = self.trial(middle, 30, "pooled_binary_refinement", "shared_pool")
                if result and result["reference_pass"]:
                    best = middle
                else:
                    upper = middle
            if best and not self.stop.is_set():
                confirmation = self.trial(best, 180, "pooled_long_confirmation", "shared_pool")
                self.report["pooled_confirmed_users"] = best if confirmation and confirmation["reference_pass"] else None
                self.report["pooled_first_failed_users"] = upper
                if upper and not self.stop.is_set():
                    retry = self.trial(upper, 30, "pooled_neighbor_recheck", "shared_pool")
                    self.report["pooled_neighbor_recheck_passed"] = bool(retry and retry["reference_pass"])
            self.report["search_end"] = "Connection-strategy comparison finished; 100 distinct existing accounts maximum"
        except Exception as exc:
            self.stop_for(f"{type(exc).__name__}: {exc}")
        finally:
            self.monitor_done.set()
            if monitor:
                monitor.join(timeout=30)
            try:
                self.cleanup()
            except Exception as exc:
                self.report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            self.report["finished_at"] = now()
            self.save()
            self.log.close()
            print("CAPACITY VALIDATION FINISHED", str(self.out / f"load_summary_{self.load_id}.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    out = source.parent / ("capacity-validation-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    CapacityValidation(out, source, 30, 180).validate()
