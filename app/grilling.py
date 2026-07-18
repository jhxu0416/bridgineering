"""Anthropic calls: decompose a plain-English rule, and grill it with corner cases.

Structured output is forced via TOOL USE (never prefilling / prompt-only JSON),
per the verified pattern in CLAUDE.md. The LLM does NO arithmetic — prevalence.py
computes every number and severity.py assigns every tier; those are fed in as
context and the model only selects and frames the corner cases.

System prompts live in app/prompts/ (one file each).

Standalone gating test (run before any UI):
    uv run python -m app.grilling         # one grill pass on the seed rule
    uv run python -m app.grilling 3       # three passes, to eyeball sharpness
"""

from __future__ import annotations

import json
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

from app import prevalence, severity
from app.prompts.decompose import DECOMPOSE_SYSTEM_PROMPT
from app.prompts.discuss import DISCUSS_SYSTEM_PROMPT
from app.prompts.grilling import GRILLING_SYSTEM_PROMPT
from app.prompts.playbooks import PLAYBOOKS_SYSTEM_PROMPT

load_dotenv()

MODEL = "claude-sonnet-4-6"
client = Anthropic()  # reads ANTHROPIC_API_KEY from env


# ---------------------------------------------------------------------------
# Tools (structured output schemas)
# ---------------------------------------------------------------------------

DECOMPOSE_TOOL = {
    "name": "emit_decomposition",
    "description": "Return the structured form of the clinician's plain-English rule.",
    "input_schema": {
        "type": "object",
        "properties": {
            "listen_for": {
                "type": "string",
                "description": "the patient-facing signal / symptom / utterance the rule listens for",
            },
            "ehr_condition": {
                "type": "string",
                "description": "the structured EHR condition that must hold to fire (column/logic style)",
            },
            "action": {
                "type": "string",
                "description": "the reminder / action surfaced to the clinician",
            },
        },
        "required": ["listen_for", "ehr_condition", "action"],
    },
}

PLAYBOOKS_TOOL = {
    "name": "emit_playbooks",
    "description": "Return the two audience-specific playbooks for the finalized rule.",
    "input_schema": {
        "type": "object",
        "properties": {
            "clinical_playbook": {
                "type": "object",
                "description": "Clinical-language summary for the CMO and clinicians (no tech/data terms).",
                "properties": {
                    "summary": {"type": "string"},
                    "when_it_fires": {"type": "string"},
                    "clinical_rationale": {"type": "string"},
                    "how_it_was_tightened": {"type": "array", "items": {"type": "string"}},
                    "what_to_tell_clinicians": {"type": "array", "items": {"type": "string"}},
                    "caveats": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "summary", "when_it_fires", "clinical_rationale",
                    "how_it_was_tightened", "what_to_tell_clinicians", "caveats",
                ],
            },
            "tech_playbook": {
                "type": "string",
                "description": "CLAUDE.md-style markdown spec for the engineering team to configure the CDS.",
            },
        },
        "required": ["clinical_playbook", "tech_playbook"],
    },
}

DISCUSS_TOOL = {
    "name": "emit_discussion_turn",
    "description": "Return the reviewer's next turn in the per-case grilling conversation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {
                "type": "string",
                "description": "the reviewer's next message to the CMO (concise, specific, on this case)",
            },
            "proposed_refinement": {
                "type": "string",
                "description": "the current best single rule-edit clause reflecting the discussion so far",
            },
        },
        "required": ["reply", "proposed_refinement"],
    },
}

# Verbatim from CLAUDE.md.
CORNER_CASE_TOOL = {
    "name": "emit_corner_cases",
    "description": "Return the corner cases to grill the CMO on.",
    "input_schema": {
        "type": "object",
        "properties": {
            "corner_cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "angle": {"type": "string", "enum": ["safety", "operational", "prevalence"]},
                        "question": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "grounded": {"type": "boolean", "description": "true = backed by computed prevalence (Mode 1); false = improvised data gap (Mode 2)"},
                        "prevalence_note": {"type": "string", "description": "the computed number referenced, or why it can't be computed"},
                        "severity_tier": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
                    },
                    "required": ["angle", "question", "why_it_matters", "grounded", "severity_tier"],
                },
            }
        },
        "required": ["corner_cases"],
    },
}


# ---------------------------------------------------------------------------
# Seed-rule condition set (deterministic facts the LLM grills over)
# ---------------------------------------------------------------------------

TRIGGER_FILTER = {
    "column": "mentioned_rectal_bleeding",
    "op": "eq",
    "value": True,
    "label": "patient mentions rectal bleeding",
}

