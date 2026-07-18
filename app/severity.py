"""Hardcoded clinical-concept -> severity tier lookup.

Loosely based on ICD / CMS-HCC risk. This is deliberately NOT data-driven: it
returns a tier for a concept even when that concept has ZERO rows in the panel
(safety cases are often rare or entirely absent). That keeps the safety override
alive in Mode 2, where the LLM improvises a data gap the panel can't quantify.

    lookup("active_gi_cancer")           -> "high"
    lookup("on anticoagulants")          -> "high"
    lookup("hemorrhoids")                -> "low"
    lookup("family history of CRC")      -> "high"   (no panel column needed)
    lookup("something we've never seen") -> "unknown"

Matching is normalize-then-substring, checked high -> medium -> low so the most
severe keyword present wins (bias toward safety).
"""

from __future__ import annotations

import re

# Keyword -> tier. Keys are matched as substrings against the normalized concept
# (lowercased, non-alphanumerics collapsed to spaces), so panel column names like
# "active_gi_cancer" and free-text like "active GI cancer" both resolve.
_TIERS: dict[str, list[str]] = {
    "high": [
        # malignancy
        "active gi cancer", "gi cancer", "gastrointestinal cancer", "colorectal cancer",
        "colon cancer", "rectal cancer", "bowel cancer", "gi malignancy", "malignancy",
        "cancer", "tumor", "neoplasm", "carcinoma",
        # bleeding risk / anticoagulation
        "anticoagulant", "anticoagulation", "blood thinner", "warfarin", "doac",
        "apixaban", "rivaroxaban", "dabigatran", "heparin",
        # inflammatory bowel disease
        "ibd", "inflammatory bowel disease", "crohn", "ulcerative colitis",
        # dangerous bleeding / acute abdomen
        "gi bleed", "gastrointestinal bleed", "major bleed", "severe bleeding",
        "significant bleeding", "hemodynamic", "perforation", "obstruction",
    ],
    "medium": [
        # the trigger symptom family
        "rectal bleeding", "hematochezia", "melena", "lower gi bleeding",
        "blood in stool", "bloody stool",
        # workup-warranting findings
        "anemia", "iron deficiency", "weight loss", "change in bowel habits",
        "bowel habit", "polyp",
        # age / family CRC risk
        "family history", "over 50", "age 50", "50 or older", "older adult", "elderly",
    ],
    "low": [
        # benign explanations
        "hemorrhoid", "anal fissure", "fissure", "benign",
        # already-handled / operational
        "prior gi referral", "already referred", "gi referral", "referral in place",
        "referred", "referral", "colonoscopy scheduled", "scope scheduled",
        "recent colonoscopy", "colonoscopy", "scheduled",
        # low-risk demographics
        "young", "under 40", "under 50", "low risk",
    ],
}

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


def normalize(concept: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", (concept or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def lookup(concept: str) -> str:
    """Return "high" | "medium" | "low" for a concept, or "unknown" if unmatched."""
    norm = normalize(concept)
    if not norm:
        return "unknown"
    for tier in ("high", "medium", "low"):
        for keyword in _TIERS[tier]:
            if keyword in norm:
                return tier
    return "unknown"


# ---------------------------------------------------------------------------
# Self-test:  uv run python -m app.severity
# Includes concepts with ZERO panel rows to prove severity is data-independent.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    checks = [
        "active_gi_cancer",
        "on_anticoagulants",
        "ibd_dx",
        "rectal bleeding",
        "hemorrhoids_dx",
        "prior_gi_referral_12mo",
        "colonoscopy_scheduled",
        "under 40 years old",
        # zero-row / not-in-panel concepts still resolve:
        "family history of colorectal cancer",
        "GI perforation",
        "unexplained weight loss",
        "a concept we have never modelled",
    ]
    width = max(len(c) for c in checks)
    for c in checks:
        print(f"{c:<{width}}  ->  {lookup(c)}")
