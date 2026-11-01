#!/usr/bin/env python3
"""
Run from your repo root AFTER finalize_ucc_addition.py, before committing:

    python finalize_ucc_check.py
"""
import json
import os
import sys

checks = []


def check(label, condition):
    checks.append((label, bool(condition)))


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


lookup_py = read("app/tools/institution_programme_lookup.py")
run_eval = read("scripts/run_eval.py")

try:
    with open("data/structured/institution_programmes.json", encoding="utf-8") as f:
        prog_data = json.load(f)
    ucc_rows = [r for r in prog_data["programmes"] if r["institution"] == "UCC"]
except Exception:
    ucc_rows = []

check("institution_programmes.json has 54 real UCC rows",
      len(ucc_rows) == 54)

check("institution_programme_lookup.py has the full-name alias fix",
      lookup_py and "_INSTITUTION_ALIASES" in lookup_py and "university of cape coast" in lookup_py)

check("scripts/run_eval.py's AUTO-11 case reads the real list dynamically, not hardcoded",
      run_eval and 'real = lookup_institutions("Physician Assistantship' in run_eval)

check("tests/test_institution_programme_lookup.py exists",
      os.path.exists("tests/test_institution_programme_lookup.py"))

print()
width = max(len(label) for label, _ in checks)
all_ok = True
for label, ok in checks:
    status = "OK  " if ok else "MISSING"
    if not ok:
        all_ok = False
    print(f"[{status}] {label}")

print()
if all_ok:
    print("Everything landed. Now run:")
    print("  python -m pytest -q          (expect 124 passed)")
    print("  python scripts\\run_eval.py   (expect all automated cases PASS)")
    print("  git add -A")
    print('  git commit -m "Add real UCC per-programme cutoff data; fix tests broken by legitimate category/data growth"')
    print("  git push")
else:
    print("Something didn't land - re-run finalize_ucc_addition.py and check again.")
    sys.exit(1)
