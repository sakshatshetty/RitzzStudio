# Topic Intelligence / Opportunity Engine — Design

**Status:** Implementation complete; TRENDING and editorial scoring live-validated; EVERGREEN adapter validation remains
**Scope:** Discover, evaluate, and present video topic opportunities; let the user select one; hand the selected or manually entered topic to Research → Outline → Script.
**Out of scope:** Automatic publishing or topic approval, downstream video production changes, full 8-minute image generation, and fabricated provider metrics.

## 1. Goal

Help RITZZ select a strong next video topic using current evidence, not just the largest search-volume number. The system should present a small, useful shortlist with the evidence and tradeoffs visible. The user remains the decision-maker.

Support two entry paths:

1. **Discover topics:** Gather provider-backed candidates, score them, and present a ranked shortlist.
2. **Enter a topic:** Skip discovery and continue through the same content preparation workflow.

A selected candidate is a topic suggestion, not a commitment to produce or publish a video.

## 2. Current repository baseline

The following components already exist:

- `ProjectManager` creates project folders and project metadata.
- `ResearchEngine.research(topic, research_directory, force_refresh=False)` generates structured research using OpenAI web search and caches `research.json`.
- `OutlineEngine.create_outline(research_file, outline_directory, force_refresh=False)` loads research, validates duration, and caches `outline.json`.
- `ScriptEngine.create_script(research_file, outline_file, script_directory, force_refresh=False)` generates and validates narration script output.
- The command-line `app.py` accepts a topic and creates a project, but does not run the content engines in sequence.

No vidIQ integration was present during the initial repository inspection. vidIQ's official documentation now confirms a developer MCP endpoint at `https://mcp.vidiq.com/mcp`, using standard MCP and OAuth 2.0; vidIQ also documents revocable MCP API keys. The implementation uses the official endpoint with a Bearer API key configured through `VIDIQ_MCP_API_KEY`. The endpoint can be overridden with `VIDIQ_MCP_URL`.

The existing Research, Outline, and Script engines are reused. No undocumented REST API or fixed vidIQ tool argument schema is assumed: the MCP client initializes a session, lists tools, inspects the selected tool's JSON schema, and calls it. Live testing found argument-substring collisions, language-code normalization, and the rising tool's requirement for a predefined vidIQ category instead of a free-form niche. Those are fixed. The interactive app asks for a rising category, defaults to `history`, and accepts `ALL` to leave the query unscoped. A live `history` query returned four candidates. The OpenAI editorial assessment and EVERGREEN mode still need live validation.

## 3. User experience

The topic selection screen or command-line interaction should provide:

- A discovery mode with a requested number of candidates and a time horizon.
- Candidate rows showing topic/angle, type (TRENDING or EVERGREEN), opportunity score, score completeness, key signals, evidence date, and a brief explanation.
- A detail view/report for a candidate, including raw provider signals and the component score breakdown.
- Actions to select a candidate, view more candidates, refresh discovery, or enter a manual topic.

Do not automatically create a production project simply because a topic ranked first. Project creation and content preparation start after the user chooses a candidate or supplies a manual topic.

If live discovery is not configured, the interface should say so plainly and offer manual topic entry. A mock provider is for tests/development only; mock candidates must be visibly labeled and must never appear as live trend evidence.

## 4. Proposed architecture

Keep acquisition, scoring, selection, and content preparation separate:

```text
Topic discovery coordinator
  ├─ Topic provider interface
  │    └─ Official vidIQ MCP provider (API key required)
  ├─ Provider response parsing and raw evidence retention
  ├─ Candidate normalization and RITZZ relevance filtering
  ├─ Opportunity evaluator (deterministic, explainable)
  ├─ Topic validation gate and near-duplicate detection
  ├─ Competitor / outlier research
  ├─ Cache / discovery report
  └─ Candidate shortlist
         ↓ user selects candidate
Topic selection artifact
         ↓
Content workflow orchestrator
  ├─ ProjectManager
  ├─ ResearchEngine
  ├─ OutlineEngine
  └─ ScriptEngine
```

