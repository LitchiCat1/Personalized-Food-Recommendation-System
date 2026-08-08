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
    
    # 3. Print Summary Report
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
        
    print("=========================================")
    if all_passed:
        print("SUCCESS: ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("ERROR: SOME TESTS FAILED. PLEASE CHECK THE DETAILS ABOVE.")
        sys.exit(1)

if __name__ == "__main__":
    main()
