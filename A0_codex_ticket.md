# Codex Ticket — A0 Real Backend (Terminal)

**Date drafted:** 2026-04-28
**Owner:** Dima
**Track:** Terminal Codex (network + API access required)
**Branch:** `feature/a0-real-backend`
**Depends on:** S1, S2, S3, A1.4 (all merged); preflight check (shipped 2026-04-28); DATA_CONTRACT v0.5 (runtime validation enforcement)

---

## Goal

Replace the A0 stub with a real Gemini-backed company research agent. Single API call produces a populated `company_profile.json` matching schema v0.2, including all judgment fields (`name_confusion_check`, `war_position`, `parallel_business_flag`, `gate_needs_judgment_call`).

After this ticket, the pipeline can take a manually-placed role and produce a real company profile without human intervention. This is the prerequisite for the real F2 evaluator (next ticket).

---

## Stack — locked

- **Research model:** Gemini 2.5 Pro (`gemini-2.5-pro`) via Google AI Studio API
- **Search:** native `google_search` grounding tool
- **Schema enforcement:** native `responseSchema` (Gemini structured output) — **NO two-step formatting**
- **Auth:** existing `GEMINI_API_KEY` env var (Dima already has the key)
- **Fallback:** if grounding returns <3 sources, run a second pass with explicit URL-fetch on top 3 search results
- **Test fixtures:** cached for unit tests, live integration test gated behind `--run-integration` flag

---

## Deliverables

### 1. `agents/a0/research.py`

Real A0 implementation. Replaces the stub.

**Public function:**
```python
def research_company(role: dict) -> dict:
    """
    Take a role record, return a populated company profile dict
    matching company_profile_schema_v0_2.json.

    Uses Gemini 2.5 Pro with google_search grounding.
    Validates output against schema before returning.
    Raises A0ResearchError with structured error info on failure.
    """
```

**Internal flow:**
1. Extract company name + domain from role record
2. Build research prompt from `agents/A0.md` (existing prompt file) + schema as `responseSchema`
3. Call Gemini API with `google_search` tool enabled
4. Parse response, validate against schema
5. If grounding returned <3 sources OR schema validation fails on enrichment fields, run fallback pass
6. Return validated profile dict

**Error handling:**
- API errors (rate limit, network, auth) → raise `A0ResearchError` with retry hint
- Schema validation errors → raise `A0SchemaError` with field-level diagnostics
- Search returned zero results → raise `A0NoSourcesError` (caller decides whether to escalate)

### 2. `agents/a0/gemini_client.py`

Thin wrapper over Gemini API. Isolates the SDK so we can swap providers later if needed.

**Public functions:**
- `call_research(prompt: str, response_schema: dict) -> GeminiResponse`
- `call_with_url_fetch(prompt: str, urls: list[str], response_schema: dict) -> GeminiResponse`

`GeminiResponse` is a dataclass with: `content`, `grounding_metadata`, `sources`, `usage`.

### 3. `agents/a0/schema_loader.py`

Loads `company_profile_schema_v0_2.json` and converts it to Gemini-compatible `responseSchema` format. Gemini's structured output uses a subset of JSON Schema — handle the conversion (drop `$ref`, flatten unions, etc.).

### 4. Pipeline wiring

Update `orchestrator/state_machine.py` (or equivalent) so that when a role transitions from `live → researched`, A0's real `research_company` is called instead of the stub. Keep the boundary clean — the state machine should not know about Gemini.

**Write lane enforcement:** A0 writes through the existing system-owned wrapper to `companies/<domain>.json`. The wrapper validates the lane and the schema before writing. No direct file writes from agent code.

### 5. Tests

`tests/agents/test_a0_research.py`:

- **Unit tests** (use cached fixtures, no live API calls):
  - Happy path: well-known company → profile validates against schema
  - Schema validation catches malformed Gemini response
  - Fallback triggers when grounding returns <3 sources
  - `name_confusion_check` populated even when no confusable lookalike found (`none_found: true`)
  - `gate_needs_judgment_call` populated when war_position is silent for RU-origin leader
  - Write lane: A0 cannot write to `roles/*.json` (raises lane violation)
- **Integration tests** (gated behind `pytest --run-integration`, hit live Gemini):
  - One real call against a known-clean target (e.g., a public scale-up with clear public profile)
  - Verifies grounding actually returns sources, schema validates, runtime is reasonable

