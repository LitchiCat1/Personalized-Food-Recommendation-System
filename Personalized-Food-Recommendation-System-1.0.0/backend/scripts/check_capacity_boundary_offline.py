"""Verify search control flow without making network requests."""

from pathlib import Path
import threading
from types import SimpleNamespace

from remote_capacity_boundary import BoundaryTest


def fake_experiment(outcomes):
    experiment = BoundaryTest.__new__(BoundaryTest)
    experiment.report = {}
    experiment.stop = threading.Event()
    experiment.monitor_done = threading.Event()
    experiment.out = Path("offline-boundary")
    experiment.load_id = "offline"
    experiment.log = SimpleNamespace(close=lambda: None)
    experiment.preflight = lambda: None
    experiment.ensure_accounts = lambda count: True
    experiment.monitor = lambda: None
    experiment.save = lambda: None
    experiment.cleanup = lambda: experiment.report.update(cleaned=True)
    experiment.calls = []

    def attempt(level, phase="steady", purpose="search"):
        experiment.calls.append((level, phase, purpose))
        return {"reference_pass": outcomes.pop(0)}

    experiment.attempt = attempt
    return experiment


def main():
    # Warmup failure must not skip later explicitly requested 10-user stages.
    fixed = fake_experiment([False, False, True, True])
    fixed.search([20, 30, 40])
    assert [call[0] for call in fixed.calls] == [20, 30, 40, 40]
    assert fixed.report["short_test_passing_levels"] == [40]
    assert fixed.report["confirmation_passed"] is True
    assert fixed.report["cleaned"] is True
    assert "finished_at" in fixed.report

    edge = fake_experiment([True, True, False, False, True, False])
    edge.search()
    assert [call[0] for call in edge.calls] == [18, 19, 20, 20, 19, 20]
    assert edge.report["highest_short_test_passing_level"] == 19
    assert edge.report["adjacent_failing_level"] == 20
    assert edge.report["next_level_recheck_passed"] is False
    assert edge.report["cleaned"] is True
    print("OFFLINE PASSED: explicit steps continue after warmup failures; repeated boundary and confirmation; cleanup always runs; no network")


if __name__ == "__main__":
    main()