The topic provider should retrieve and expand candidate topics; it should not rank candidates with opaque prose alone. The evaluator owns the score calculation. The Research Engine remains independent and must continue to accept a manually supplied topic.

### Recommended module boundaries

Names are proposed and can follow repository naming conventions during implementation:

- `modules/topic_intelligence/models.py`: provider evidence, normalized candidate, score breakdown, report, and selection models.
- `modules/topic_intelligence/providers/base.py`: provider contract and explicit unavailable-provider error/result.
- `modules/topic_intelligence/providers/vidiq_mcp.py`: implemented official MCP adapter, with runtime tool and schema discovery.
- `modules/topic_intelligence/evaluator.py`: deterministic filtering, normalization, scoring, and ranking.
- `modules/topic_intelligence/validation.py`: recommendation eligibility, evidence thresholds, editorial flags, and near-duplicate detection.
- `modules/topic_intelligence/market_intelligence.py`: typed evidence for channels and videos that outperform their baseline.
- `modules/topic_intelligence/engine.py`: discovery orchestration, cache read/write, report generation.
- `modules/content_workflow/engine.py`: selected/manual topic → project → research → outline → script orchestration.
- `app.py`: present candidates and collect user selection; manual input remains available.
- `tests/test_topic_intelligence_*.py` and `tests/test_content_workflow.py`: provider-independent tests using fixtures and fakes.

Provider-specific parsing must not leak into the evaluator or the content workflow.

## 5. Provider contract and live-data boundary

The implemented provider uses vidIQ's documented MCP endpoint. It supports a revocable vidIQ MCP API key in the app's `.env` file (`VIDIQ_MCP_API_KEY`; do not commit the key). The current client uses Bearer authentication. This implementation does not use OAuth login in the application.

It initializes MCP, lists available tools, selects a trend/rising-keyword tool for TRENDING mode or a keyword-research tool for EVERGREEN mode, maps supported query/timeframe/limit fields from the advertised input schema, then calls one provider tool per discovery run. It accepts recognized structured or explicit text rows. If the server has no matching tool, the requested timeframe is unsupported, or the response contains no recognizable topic rows, discovery reports an explicit diagnostic rather than guessing.

The provider interface should express the operations the product needs without assuming how vidIQ implements them. Conceptually:

- Discover candidate keywords/topics for a niche and timeframe.
- Expand a candidate into related keywords and viewer questions.
- Return available demand, competition, growth/trend, and related-video signals.
- Identify data source, retrieval time, and freshness/coverage.

The adapter must preserve both normalized fields and raw source payload (subject to provider terms). It must distinguish:

- A real value of zero.
- A missing value.
- A value the provider does not support.
- A failed or stale provider response.

No missing metric should silently become zero. No estimated vidIQ value should be generated by the LLM. If an official API/MCP is unavailable, document the specific account, permission, endpoint, or connection prerequisite once known; keep manual entry usable in the meantime.

### Competitor and outlier research

The market-intelligence layer uses vidIQ's supported MCP tools separately from
keyword opportunity scoring:

- `vidiq_similar_channels` can identify adjacent channels using the RITZZ niche and channel-size filters.
- `vidiq_outliers` can find long-form videos that outperform their channel baseline by topic/query.
- Each outlier preserves title, channel, subscribers, views, breakout score, engagement rate, velocity, tags, topics, and raw provider evidence.
- `vidiq_balance` exposes credit state before paid research is repeated frequently.

This evidence is not yet converted directly into the opportunity score. First,
collect repeated outlier reports and identify durable patterns such as title
structures, topic families, video length, and channel size. A single viral video
is inspiration, not proof that a topic will succeed for RITZZ.

The CLI competitor path is menu option 2. It accepts a topic-family query,
shows the top three outliers by breakout evidence, and saves the normalized
report to `cache/topic_intelligence/market_intelligence.json`.

## 6. Opportunity data model

The final Pydantic schema should be designed to match verified provider data. The conceptual fields are:

### Discovery report

