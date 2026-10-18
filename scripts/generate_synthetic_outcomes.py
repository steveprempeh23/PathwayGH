#!/usr/bin/env python3
"""Generates data/structured/historical_student_outcomes.csv - a SYNTHETIC
cohort dataset for Question 9 (Data Analysis Capability).

This is not real admissions data. Real, student-level WASSCE/CSSPS outcome
records at this granularity aren't publicly available, and using invented
numbers as if they were real would violate the same honesty principle this
whole project is built around. This script exists so the dataset's
construction is fully transparent and reproducible (fixed seed) rather than
a CSV of unexplained numbers - anyone can re-run it and get the exact same
file, and can read exactly how "admitted" is decided.

Rule: aggregate is sampled around each category's band from programmes.json;
admission is TRUE with 90% probability if aggregate falls within the band,
10% probability otherwise (modeling real-world borderline variance, not
hidden business logic).
"""

import csv
import json
import random
from pathlib import Path

random.seed(42)  # fixed seed - reproducible, not cherry-picked per run

ROOT = Path(__file__).resolve().parent.parent
PROGRAMMES_PATH = ROOT / "data" / "structured" / "programmes.json"
OUTPUT_PATH = ROOT / "data" / "structured" / "historical_student_outcomes.csv"

YEARS = [2021, 2022, 2023, 2024, 2025]
STUDENTS_PER_CATEGORY_PER_YEAR = 12  # modest, keeps the CSV small and inspectable


def load_categories() -> list[dict]:
    with open(PROGRAMMES_PATH, encoding="utf-8") as f:
        return json.load(f)["programme_categories"]


def generate_row(student_id: int, category: dict, year: int) -> dict:
    band = category["aggregate_band"]
    # Sample aggregate in a slightly wider range than the band itself, so
    # some students land outside it - otherwise "admission rate" would be
    # a trivial 90%/10% constant with no real spread to analyze.
    spread_low = max(6, band["best"] - 4)
    spread_high = band["worst"] + 10
    aggregate = random.randint(spread_low, spread_high)

    in_band = band["best"] <= aggregate <= band["worst"]
    admitted = random.random() < (0.90 if in_band else 0.10)

    return {
        "student_id": student_id,
        "year": year,
        "programme_category": category["category"],
        "track": category["track"],
        "aggregate": aggregate,
        "admitted": admitted,
    }


def main() -> None:
    categories = load_categories()
    rows = []
    student_id = 1

    for year in YEARS:
        for category in categories:
            for _ in range(STUDENTS_PER_CATEGORY_PER_YEAR):
                rows.append(generate_row(student_id, category, year))
                student_id += 1

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "year", "programme_category", "track", "aggregate", "admitted"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} synthetic rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