# Each condition carries a display `label` (used in the facts) and a clean
# `concept` (used only for the severity lookup, so a descriptive label can't
# trip the keyword matcher).
GRILL_CONDITIONS = [
    {"column": "prior_gi_referral_12mo", "op": "eq", "value": True,
     "label": "already had a GI referral in the last 12 months",
     "concept": "prior GI referral"},
    {"column": "colonoscopy_scheduled", "op": "eq", "value": True,
     "label": "colonoscopy already scheduled",
     "concept": "colonoscopy scheduled"},
    {"column": "on_anticoagulants", "op": "eq", "value": True,
     "label": "on anticoagulants",
     "concept": "anticoagulants"},
    {"column": "active_gi_cancer", "op": "eq", "value": True,
     "label": "active GI cancer",
     "concept": "active GI cancer"},
    {"column": "ibd_dx", "op": "eq", "value": True,
     "label": "inflammatory bowel disease (IBD)",
     "concept": "IBD"},
    {"column": "hemorrhoids_dx", "op": "eq", "value": True,
     "label": "hemorrhoids diagnosis (benign bleeding source)",
     "concept": "hemorrhoids"},
    {"column": "age", "op": "lt", "value": 40,
     "label": "under 40 years old",
     "concept": "young low-risk patient"},
    # Mode-2 probe: a real safety factor the panel simply doesn't record.
    {"column": "family_history_colorectal_cancer", "op": "eq", "value": True,
     "label": "family history of colorectal cancer",
     "concept": "family history of colorectal cancer"},
]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def build_grounded_facts(trigger_filter=TRIGGER_FILTER, condition_filters=GRILL_CONDITIONS):
    """Compute deterministic stats and attach a severity tier to each condition."""
    stats = prevalence.compute_stats(trigger_filter, condition_filters)
    facts = []
    for filt, stat in zip(condition_filters, stats):
        concept = filt.get("concept", stat["condition"])
        facts.append({**stat, "severity_tier": severity.lookup(concept)})
    return facts


def _fact_view(f: dict) -> dict:
    """Trim a fact to what the LLM needs, with numbers preformatted so it can
    cite them verbatim without any arithmetic."""
    if f["computable"] == "unanswerable":
        cond = raw = "NOT RECORDED IN PANEL — cannot be computed"
    else:
        cond = f"{f['conditional_count']}/{f['trigger_count']} = {round(f['conditional_prevalence'] * 100)}% of triggering patients"
        raw = f"{f['raw_count']}/{f['total_count']} = {round(f['raw_prevalence'] * 100)}% of all patients"
    return {
        "concept": f["condition"],
        "severity_tier": f["severity_tier"],
        "computable": f["computable"],
        "conditional_prevalence": cond,
        "raw_prevalence": raw,
    }


