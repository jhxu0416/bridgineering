# 🩺 Bridgineering

**A clinical decision support (CDS) rule-authoring tool that tailors to your own data and patient population.**

Most CDS rules are written once, in the abstract, and only discover their edge
cases after they're live and firing on real patients. Bridgineering moves that
reckoning *before* go-live: a clinician writes a rule in plain English, and the
tool **grills** it with sharp corner cases — grounded in *your* patient panel —
so the rule ships already stress-tested against the population it will run on.

---

## How it works

1. **Write** a rule in plain English
   *(e.g. "When a patient mentions rectal bleeding, remind the clinician to refer to GI.")*
2. **Interpret** — the rule is decomposed into a structured trigger:
   `listen_for` / `ehr_condition` / `action`.
3. **Grill** — the rule is pressure-tested along **three angles**, in priority order:
   - 🔴 **Safety** — could firing (or *not* firing) miss or mishandle a dangerous patient? (anticoagulation, active malignancy, IBD, a risk factor the data can't even see)
   - 🔵 **Operational** — will it fire when the action is already handled, creating alert fatigue? (already referred, colonoscopy already scheduled)
   - 🟢 **Prevalence** — does it mostly fire on low-yield patients? (young, low-risk, benign cause)
4. **Refine** — accept / modify / skip each corner case; the rule tightens as you go.
5. **Activate** — ship a clean rule, a tightened rule, or (deliberately) one with an
   acknowledged, unresolved safety flag.

## What makes the grilling trustworthy

- **Grounded in your data, not hallucinated.** Every prevalence number is computed
  deterministically with pandas over your patient panel. The LLM is *handed* the
  numbers — it never counts, estimates, or invents them.
- **Raw vs. conditional prevalence.** The number that matters is the *conditional*
  one — the rate **among the patients who trigger the rule** — which is what surfaces
  suppression cases (e.g. "1 in 3 triggering patients were already referred").
- **Safety overrides frequency.** A rare-but-dangerous case is never dropped for being
  rare; safety cases are exempt from the corner-case cap and always surfaced.
- **Two modes, both severity-tagged:**
  - **Mode 1 — grounded:** backed by a computed number from your panel.
  - **Mode 2 — data gap:** a real risk the panel *can't* quantify (e.g. family history
    of colorectal cancer isn't recorded). It's still flagged with a severity tier, so
    safety concerns survive even where the data is silent.

Because the whole thing runs over *your* CSV panel and a severity map you control,
the same rule gets grilled differently for different populations — that's the point.

---

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/) and an Anthropic API key.

```bash
# 1. install deps (from the lockfile)
uv sync

# 2. add your key
cp .env.example .env      # then edit .env and set ANTHROPIC_API_KEY=...

# 3. run (one process serves the API and the UI)
uv run uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**.

## Demo walkthrough

The seed rule is prefilled, so it's one click to start.

**Path A — grill → resolve → activate**
1. **Analyze** → confirm the interpreted rule panel.
2. **Begin grilling** → step through the cases: *Accept* (or *Modify*) the
   operational "already referred (33%)" and the prevalence "under-40 / hemorrhoids"
   cases; *Accept* the safety cases.
3. Review the tightened rule → **Activate rule**.

**Path B — the open-safety-flag path**
1. Same start, but on a **high-severity safety** card (anticoagulants / active GI
   cancer / IBD) click **Skip**.
2. A friction dialog warns you're shipping an unresolved safety flag → **Proceed**.
3. The final screen carries a **persistent caveat banner** and the button reads
   **Activate anyway** — it never hard-blocks.

---

## Project layout

```
app/
  main.py            FastAPI: serves the UI + /api/decompose + /api/grill
  grilling.py        Anthropic decompose + grill (structured output via forced tool use)
  prevalence.py      deterministic pandas stats over the panel (raw + conditional)
  severity.py        hardcoded clinical concept -> severity tier (data-independent)
  prompts/           system prompts, one file each (decompose.py, grilling.py)
  static/index.html  single-page vanilla-JS frontend (no build step)
  data/
    panel.csv        mock 100-patient panel
    make_panel.py    regenerates panel.csv with a rigged, reproducible distribution
```

**Stack:** FastAPI + uvicorn · Anthropic Python SDK (`claude-sonnet-4-6`) · pandas · vanilla JS.
Dependencies are managed with `uv` (`pyproject.toml` / `uv.lock`).

## Dev commands

```bash
uv run python -m app.data.make_panel   # regenerate the mock panel + print its distribution
uv run python -m app.prevalence        # self-test: raw/conditional/computable stats
uv run python -m app.severity          # self-test: concept -> tier lookups
uv run python -m app.grilling 3        # run the grill on the seed rule 3x (no UI)
```

## Scope (hackathon MVP)

Bridgineering builds **only** the rule-authoring "grilling" flow. It intentionally
does **not** include runtime reminders, a real EHR/FHIR integration, a database,
auth, or multi-rule management. State lives in the browser and the request payloads;
the patient panel is a mock CSV; the ICD/CMS-HCC severity mapping is hardcoded.