### 6. Fixtures

`tests/fixtures/a0/`:

- `gemini_response_clean.json` — captured real response for happy-path company
- `gemini_response_thin_sources.json` — response with <3 sources (triggers fallback)
- `gemini_response_malformed.json` — response with schema violation
- `expected_profile_clean.json` — expected validated output

Generate fixtures by running the integration test once with `--save-fixtures` flag, then commit.

### 7. Docs

`docs/a0.md` — operating notes:

- Stack: Gemini 2.5 Pro + google_search grounding + responseSchema
- Auth: `GEMINI_API_KEY` env var
- Cost expectation: per-call estimate, free-tier limits (1,500 grounded requests/day)
- Fallback behavior: when it triggers, what it does
- How to regenerate test fixtures
- Known limitations (e.g., grounding edge cases, language coverage for RU/BY sources)

---

## Acceptance criteria

- [ ] `research_company(role)` returns a dict that validates against `company_profile_schema_v0_2.json` for happy-path companies
- [ ] `name_confusion_check` is always populated (never null/missing) — agent actively searched
- [ ] For RU/BY-origin leaders, `war_position` field is populated with `value`, `evidence`, `research_scope`, `confidence`
- [ ] `gate_needs_judgment_call` array correctly captures unresolved gates (e.g., silent RU war_position triggers an entry)
- [ ] Source citations included in `source_index` with at least 3 sources for happy-path calls
- [ ] Schema validation fails loudly on malformed responses — no silent partial profiles written to disk
- [ ] Write lane enforcement: A0 can write `companies/*.json`, cannot write anywhere else
- [ ] Unit tests pass without network access (`pytest tests/agents/test_a0_research.py`)
- [ ] Integration test passes against live API (`pytest --run-integration tests/agents/test_a0_research.py`)
- [ ] Pipeline runner picks up A0 real when role state transitions to `researched`
- [ ] `docs/a0.md` exists and covers stack, auth, cost, fallback, fixture regeneration
- [ ] Pre-existing test suite still passes (no regressions in 112-test baseline)

---

## Out of scope

- F2 (separate ticket — depends on this one)
- A0 caching beyond the synthesis cache invalidation already handled by A7 logic (no additional Gemini-call caching layer)
- Multi-provider abstraction. Build for Gemini directly. If we want to swap providers later, refactor at that point.
- Cost tracking dashboard. Log token usage per call to `decisions.log` so we can audit later, but no live cost UI.
- LinkedIn-specific scrapers or special-case research paths. Generic research only.
- Rubric scoring or stance generation. A0 produces facts; F2 produces judgment.

---

## Open questions Codex should NOT answer alone — flag for Dima

1. **Rate limit handling:** if free tier (1,500 grounded RPD on 2.5 Pro) exhausted, what's the expected behavior — fail-fast and queue, or fall back to a paid call? Default to fail-fast for now, flag in `decisions.log`.
2. **Language coverage for war_position research:** schema v0.2 says research_scope should include Russian-language sources for RU/BY-origin founders. Gemini grounding handles multilingual search, but if results are thin, do we explicitly add Russian-language search terms? Default to no for v1; add if integration testing shows the gap.
3. **First test target company:** pick one for the integration test fixture. Suggest something with a publicly clean profile and known data (no carve-out triggers, no judgment-call gates). Codex proposes; Dima approves before live call burns tokens.

---

## Operational notes

- This is a **terminal Codex ticket** — desktop sandbox blocks `pip install google-genai` and live API calls.
- Python 3.11+ env required. If Codex hits a `python3.11` not found error on Dima's Mac, halt and flag — env setup is human work.
- Real API calls during development will burn tokens. Cap dev-loop calls. Always use cached fixtures for repeated test runs; only hit live API when fixture regeneration is intentional.
- Commit the fixture files. They are part of the test surface, not gitignored.

---

## Done means

- PR open against `main`
- All acceptance criteria checked
- Integration test run once successfully against live Gemini, output committed as fixture
- `docs/a0.md` written
- A short note in `MEMORY.md` updating the stub-to-real status
- Ticket handed back with: actual cost of integration test run, any unexpected schema/grounding gotchas surfaced, recommendation on whether F2 ticket needs adjustment based on what A0 actually produces
