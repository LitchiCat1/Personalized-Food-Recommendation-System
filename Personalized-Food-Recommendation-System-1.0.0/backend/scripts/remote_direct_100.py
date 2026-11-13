"""Start exactly 100 independent users together, using the existing CRUD flow."""

import argparse
from datetime import datetime
from pathlib import Path
import threading

from remote_capacity_boundary import BoundaryTest
from remote_population_test import now


class DirectHundredTest(BoundaryTest):
    def run_direct(self):
        monitor = None
        self.report.update({
            "method": "100 simultaneous fresh HTTP sessions; no all-user warmup gate; one 8-request authenticated CRUD flow per user",
            "requested_users": 100,
            "conditional_confirmation_seconds": self.soak_seconds,
            "note": "Connection failures count as failed users. Partial completion does not establish sustained capacity for 100 users.",
        })
        try:
            self.preflight()
            if not self.ensure_accounts(100):
                return
            monitor = threading.Thread(target=self.monitor, daemon=True)
            monitor.start()
            result = self.attempt(100, phase="burst", purpose="direct_100_simultaneous_users")
            if result and result["reference_pass"] and not self.stop.is_set():
                confirmation = self.attempt(100, phase="soak", purpose="conditional_100_user_confirmation")
                self.report["confirmation_passed"] = bool(confirmation and confirmation["reference_pass"])
            self.report["search_end"] = "Direct 100-user attempt finished"
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
            print("DIRECT 100 FINISHED", str(self.out / f"load_summary_{self.load_id}.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    out = args.out or source.parent / ("direct100-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    DirectHundredTest(out.resolve(), source, seconds=20, confirmation_seconds=60).run_direct()
