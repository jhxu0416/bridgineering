"""Generate the mock per-patient panel -> data/panel.csv.

Deterministic. Run once via:  uv run python -m app.data.make_panel

The committed artifact is panel.csv; this generator lives alongside it so the
rigged distribution is transparent and easy to adjust.

Everything is rigged around the seed rule:
    "When a patient mentions rectal bleeding, remind the clinician to refer to GI."
so the grilling demo lands. Among the 30 patients who mention bleeding (the
trigger cohort), the conditional prevalences are:

    prior_gi_referral_12mo  ~33%  -> operational suppression (already handled)
    colonoscopy_scheduled   ~17%  -> secondary suppression signal
    on_anticoagulants       ~13%  -> SAFETY, low prevalence but must survive
    active_gi_cancer         ~7%  -> SAFETY, rare but critical, must survive
    ibd_dx                  ~10%  -> safety-adjacent (high tier)
    hemorrhoids_dx          ~30%  -> benign, low tier
    young low-risk          ~37%  -> deferrable prevalence case

Raw (whole-panel) prevalences are deliberately lower than the conditional ones
so the demo can show why the conditional number is the one that matters.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent
CSV_PATH = DATA_DIR / "panel.csv"

FIELDS = [
    "patient_id",
    "age",
    "mentioned_rectal_bleeding",
    "prior_gi_referral_12mo",
    "colonoscopy_scheduled",
    "last_colonoscopy_date",
    "hemorrhoids_dx",
    "on_anticoagulants",
    "ibd_dx",
    "active_gi_cancer",
]

TODAY = date(2026, 7, 18)
rng = random.Random(7)

_next_id = 0


def _recent_date(max_days_ago: int, min_days_ago: int = 15) -> str:
    return (TODAY - timedelta(days=rng.randint(min_days_ago, max_days_ago))).isoformat()


def patient(age: int, bleeding: bool) -> dict:
    global _next_id
    _next_id += 1
    return {
        "patient_id": f"P{_next_id:04d}",
        "age": age,
        "mentioned_rectal_bleeding": bleeding,
        "prior_gi_referral_12mo": False,
        "colonoscopy_scheduled": False,
        "last_colonoscopy_date": "",
        "hemorrhoids_dx": False,
        "on_anticoagulants": False,
        "ibd_dx": False,
        "active_gi_cancer": False,
    }


def build_panel() -> list[dict]:
    rows: list[dict] = []

    # ---- 30 bleeders (trigger cohort), explicit personas -> exact counts ----

    # A. operational suppression: already referred (10)
    for i in range(10):
        r = patient(rng.randint(50, 78), True)
        r["prior_gi_referral_12mo"] = True
        if i < 5:                    # 5 of them also have a colonoscopy scheduled
            r["colonoscopy_scheduled"] = True
        if i < 3:                    # a few have a recent scope on file
            r["last_colonoscopy_date"] = _recent_date(330)
        if i in (8, 9):              # a couple also carry a benign dx
            r["hemorrhoids_dx"] = True
        rows.append(r)

    # B. SAFETY: on anticoagulants, not yet referred (4)
    for _ in range(4):
        r = patient(rng.randint(60, 82), True)
        r["on_anticoagulants"] = True
        rows.append(r)

    # C. SAFETY: active GI cancer, rare but critical (2)
    for _ in range(2):
        r = patient(rng.randint(64, 80), True)
        r["active_gi_cancer"] = True
        rows.append(r)

    # D. safety-adjacent: IBD, skews younger (3)
    for _ in range(3):
        r = patient(rng.randint(24, 46), True)
        r["ibd_dx"] = True
        rows.append(r)

    # E. deferrable prevalence case: young, low-risk (11)
    for i in range(11):
        r = patient(rng.randint(19, 38), True)
        if i < 7:                    # most have benign hemorrhoids
            r["hemorrhoids_dx"] = True
        rows.append(r)

    # ---- 70 non-bleeders (background) --------------------------------------
    # Flags assigned by exact slices so raw prevalence is reproducible; only
    # ages are randomized. The point is raw != conditional.
    non_bleeders = [patient(rng.randint(19, 90), False) for _ in range(70)]

    def set_flag(indices, key):
        for idx in indices:
            non_bleeders[idx][key] = True

    set_flag(range(0, 8), "prior_gi_referral_12mo")   # 8  -> raw referral   18/100
    set_flag(range(8, 14), "on_anticoagulants")       # 6  -> raw anticoag   10/100
    set_flag(range(14, 15), "active_gi_cancer")       # 1  -> raw cancer      3/100
    set_flag(range(15, 20), "colonoscopy_scheduled")  # 5  -> raw scope      10/100
    set_flag(range(20, 28), "hemorrhoids_dx")         # 8  -> raw hemorrhoids 17/100
    set_flag(range(28, 30), "ibd_dx")                 # 2  -> raw ibd         5/100
    for idx in range(15, 18):
        non_bleeders[idx]["last_colonoscopy_date"] = _recent_date(700, 120)

    rows.extend(non_bleeders)
    return rows


def summarize(df: pd.DataFrame) -> None:
    n = len(df)
    trig = df[df["mentioned_rectal_bleeding"]]
    nt = len(trig)
    bool_cols = [
        "prior_gi_referral_12mo",
        "colonoscopy_scheduled",
        "on_anticoagulants",
        "active_gi_cancer",
        "ibd_dx",
        "hemorrhoids_dx",
    ]

    print(f"\nPanel written: {CSV_PATH}")
    print(f"patients: {n}   |   trigger cohort (mention rectal bleeding): {nt}\n")
    print(f"{'condition':<24}{'raw (whole panel)':>20}{'conditional (bleeders)':>26}")
    print("-" * 70)
    for c in bool_cols:
        raw = int(df[c].sum())
        cond = int(trig[c].sum())
        print(f"{c:<24}{f'{raw}/{n} = {raw/n:.0%}':>20}{f'{cond}/{nt} = {cond/nt:.0%}':>26}")

    young_lowrisk = trig[
        (trig["age"] < 40)
        & ~trig["prior_gi_referral_12mo"]
        & ~trig["on_anticoagulants"]
        & ~trig["active_gi_cancer"]
        & ~trig["ibd_dx"]
    ]
    yl = len(young_lowrisk)
    print(f"{'young low-risk (age<40)':<24}{'':>20}{f'{yl}/{nt} = {yl/nt:.0%}':>26}")
    print("\n(raw < conditional is intentional — conditional is the number that")
    print(" matters for suppression; safety cases stay rare on purpose.)")


def main() -> None:
    df = pd.DataFrame(build_panel(), columns=FIELDS)
    df.to_csv(CSV_PATH, index=False)
    summarize(df)


if __name__ == "__main__":
    main()
