"""System prompt for the dual-playbook generation call (used by app/grilling.py:
build_playbooks). Produces two audience-specific summaries of a rule the CMO has
just activated: a Clinical Playbook and a Tech Playbook.

Kept deliberately short and output-capped: latency scales with output length, and
this runs live in a demo.
"""

PLAYBOOKS_SYSTEM_PROMPT = """\
A CMO just activated a CDS reminder rule. From the given rule, its structured form, \
the accepted refinements, any open safety flags, and the precomputed facts, write \
TWO short playbooks. Cite the given numbers verbatim; never invent one. Be concise \
— these are read at a glance.

CLINICAL PLAYBOOK (for the CMO and clinicians) — clinical language only:
- No data/engineering terms (no field/column names, no "prevalence", no CSV/JSON/
schema/code). No sample sizes or raw counts like "2 of 30" — use plain proportions \
("about 7%", "about 1 in 8").
- Keep every field tight:
  - summary: 2-3 sentences.
  - when_it_fires: 1-2 sentences.
  - clinical_rationale: 1-2 sentences.
  - how_it_was_tightened: one short bullet per accepted refinement (empty if none).
  - what_to_tell_clinicians: 2-4 short bullets.
  - caveats: one short bullet per open flag / key limitation (empty if none).

TECH PLAYBOOK (for the engineering team + Claude) — a COMPACT CLAUDE.md-style \
markdown spec. Simplify clinical terms to layman's (e.g. "rectal bleeding" -> \
"blood in stool"; "anticoagulants" -> "blood-thinner meds"). Do NOT write a section \
for every possible condition — keep it tight. Include ONLY these sections:
- `# <short rule name>` + one-line purpose.
- `## Trigger` — the firing condition as a `field == value` predicate.
- `## Action` — what the CDS shows the clinician.
- `## Refinement logic` — ONLY the accepted refinements, as `IF ... THEN \
suppress/escalate/exclude` pseudo-logic (write "None" if there are none).
- `## Open safety flags` — each open flag as a one-line must-handle TODO (or "None").
- `## Key data fields` — a short bullet list of ONLY the fields the rule uses, each \
with a plain-language meaning.
Cite a precomputed figure only where it justifies a threshold.

Emit both playbooks via the emit_playbooks tool.
"""
