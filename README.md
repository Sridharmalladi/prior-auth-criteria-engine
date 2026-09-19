# Prior-Auth Criteria Engine

[![parity](https://github.com/Sridharmalladi/prior-auth-criteria-engine/actions/workflows/parity.yml/badge.svg)](https://github.com/Sridharmalladi/prior-auth-criteria-engine/actions/workflows/parity.yml)

Checks whether a documented clinical case satisfies published Medicare coverage
criteria, and shows exactly which clause blocks it.

**Live demo:** https://sridharmalladi.github.io/prior-auth-criteria-engine/
**Evaluation:** https://sridharmalladi.github.io/prior-auth-criteria-engine/eval.html

---

## What this is not

- **Not a payer-behavior predictor.** It determines whether documented facts
  satisfy the criteria a policy *publishes*. It does not model how a payer's
  adjudication staff, medical directors, or prior-auth vendor actually decide,
  and it makes no claim about the probability that a real submission would be
  approved or denied.
- **All 20 clinical cases are synthetic**, written for this project to mirror
  discharge/consult note style. They are not real patient records, not
  de-identified real records, and not drawn from MIMIC or any other
  credentialed corpus — that credentialing requirement is incompatible with a
  public repo, so this project doesn't use one.
- **n = 20.** Every accuracy number below rests on twenty cases written by the
  author of the system being measured. Treat the eval page as a demonstration
  of method — decision accuracy, clause attribution, calibration, abstention —
  not as evidence of production accuracy.
- Two of the eight policies (`lumbar_fusion`, `cgm`) are LCDs. CMS returns
  HTTP 401 for LCD detail text without a paid license (embedded AMA/ADA/AHA
  material) — confirmed directly against `api.coverage.cms.gov`, not assumed.
  Those two trees are **paraphrases in our own words**, marked
  `"verification": "unverified-paraphrase"` and flagged with a warning badge
  in the UI. See [`data/policies/CORRECTIONS.md`](data/policies/CORRECTIONS.md).

---

## Architecture

Three kinds of memory, each with a different lifetime and a different owner:

```
┌─────────────────────┐      offline, developer machine      ┌──────────────────┐
│   POLICY MEMORY      │◄──── pipeline/fetch_policies.py ─────┤  CMS MCD API      │
│  data/policies/*.json│      pipeline/build_policies.py      │ (public, no key)  │
│  criteria trees,      │      pipeline/parse_policy.py (LLM) └──────────────────┘
│  hand-reviewed,        │
│  source_ref per node   │
└──────────┬────────────┘
           │ read by
           ▼
┌─────────────────────┐      offline                          ┌──────────────────┐
│   CASE MEMORY         │◄──── pipeline/build_cases.py ────────┤ synthetic notes    │
│  data/cases/*.json    │      pipeline/extract_facts.py (LLM) │ written by hand    │
│  note text, facts with │                                     └──────────────────┘
│  verified source_span  │
└──────────┬────────────┘
           │ facts + tree
           ▼
┌─────────────────────┐
│  BINDING MEMORY (ephemeral, computed per view)               │
│  pipeline/evaluate.py  ──parity──  docs/js/evaluator.js       │
│  one Binding per leaf: {node_id, fact_key, state, reason}     │
│  drives: tree colouring, note highlights, verdict, blocking   │
│  clause, confidence — recomputed synchronously on every edit  │
└─────────────────────┘
```

Policy memory and case memory are committed JSON — read-only at runtime.
Binding memory is never stored: it is the output of `evaluate(policy, facts)`,
recomputed in the browser every time a fact chip is edited. This is why
editing a chip cannot desynchronise the three panes — there is only one
function that produces the displayed state, and it runs fresh each time.

---

## Why a criteria graph beats chunk retrieval

Flat retrieval answers "what text looks similar to this note?" A prior-auth
decision needs the answer to a different question: "does this note satisfy a
*specific boolean combination* of requirements, and if not, which one?"

Three properties chunk retrieval structurally cannot provide, that a graph
gets for free:

1. **Multi-clause attribution.** When two independent criteria fail at once —
   three of the twenty cases here are built exactly this way — a graph walks
   every failing path and ranks the candidates; a retrieval system sees one
   blob of relevant-looking text and has no structure to reason about which
   failure is more fundamental.
2. **Scope-correct negation and alternation.** "Unless," "or," and duration
   qualifiers that attach to one modality but not its siblings are exactly
   the sentences that make policy text hard — see
   [`CORRECTIONS.md`](data/policies/CORRECTIONS.md) for three real examples
   from these eight policies. A chunk-similarity model has no representation
   of scope at all; it either gets the sentence's structure right by luck or
   it doesn't.
3. **Abstention that means something.** UNKNOWN here is not "the model wasn't
   sure" — it's "this specific fact, needed by this specific leaf, was never
   documented." A retrieval system can be prompted to say "indeterminate," but
   it has no way to point at *which* requirement is the gap.

**The evidence, from this repo's own eval:** clause attribution accuracy —
the fraction of correctly-denied cases that name the right blocking clause —
is the headline chart on the [evaluation page](docs/eval.html), specifically
because it is where the gap between the two approaches should be largest. On
the structured evaluator alone: **decision accuracy 20/20 (1.00)**,
**clause attribution 6/8 (0.75)**, computed on hand-labelled gold facts (see
[Known failure modes](#known-failure-modes) for what the 2/8 miss). The
baseline comparison numbers appear once `pipeline/baseline_rag.py` has been
run with an `OPENROUTER_API_KEY` — the eval page states plainly when they are
absent rather than showing an invented number.

---

## Three-valued logic

Every node evaluates to `TRUE`, `FALSE`, or `UNKNOWN`. A fact that was never
documented does not default to failing the criterion — it propagates as
`UNKNOWN`, which is what lets the system land on `INDETERMINATE` instead of a
false `DENY`.

| Node | Rule |
|---|---|
| `LEAF` | fact missing → `UNKNOWN`. fact present → apply the predicate → `TRUE`/`FALSE`. |
| `AND` | any child `FALSE` → `FALSE`. else any child `UNKNOWN` → `UNKNOWN`. else → `TRUE`. |
| `OR` | any child `TRUE` → `TRUE`. else any child `UNKNOWN` → `UNKNOWN`. else → `FALSE`. |
| `NOT` | child `TRUE` → `FALSE`. child `FALSE` → `TRUE`. child `UNKNOWN` → `UNKNOWN`. |
| `N_OF(n)` | count(`TRUE`) ≥ n → `TRUE`. count(`TRUE`) + count(`UNKNOWN`) < n → `FALSE`. else → `UNKNOWN`. |

Root state maps directly to the decision: `TRUE` → `APPROVE`, `FALSE` →
`DENY`, `UNKNOWN` → `INDETERMINATE`.

`pipeline/evaluate.py` and `docs/js/evaluator.js` implement this identically —
see [Parity](#parity) below.

---

## Blocking-clause ranking

Selecting *one* clause to show a reviewer is a separate problem from computing
the root state, and it's the one flat retrieval has no answer for at all. This
project's approach walks *down* the failing paths from the root rather than
testing "does flipping this leaf change the root?" one leaf at a time — a flip
test finds nothing on a case with two independent failures, because neither
flip alone changes the verdict, and those are exactly the cases that matter.
`collect_candidates()` recurses through the tree, at each `AND`/`OR`/`N_OF`
choosing the cheapest arm (fewest leaves needed, then most already satisfied)
to descend into, and returns the leaves that would actually have to change.

Among the resulting candidates, the final ranking is:

1. **Documented outcomes before documentation gaps.** A leaf that is `FALSE`
   — or reached through a `NOT` and therefore blocking while `TRUE` (an
   exclusion that fired) — ranks above a leaf that is merely `UNKNOWN`. A
   confirmed problem is a harder blocker than a missing form.
2. **Shallowest leaf.** It gates the largest share of the tree, and is
   usually the criterion closest to "why was this even proposed."
3. **Smallest required delta.** Between two equally-shallow, equally-documented
   failures, the one closer to being satisfied is reported — "two more months
   of physical therapy" outranks "lose 40 points of BMI" as the thing to fix
   first.
4. **Node id**, purely to make the choice deterministic and testable.

This ranking, and the responsibility-walk that feeds it, is one of the two
places (with the confidence formula) where this project makes a judgement call
that isn't handed down by the policy text itself. It is pinned down by 82
hand-written fixtures in `data/parity/fixtures.json` — see
[`pipeline/make_parity_fixtures.py`](pipeline/make_parity_fixtures.py), where
every `expected_state`/`expected_blocking_node` is written by hand from the
rules above, not read back out of the evaluator.

---

## Confidence formula

**Rule-derived, not calibrated against payer outcomes, and not a probability
of denial.** Every leaf carries weight `w = 1 / (1 + depth)`, so a criterion
gating a whole branch counts for more than one buried inside an untaken
alternative. Let *S*, *F*, *U* be the shares of total leaf weight in states
`TRUE`, `FALSE`, `UNKNOWN`:

```
satisfaction = clamp(S − 0.5·U, 0, 1)

APPROVE        → confidence = satisfaction
DENY           → confidence = 1 − U        (a denial is only as solid as the record is complete)
INDETERMINATE  → confidence = 0.5 + 0.5·U  (the more of the record is missing, the surer the abstention)
```

Implemented identically in `pipeline/evaluate.py::confidence()` and
`docs/js/evaluator.js::confidence()`. The UI states the caveat inline, next to
every number it produces.

---

## Evaluation methodology

Four measures, computed identically for both systems (`pipeline/run_eval.py`):

1. **Decision accuracy** — 3-class, with a full confusion matrix.
2. **Clause attribution accuracy** — of the cases *correctly* denied, the
   fraction naming the right blocking node. The baseline's free-text citation
   is mapped onto a node by token overlap against node labels, predicate keys,
   and section names (`map_citation_to_node()`); a single shared token is
   enough to score. **This mapping is deliberately generous to the baseline**
   — a citation that merely mentions the right subject gets credit.
3. **Calibration** — 10 bins of predicted confidence vs. observed correctness,
   plotted against the diagonal for both systems.
4. **Abstention quality** — precision/recall on the `INDETERMINATE` class
   specifically.

**Baseline tuning disclosure.** `pipeline/baseline_rag.py` is built to be
beaten on the merits: same model, same temperature (0), same three-class
output contract as the structured system's own extraction prompt. Its prompt
was written and revised — the three classes are named explicitly,
`INDETERMINATE` is defined as "the note does not document this" rather than
"you are unsure," and the citation is required to be quoted from the retrieved
excerpts rather than paraphrased. Chunking is ~400 tokens / 50 overlap,
embedded with `all-MiniLM-L6-v2`, top-5 retrieved by cosine similarity in
plain numpy (`faiss` is unnecessary at eight policies). A strawman baseline
would make the comparison chart meaningless; this one was tuned specifically
so it wouldn't be.

**Decision accuracy is computed on hand-labelled gold facts for both systems**,
which isolates the coverage-logic question from the extraction question. A
separate, smaller measurement — `pipeline/extract_facts.py` scored against
gold, and `run_eval.py`'s `structured_extracted` system — shows what happens
end-to-end, including extraction error, and is reported separately rather than
blended into the headline number.

---

## Known failure modes

From this build's run (`data/eval/failures.json`, `data/eval/metrics.json`):
decision accuracy is 20/20 on gold facts; clause attribution is 6/8 on the
correctly-denied cases. The two attribution misses, plus two more surfaced
while authoring the gold labels (recorded, not silently relabelled — see
`pipeline/build_cases.py`), are genuine disagreements between the ranking
rules above and a human's clinical judgement:

- **`lumbar_fusion_03`** (three independent failures: no covered indication,
  incomplete conservative care, active infection) — the evaluator cites the
  shallowest documented failure by the depth rule; a reviewer would lead with
  the active infection as an absolute surgical contraindication. Depth-first
  ranking and clinical-severity-first ranking disagree here by design; this
  project takes the position that depth is the more defensible *automatable*
  proxy and says so rather than hiding the disagreement.
- **`tavr_02`** — the hospital cannot qualify on the experienced-program
  route (`FALSE`) and the new-program volume figures are simply absent
  (`UNKNOWN` for several sibling leaves); the ranking's state-rank rule
  prefers the documented `FALSE` over the `UNKNOWN` siblings, which is correct
  by the stated rule but produces a less actionable clause than "get us the
  volume figures" would be.
- **`home_oxygen_02`**, **`cgm_02`** — similar shallowest-documented-failure
  vs. most-actionable-next-step disagreements.

These are exactly the kind of finding this project is trying to surface
rather than launder into a clean accuracy number. Full context for every
failure is in `data/eval/failures.json`, linked from the evaluation page.

---

## Reproduce

```bash
git clone <this-repo>
cd prior-auth-criteria-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OPENROUTER_API_KEY — only needed for the LLM steps
```

Deterministic core (no API key needed):

```bash
python3 pipeline/make_parity_fixtures.py   # writes data/parity/fixtures.json
python3 pipeline/build_policies.py         # writes data/policies/*.json (8 hand-built trees)
python3 pipeline/build_cases.py            # writes data/cases/*.json (20 synthetic cases)
python3 pipeline/run_eval.py               # writes data/eval/{metrics,results,failures}.json
python3 pipeline/sync_docs_data.py         # copies data/ into docs/data/ for Pages
pytest pipeline/tests -q                   # 541 assertions: fixtures, Python↔JS parity, data checks
```

LLM steps (need `OPENROUTER_API_KEY`; re-fetches source text live from CMS):

```bash
python3 pipeline/fetch_policies.py                 # pulls NCD/LCD metadata + NCD text from api.coverage.cms.gov
python3 pipeline/parse_policy.py --all --diff       # LLM-generated trees vs. the hand-written ones
python3 pipeline/extract_facts.py                   # LLM fact extraction, scored against gold
python3 pipeline/baseline_rag.py                    # the RAG ablation (needs sentence-transformers)
python3 pipeline/run_eval.py                        # re-run once baseline_predictions.json exists
python3 pipeline/sync_docs_data.py
```

Serve and view locally:

```bash
cd docs && python3 -m http.server 8000
# open http://localhost:8000/index.html and http://localhost:8000/eval.html
```

**Deploy to GitHub Pages:** Settings → Pages → Deploy from branch → `main` →
`/docs`. No build step; the site is served as committed. Total shipped data
under `docs/data/` is ~320 KB, well inside the 5 MB budget.

Build order this repo actually followed matches the spec's step 3-before-5
rule: schemas → validator → evaluator → 82 parity fixtures → pytest, *then*
the JS evaluator and parity CI, *then* one hand-built policy end-to-end with
zero LLM involvement, before any model touched policy parsing or fact
extraction.