- `report_id`, `created_at`, requested timeframe and niche.
- Provider identifier, provider/configuration state, retrieval timestamps, and cache status.
- Candidate IDs and ordered candidate list.
- Warnings such as partial coverage, stale data, unavailable metrics, or provider failure.
- Raw provider response references or retained raw payload, as allowed.

### Candidate

- Stable candidate ID and normalized topic/title.
- Primary keyword, related keywords, related questions, and viewer question.
- Opportunity type: `TRENDING`, `EVERGREEN`, or potentially `TREND_TO_EVERGREEN`.
- Provider evidence: search volume, competition, growth, time window, keyword score, related videos, and freshness. Each metric has value, unit/scale, source, observed time, and availability.
- Editorial assessments for RITZZ fit, curiosity, evergreen potential, visual potential, researchability, differentiation, and content saturation.
- Component score breakdown, final opportunity score, confidence/completeness, rank, and human-readable rationale.
- Filter decisions/reasons and raw evidence reference.

### Selection

- Report ID and candidate ID, or a manually supplied topic.
- Selected topic text/angle, selection source, and selection timestamp.
- Optional user edits to title/angle.
- Link to the resulting project ID after the content workflow starts.

Discovery report, selected topic, and project artifacts should be distinct. A user may select a candidate title and refine its framing before research.

## 7. Filtering and scoring

Apply channel-suitability filters before ranking. Exclude or flag topics that are outside the mixed-curiosity niche, unsafe for a general audience, difficult to explain accurately, purely gossip/celebrity news, highly political without a future policy decision, short-lived memes with no useful explainer angle, or visually difficult to communicate.

Scoring is inspectable. The initial 100-point weighting is:

| Component | Weight |
| --- | ---: |
| Demand / underlying search opportunity | 15 |
| Trend momentum and timeframe | 15 |
| Competition (higher score means more manageable) | 10 |
| RITZZ audience fit | 12 |
| Curiosity strength | 10 |
| Evergreen potential | 7 |
| Visual storytelling potential | 8 |
| Researchability | 8 |
| Differentiation opportunity | 8 |
| Content saturation (higher score means less saturated) | 7 |
| **Total** | **100** |

These weights are starting defaults and should be configurable/versioned rather than hidden constants. Each score should include its rubric/evidence. The current implementation uses one structured OpenAI assessment for the candidate batch; its model and prompt version are stored in the report. Provider metrics, editorial judgments, and deterministic transformations remain separate. Editorial scores are preliminary fit judgments, not fact checks.

Search volume and growth are normalized relative to the returned candidate set (log-scaled min/max); competition categories map to a documented ordinal score with lower competition scoring better. Growth is scored only for candidates at or above the median demand in the fetched candidate set, and the weighted average considers available signals only. vidIQ's overall keyword score is retained as raw evidence and is not mislabeled as pure search demand. Compare competition and demand in context. A high growth percentage with negligible underlying demand must not dominate; high demand with extreme competition must not dominate either.

For candidates with missing metrics:

- Keep missingness explicit.
- Compute a provisional score only from available, valid components using documented weight renormalization.
- Show score completeness and apply a minimum evidence threshold for inclusion in the recommended shortlist.
- Do not label a low-completeness score as directly comparable to a fully evidenced score.
- If evidence is inadequate, return the candidate as unranked/review-required or exclude it with a reason; never invent replacement values.

The output should show both the final score and component signals. The explanation should say why the candidate ranks well and what evidence is weak or missing.

### Recommendation validation gate

Ranking is not the same as approval. After ranking, the validation gate keeps all
provider candidates in the report but assigns one of these statuses:

- `RECOMMENDED`: passes editorial fit, evidence completeness, score, and duplicate checks.
- `REVIEW`: visible to the user, but requires a deliberate decision because evidence is weak, editorial fit is uncertain, or the topic duplicates a stronger candidate.
- `REJECTED`: editorial assessment clearly marks the topic as unsuitable.

The initial gate requires at least 50% evidence completeness and an opportunity
score of at least 55. It removes articles such as `the` when detecting near
duplicates, so `The Art of War` and `Art of War` are not presented as separate
recommendations. Thresholds and decisions are stored on each candidate, while
`shortlist_candidate_ids` identifies the recommended set in the report.