def grill(rule: str, decomposition: dict, facts: list[dict]) -> list[dict]:
    """Call the LLM to produce ranked corner cases from precomputed facts."""
    trigger_count = facts[0]["trigger_count"] if facts else 0
    total = facts[0]["total_count"] if facts else 0

    payload = {
        "rule_plain_english": rule,
        "structured_rule": decomposition,
        "trigger_cohort": f"{trigger_count} of {total} patients in the panel trigger this rule.",
        "computed_facts": [_fact_view(f) for f in facts],
    }
    user_content = (
        "Here is a clinical reminder rule a CMO wrote, its structured form, and the "
        "deterministic prevalence + severity facts computed from the patient panel. "
        "Every number below is precomputed — use the figures verbatim and never "
        "calculate or invent a number.\n\n"
        + json.dumps(payload, indent=2)
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=GRILLING_SYSTEM_PROMPT,
        tools=[CORNER_CASE_TOOL],
        tool_choice={"type": "tool", "name": "emit_corner_cases"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_block = next(b for b in resp.content if b.type == "tool_use")
    return tool_block.input["corner_cases"]


def decompose(rule: str) -> dict:
    """Call the LLM to decompose a plain-English rule into listen_for/ehr_condition/action."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=DECOMPOSE_SYSTEM_PROMPT,
        tools=[DECOMPOSE_TOOL],
        tool_choice={"type": "tool", "name": "emit_decomposition"},
        messages=[{"role": "user", "content": rule}],
    )
    tool_block = next(b for b in resp.content if b.type == "tool_use")
    return tool_block.input


def discuss(rule: str, decomposition: dict, case: dict, messages: list[dict]) -> dict:
    """One turn of a continuous per-case grilling conversation.

    `messages` is the transcript so far: [{"role": "cmo"|"assistant", "text": ...}].
    Returns {"reply", "proposed_refinement"}. Stateless — the browser holds the
    transcript and re-sends it each turn (no persistence, per CLAUDE.md). The facts
    are recomputed deterministically here so the LLM only cites, never counts.
    """
    facts = build_grounded_facts()
    conversation = [
        {"speaker": "CMO" if m.get("role") == "cmo" else "Reviewer", "text": m.get("text", "")}
        for m in messages
    ]
    payload = {
        "rule_plain_english": rule,
        "structured_rule": decomposition,
        "corner_case": {
            "angle": case.get("angle"),
            "question": case.get("question"),
            "why_it_matters": case.get("why_it_matters"),
            "grounded": case.get("grounded"),
            "prevalence_note": case.get("prevalence_note"),
            "severity_tier": case.get("severity_tier"),
        },
        "computed_facts": [_fact_view(f) for f in facts],
        "conversation": conversation,
    }
    user_content = (
        "Continue grilling this ONE corner case with the CMO. All numbers below are "
        "precomputed — cite them verbatim and never invent a number. Respond with your "
        "next turn via emit_discussion_turn.\n\n"
        + json.dumps(payload, indent=2)
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=DISCUSS_SYSTEM_PROMPT,
        tools=[DISCUSS_TOOL],
        tool_choice={"type": "tool", "name": "emit_discussion_turn"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_block = next(b for b in resp.content if b.type == "tool_use")
    return tool_block.input


def grill_rule(rule: str, decomposition: dict) -> list[dict]:
    """Full grill pipeline for a rule: build facts, then grill. Reused by /api/grill."""
    return grill(rule, decomposition, build_grounded_facts())


def build_playbooks(rule: str, decomposition: dict, refinements: list[dict],
                    open_flags: list[dict]) -> dict:
    """Generate the Clinical + Tech playbooks for a finalized (activated) rule.

    Returns {"clinical_playbook": {...}, "tech_playbook": "<markdown>"}. Reuses the
    deterministic facts so the LLM only cites numbers, never computes them.
    """
    facts = build_grounded_facts()
    payload = {
        "rule_plain_english": rule,
        "structured_rule": decomposition,
        "accepted_refinements": [
            {
                "angle": r.get("angle"),
                "clause": r.get("clause"),
                "addresses": r.get("source"),
            }
            for r in refinements
        ],
        "open_safety_flags": [
            {
                "angle": f.get("angle"),
                "question": f.get("question"),
                "severity_tier": f.get("severity_tier"),
                "why_it_matters": f.get("why_it_matters"),
            }
            for f in open_flags
        ],
        "computed_facts": [_fact_view(f) for f in facts],
    }
    user_content = (
        "The CMO has activated this CDS reminder rule. Write the two playbooks that "
        "summarize the finalized rule. All numbers below are precomputed — cite them "
        "verbatim and never invent a number. Emit both via emit_playbooks.\n\n"
        + json.dumps(payload, indent=2)
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=PLAYBOOKS_SYSTEM_PROMPT,
        tools=[PLAYBOOKS_TOOL],
        tool_choice={"type": "tool", "name": "emit_playbooks"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_block = next(b for b in resp.content if b.type == "tool_use")
    return tool_block.input


# ---------------------------------------------------------------------------
# Gating test:  uv run python -m app.grilling [N]
# ---------------------------------------------------------------------------

SEED_RULE = "When a patient mentions rectal bleeding, remind the clinician to refer to GI."
SEED_DECOMP = {
    "listen_for": "patient mentions rectal bleeding",
    "ehr_condition": "mentioned_rectal_bleeding == true",
    "action": "remind the clinician to refer the patient to GI",
}


def _print_facts(facts: list[dict]) -> None:
    print("GROUNDED FACTS fed to the model (computed deterministically, not by the LLM):")
    print(f"{'concept':<50}{'tier':<8}{'computable':<14}{'conditional':>14}")
    print("-" * 86)
    for f in facts:
        cond = "n/a" if f["conditional_prevalence"] is None else f"{round(f['conditional_prevalence'] * 100)}%"
        print(f"{f['condition']:<50}{f['severity_tier']:<8}{f['computable']:<14}{cond:>14}")


def _print_cases(cases: list[dict]) -> None:
    if not cases:
        print("  (no corner cases — clean rule; all three angles checked)")
        return
    for i, c in enumerate(cases, 1):
        mode = "GROUNDED (Mode 1)" if c.get("grounded") else "IMPROVISED (Mode 2)"
        print(f"\n  [{i}] {c.get('angle', '?').upper():<12} severity={c.get('severity_tier', '?'):<7} {mode}")
        print(f"      Q:   {c.get('question', '')}")
        print(f"      why: {c.get('why_it_matters', '')}")
        note = c.get("prevalence_note")
        if note:
            print(f"      note: {note}")


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(f"SEED RULE: {SEED_RULE}\n")
    facts = build_grounded_facts()
    _print_facts(facts)
    for i in range(1, n + 1):
        print(f"\n===================== GRILL PASS {i}/{n} =====================")
        _print_cases(grill(SEED_RULE, SEED_DECOMP, facts))


if __name__ == "__main__":
    main()
