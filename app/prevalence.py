"""Deterministic prevalence over the mock panel (data/panel.csv).

The LLM NEVER computes these numbers. This module does, and the results are fed
into the grilling prompt as context (see CLAUDE.md).

A "filter" is a plain dict:
    {"column": str, "op": str, "value": Any, "label": str (optional)}
    op in: eq, ne, lt, le, gt, ge

compute_stats(trigger_filter, condition_filters) returns one dict per condition:
    condition               -> the label (natural-language concept name)
    computable              -> "yes" | "true_zero" | "unanswerable"
    raw_prevalence          -> fraction of the WHOLE panel matching (or None)
    conditional_prevalence  -> fraction among rows matching trigger_filter (or None)
    raw_count / total_count / conditional_count / trigger_count
        -> the underlying integers, so downstream can phrase "10 of 30" exactly.

computable meanings (per CLAUDE.md — never report an unanswerable filter as 0%):
    "unanswerable" -> column/op can't be evaluated against the panel
    "true_zero"    -> valid filter, but 0 rows in the whole panel match it
    "yes"          -> valid filter with >= 1 matching row in the panel
"""

from __future__ import annotations

import operator
from functools import lru_cache
from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).parent / "data" / "panel.csv"

_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}


@lru_cache(maxsize=1)
def load_panel() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    # CSV stores booleans as the strings "True"/"False"; coerce them back so
    # `column == True` filters behave as expected.
    for col in df.columns:
        non_null = set(df[col].dropna().unique())
        if non_null and non_null <= {"True", "False", True, False}:
            df[col] = df[col].map(
                {"True": True, "False": False, True: True, False: False}
            )
    return df


def _mask(df: pd.DataFrame, filt: dict):
    """Boolean mask for a filter, or None if the filter is unanswerable."""
    col = filt.get("column")
    op = filt.get("op", "eq")
    if col not in df.columns or op not in _OPS:
        return None
    try:
        return _OPS[op](df[col], filt.get("value"))
    except Exception:
        return None


def _label(filt: dict) -> str:
    return filt.get("label") or f"{filt.get('column')} {filt.get('op', 'eq')} {filt.get('value')}"


def compute_stats(trigger_filter: dict, condition_filters: list[dict]) -> list[dict]:
    df = load_panel()
    total = len(df)

    trigger_mask = _mask(df, trigger_filter)
    trigger_count = 0 if trigger_mask is None else int(trigger_mask.sum())

    results: list[dict] = []
    for filt in condition_filters:
        mask = _mask(df, filt)

        if mask is None:
            results.append(
                {
                    "condition": _label(filt),
                    "computable": "unanswerable",
                    "raw_prevalence": None,
                    "conditional_prevalence": None,
                    "raw_count": None,
                    "total_count": total,
                    "conditional_count": None,
                    "trigger_count": trigger_count,
                }
            )
            continue

        raw_count = int(mask.sum())
        computable = "true_zero" if raw_count == 0 else "yes"

        if trigger_mask is None or trigger_count == 0:
            cond_count = None
            cond_prev = None
        else:
            cond_count = int((mask & trigger_mask).sum())
            cond_prev = round(cond_count / trigger_count, 4)

        results.append(
            {
                "condition": _label(filt),
                "computable": computable,
                "raw_prevalence": round(raw_count / total, 4) if total else None,
                "conditional_prevalence": cond_prev,
                "raw_count": raw_count,
                "total_count": total,
                "conditional_count": cond_count,
                "trigger_count": trigger_count,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Self-test: stats for the seed rule's conditions.
#   uv run python -m app.prevalence
# ---------------------------------------------------------------------------

SEED_TRIGGER = {
    "column": "mentioned_rectal_bleeding",
    "op": "eq",
    "value": True,
    "label": "mentions rectal bleeding",
}

SEED_CONDITIONS = [
    {"column": "prior_gi_referral_12mo", "op": "eq", "value": True,
     "label": "already had a GI referral in the last 12 months"},
    {"column": "colonoscopy_scheduled", "op": "eq", "value": True,
     "label": "colonoscopy already scheduled"},
    {"column": "on_anticoagulants", "op": "eq", "value": True,
     "label": "on anticoagulants"},
    {"column": "active_gi_cancer", "op": "eq", "value": True,
     "label": "active GI cancer"},
    {"column": "ibd_dx", "op": "eq", "value": True,
     "label": "inflammatory bowel disease (IBD)"},
    {"column": "hemorrhoids_dx", "op": "eq", "value": True,
     "label": "hemorrhoids diagnosis"},
    {"column": "age", "op": "lt", "value": 40,
     "label": "under 40 years old"},
    # demonstrates "true_zero": valid filter, zero matching rows
    {"column": "age", "op": "gt", "value": 120,
     "label": "over 120 years old (true-zero demo)"},
    # demonstrates "unanswerable": column not in the panel
    {"column": "family_history_colorectal_cancer", "op": "eq", "value": True,
     "label": "family history of colorectal cancer (not in panel)"},
]


def _cell(count, denom, prev) -> str:
    if prev is None:
        return "n/a"
    return f"{count}/{denom} = {prev:.0%}"


def _selftest() -> None:
    stats = compute_stats(SEED_TRIGGER, SEED_CONDITIONS)
    total = stats[0]["total_count"]
    trig = stats[0]["trigger_count"]
    print(f"Seed rule trigger: {SEED_TRIGGER['label']}")
    print(f"panel total = {total}   |   trigger cohort = {trig}\n")
    print(f"{'condition':<52}{'computable':<14}{'raw':>16}{'conditional':>16}")
    print("-" * 98)
    for s in stats:
        raw = _cell(s["raw_count"], s["total_count"], s["raw_prevalence"])
        cond = _cell(s["conditional_count"], s["trigger_count"], s["conditional_prevalence"])
        print(f"{s['condition']:<52}{s['computable']:<14}{raw:>16}{cond:>16}")


if __name__ == "__main__":
    _selftest()