## 8. Trend and evergreen handling

Discovery should support at least two intents:

- **TRENDING:** Current upward momentum within a selected timeframe, with enough underlying demand and a viable explainer angle.
- **EVERGREEN / LONG-TAIL:** Stable or recurring viewer interest, reasonable competition, and durable curiosity value.
- **TREND_TO_EVERGREEN:** An emerging event or trend reframed as a lasting explanation, where supported by evidence.

Do not classify a candidate as trending solely from a high growth percentage. Store the observation window and data retrieval time so the user can judge recency. Cached reports should visibly identify their age.

## 9. Discovery and selection flow

1. User chooses TRENDING or EVERGREEN mode and a timeframe; manual topic entry remains available.
2. Coordinator checks for a valid cached report matching provider, query, settings, and freshness policy.
3. If needed, the provider invokes one matching MCP discovery tool and gathers candidates plus any related signals returned by that tool.
4. Optional market research invokes competitor/outlier tools for a selected query or shortlist, separately from keyword discovery.
5. Parser validates response shape and records raw evidence, availability, units, provider, and timestamps.
6. Filters remove or flag poor RITZZ fit with explicit reasons.
7. Evaluator computes component scores, confidence/completeness, ranks, and rationale.
8. Validation gate marks recommendations, review items, rejected items, and near duplicates.
9. Report is saved and the shortlist is presented.
10. User selects a candidate or types/edits a manual topic.
11. Selection is saved before content preparation proceeds.
12. Content workflow creates/resumes a project, runs research, outline, and script in order, and records each successful stage.

Provider discovery does not call the Research Engine for every candidate. It currently makes one vidIQ tool call per discovery run and one OpenAI structured editorial assessment for the batch (in addition to MCP initialization/tool listing). vidIQ documents shared AI credits for MCP tools; check the account's current credit balance before frequent refreshes. The app discloses these two calls before discovery. A later, user-triggered validation step could use Research Engine to check researchability for shortlisted topics; it should be cost-aware and clearly identified.

## 10. Content workflow handoff

The workflow orchestrator receives a normalized topic string and source metadata, not a provider object. For a selected candidate, it should retain the selection/report IDs and discovery rationale in project metadata or a linked selection artifact. For manual topics, it records the entry mode and supplied text.

Expected order:

1. Create or resume the project.
2. Run/reuse `ResearchEngine.research()`.
3. Mark research complete only after valid output has been saved.
4. Run/reuse `OutlineEngine.create_outline()`.
5. Mark outline complete only after validation and save.
6. Run/reuse `ScriptEngine.create_script()`.
7. Mark script complete only after validation and save.

Failures should leave earlier successful stages intact, make the failing stage visible, and allow retry without repeating completed work. Topic discovery should not change downstream video generation APIs.

**Duration compatibility:** current Outline and Script engines encode the 8-minute production target in prompts and validation defaults. The first integration should retain that default. If target duration becomes configurable, pass it explicitly and test that an 8-minute request behaves exactly as it does today. Do not change target length silently as part of topic discovery.

## 11. Artifacts and caching

Proposed artifacts (final paths should match project conventions):

- Discovery cache keyed by provider, normalized query/seeds, timeframe, locale/niche, and relevant settings.
- `topic_candidates.json` or `topic_opportunity_report.json` for a reproducible shortlist.
- `topic_selection.json` for the user decision.
- Project link/reference to the report and selected candidate when content creation starts.

Store fetched time, provider version/configuration, cache age, and scoring/rubric version. Cache raw provider data separately from derived score output so a scoring change can reevaluate candidates without refetching provider data. Support force refresh and cached re-evaluation as separate actions. Define TTL only after understanding provider freshness and rate limits.

## 12. Failure and safety behavior

- Missing credentials or unsupported live API/MCP: return a clear unavailable state and keep manual input functional.
- Provider outage/rate limit: preserve a useful error and offer a cached report if it meets freshness policy.
- Invalid provider response: fail parsing explicitly; never build candidates from guessed fields.
- Partial provider data: retain available evidence and report coverage.
- Empty shortlist: explain filters/evidence thresholds and offer manual entry or revised discovery criteria.
- Low confidence: label for review; do not auto-select.
- Repeated discovery: cache or refresh according to user choice and freshness policy.
- Project workflow failure: persist stage state and allow safe retry.

