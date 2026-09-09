#!/usr/bin/env python3
"""Tests for the all-day frequency rule. Run: python3 test_frequency.py"""
import sys

from bus_stops import WINDOW_END, WINDOW_START, qualifies


def t(*times):
    """'07:15' -> seconds since midnight."""
    out = []
    for s in times:
        h, m = s.split(":")
        out.append(int(h) * 3600 + int(m) * 60)
    return out


def every(start, end, step_min):
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += step_min * 60
    return out


CASES = [
    ("evenly spread every 20 min", every(WINDOW_START, WINDOW_END, 20), True),
    ("exactly every 30 min", every(WINDOW_START, WINDOW_END, 30), True),
    ("every 31 min - gap too wide", every(WINDOW_START, WINDOW_END, 31), False),
    ("rush hours only, dead midday",
     t("07:00","07:10","07:20","07:30","12:30","16:00","16:10","16:30","21:30"), False),
    ("starts too late (09:00)", every(t("09:00")[0], WINDOW_END, 15), False),
    ("first departure exactly 07:30", every(t("07:30")[0], WINDOW_END, 20), True),
    ("first departure 07:31 - too late", every(t("07:31")[0], WINDOW_END, 20), False),
    ("ends too early (19:00)", every(WINDOW_START, t("19:00")[0], 15), False),
    ("last departure exactly 21:30", every(WINDOW_START, t("21:30")[0], 30), True),
    ("last departure 21:29 - too early", every(WINDOW_START, t("21:29")[0], 29), False),
    ("single departure", t("12:00"), False),
    ("no departures", [], False),
    ("one 35-min gap in an otherwise dense day",
     every(WINDOW_START, t("13:00")[0], 10) + every(t("13:35")[0], WINDOW_END, 10), False),
    ("unsorted input still handled",
     list(reversed(every(WINDOW_START, WINDOW_END, 20))), True),
    ("duplicate departure times", every(WINDOW_START, WINDOW_END, 20) * 2, True),
    ("departures outside the window are ignored",
     t("05:00") + every(WINDOW_START, WINDOW_END, 20) + t("23:30"), True),
]

failed = 0
for name, times, expected in CASES:
    got = qualifies(times)
    ok = got == expected
    if not ok:
        failed += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: expected {expected}, got {got}")

print(f"\n  {len(CASES) - failed}/{len(CASES)} passed")
sys.exit(1 if failed else 0)
