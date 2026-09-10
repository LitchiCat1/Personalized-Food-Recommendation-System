#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated testing runner for Personalized-Food-Recommendation-System.
Runs both backend Python unit tests and frontend TypeScript type checks.
"""
import os
import subprocess
import sys

def run_command(command, cwd=None, env=None):
    try:
        # Use shell=True for system compatibility especially with npx on Windows
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Run Backend Tests
    backend_dir = os.path.join(root_dir, "backend")
    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    
    print("=========================================")
    print("1. Running Backend Unit Tests...")
    print("=========================================")
    backend_code, backend_stdout, backend_stderr = run_command(
        "python -m unittest discover -s tests",
        cwd=backend_dir,
        env=env
    )
    
    # 2. Run Frontend Type Checks
    frontend_dir = os.path.join(root_dir, "frontend")
    print("=========================================")
    print("2. Running Frontend TypeScript Checks...")
    print("=========================================")
    frontend_code, frontend_stdout, frontend_stderr = run_command(
        "npx tsc --noEmit",
        cwd=frontend_dir
    )
    
    # 3. Run Frontend Unit Tests
    #
    # 這些 node --test 測試一直存在，但 runner 從來沒跑過，所以 CI 接不到
    # 它們的迴歸——飲食趨勢、紀錄、掃描與安全條件的規則都靠它們釘著。
    print("=========================================")
    print("3. Running Frontend Unit Tests...")
    print("=========================================")
    frontend_unit_results = []
    for suite in ("trends", "records", "scanner", "config", "safety"):
        code, out, err = run_command(f"npm run --silent test:{suite}", cwd=frontend_dir)
        frontend_unit_results.append((suite, code, out, err))
        print(f"  test:{suite} {'OK' if code == 0 else 'FAILED'}")

    # 4. Print Summary Report
    print("\n=========================================")
    print("           TEST RUN SUMMARY              ")
    print("=========================================")
    
    all_passed = True
    
    if backend_code == 0:
        print("[OK] Backend Unit Tests: PASSED")
    else:
        print("[FAIL] Backend Unit Tests: FAILED")
        print("--- Stdout Output ---")
        print(backend_stdout)
        print("--- Stderr Output ---")
        print(backend_stderr)
        all_passed = False
        
    if frontend_code == 0:
        print("[OK] Frontend TypeScript Type Checks: PASSED")
    else:
        print("[FAIL] Frontend TypeScript Type Checks: FAILED")
        print("--- Stdout Output ---")
        print(frontend_stdout)
        print("--- Stderr Output ---")
        print(frontend_stderr)
        all_passed = False

    failed_suites = [entry for entry in frontend_unit_results if entry[1] != 0]
    if not failed_suites:
        print(f"[OK] Frontend Unit Tests: PASSED ({len(frontend_unit_results)} suites)")
    else:
        print("[FAIL] Frontend Unit Tests: FAILED")
        for suite, _code, out, err in failed_suites:
            print(f"--- test:{suite} ---")
            print(out)
            print(err)
        all_passed = False
        
    print("=========================================")
    if all_passed:
        print("SUCCESS: ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("ERROR: SOME TESTS FAILED. PLEASE CHECK THE DETAILS ABOVE.")
        sys.exit(1)

if __name__ == "__main__":
    main()