## 13. Testing strategy

All automated tests use fake providers, fixtures, and mocked engines. No test calls vidIQ, OpenAI, ElevenLabs, or another live service.

### Topic intelligence tests

- Model validation, metric units, timestamps, missing-vs-zero handling.
- Provider parsing for valid, partial, malformed, empty, and error responses.
- Filtering reasons and RITZZ suitability.
- Demand, competition, momentum, saturation, and time-window normalization.
- Scoring weights, component breakdown, missing-signal renormalization, confidence/completeness threshold.
- Large search volume and high growth edge cases do not overpower weak competition/demand context.
- Ranking stability, deterministic tie handling, and report reproducibility for the same inputs/rubric version.
- TRENDING and EVERGREEN classification.
- Cache key, TTL, refresh, cached reevaluation, and stale-data display.
- No live provider configured: manual mode remains available and mock results are not labeled live.

### Content workflow tests

- Selected-candidate and manual-topic paths reach the same research → outline → script sequence.
- Correct project title/topic and selection linkage.
- Stage order and project step updates only after successful saves.
- Cache reuse and force refresh behavior.
- Failure/retry leaves prior outputs and statuses intact.
- Existing 8-minute defaults remain unchanged.

Run focused tests first, then the broader offline suite. Do not weaken existing tests.

## 14. Implementation sequence

1. ~~Confirm the supported vidIQ integration path.~~ Done: official MCP endpoint and authentication options documented.
2. ~~Add normalized models, provider contract, and fake provider fixtures.~~ Done.
3. ~~Implement runtime MCP tool discovery, parsing, and provider-unavailable handling.~~ Done; live auth remains unverified.
4. ~~Implement transparent scoring, ranking, and cache/report persistence.~~ Done; a structured OpenAI editorial assessment supplies editorial dimensions and missing provider data remains explicit. Scoring and validation versions are included in cache keys so stale reports cannot bypass newer gates.
5. ~~Add a discovery entry point and record human selection.~~ Done in the interactive app.
6. ~~Implement selected/manual topic orchestration through the existing engines.~~ Done.
7. Run focused and broad offline tests. Done; live OpenAI web-search test excluded.
8. ~~Add a credential and perform live integration validation before treating trend results as operational.~~ Done for TRENDING `history` discovery and the structured editorial assessment; EVERGREEN still needs adapter validation.

## 15. Acceptance criteria

- User sees structured candidate topics with raw available evidence, score coverage, and transparent scoring.
- Trending and evergreen opportunities can be surfaced.
- Missing provider data is shown as missing; no fake vidIQ signal is presented.
- User selects the topic; no automatic topic approval or publishing occurs.
- Manual topic input remains functional.
- Both topic entry paths feed existing Research → Outline → Script components.
- Cache behavior, stage status, errors, and retries are auditable.
- Existing 8-minute production defaults and downstream pipeline remain intact.
- Mocked tests cover provider, scoring, caching, selection, and workflow behavior.
- The validation gate preserves provider candidates, deduplicates close topics, and requires explicit evidence and editorial thresholds for recommendations.

### Current implementation limits

- Live vidIQ rising discovery is validated for category `history` (four candidates), and the structured OpenAI editorial assessment completed for the resulting report. Unscoped results can include topics outside the channel niche; the app lets the user select a supported vidIQ category. The current EVERGREEN call authenticates but returns only a generic query-derived row, so evergreen argument mapping and usefulness remain unverified.
- The adapter maps only explicit topic rows and provider metrics. It does not transform prose into invented metrics.
- Editorial dimensions are preliminary OpenAI judgments; they are not factual research or verified saturation measurements. If that assessment fails, the report retains provider evidence and explicitly lowers score completeness.
- Tool names and response fields can evolve; runtime schema discovery reduces input assumptions, but actual server compatibility still needs a credentialed check.
