# GitHub Actions Pipeline

RITZZ video runs are started from the GitHub Actions web interface. Normal video
production does not require a local command-line command.

## Current workflow

Workflow file: `.github/workflows/ritzz-pipeline.yml`

The default topic-discovery path uses one vidIQ market-opportunity discovery
operation, followed by one GPT ideation request:

When starting a run, the GitHub form provides `Test run`, `Target video
duration in minutes`, and `Minimum allowed video duration in minutes`. Both
duration fields default to 8 minutes, and the minimum cannot exceed the target.

Before tests or external providers run, the workflow validates that all required
secrets are present and that the Google client and token secrets decode to valid
OAuth JSON, including the vidIQ API key required for discovery. Preflight makes
no provider API calls and does not prove that a key has live service permission.

1. Run focused pipeline regression tests.
2. Make one vidIQ keyword-research call using the `strange history` seed,
   selected as a market-discovery starting point for the RITZZ profile, to get
   up to 20 opportunities.
3. Send that pool, including any provider-supplied metrics, in one OpenAI
   structured-output request to generate 8–10 video ideas.
4. Apply simple local RITZZ, originality, and inventory filters; present up to
   five candidates and require at least three.
5. Publish the candidates in a GitHub issue and workflow artifact.
6. Wait for a trusted collaborator to reply with one of the displayed labels.
7. Pause at the protected topic-approval environment.
8. Pause at the protected test-approval environment.
9. Run the existing Research -> Outline -> Script content workflow.
10. Upload the generated project artifacts to the GitHub Actions run.
11. Use the human-selected topic and its vidIQ opportunity context to inform titles, tags, description framing,
   and the thumbnail brief; persist the source report and candidate context.
12. Generate and validate ElevenLabs narration with character alignment.
13. Build the narrative and audio-timed static storyboard.
14. Render the test video and run deterministic technical QA.
15. Pause for human video review and approval.
16. Pause for packaging approval.
17. Upload the test video privately through YouTube OAuth.
18. Keep the current run marked as a test run; public publication remains
   disabled.

Topic duplicate prevention reads the durable repository inventory at
`data/content_inventory.json`. Test runs do not write to this file and therefore
do not reserve or permanently exclude their selected topics. A future approved
V1 release will update the inventory with the final topic and publication data.

## Legacy discovery capabilities (not used by the default workflow)

The existing non-pipeline topic-intelligence engine can start from enabled channels in
`config/competitors.json` (override with `RITZZ_COMPETITORS_FILE`). The registry
has three distinct groups: `format_competitors` (similar illustrated/explainer
formats), `topic_competitors` (overlapping subjects), and `emerging_format`
(newer channels using relevant formats). Each entry may use `channel_id`,
`channel_handle`, or `channel_url`; vidIQ resolves handles/URLs for its
channel-scoped video tools, so manually supplied UC IDs are not required. When
the advertised video-tool schema accepts handles/URLs, the provider passes
those references directly instead of spending credits on a separate metadata
lookup. Otherwise, available channel metadata tools can verify identity and
retain the provider's channel name/description/type. An empty registry never
invents competitor evidence; the pipeline can still try explicitly secondary
discovery sources.

The adapter discovers MCP tools and their argument schemas at runtime. It
queries each competitor group separately, starting with format competitors,
and uses channel-scoped outlier research (`channelIds` when supported) before
falling back to channel-scoped recent/popular video research only if available.
Evidence retains its group, and diagnostics report configured, resolved,
queried, researched, inspected-video, and successful-outlier counts by group.
Successful channel identity resolution is based on provider metadata or a
successful provider query; attempted but failed provider calls remain errors.
The lookback, video limit, and provider outlier-score threshold are configured by
`RITZZ_COMPETITOR_LOOKBACK_DAYS`, `RITZZ_COMPETITOR_VIDEO_LIMIT`, and
`RITZZ_OUTLIER_MIN_SCORE`. Provider outlier scores are preferred; views are
considered an outlier only against a supported baseline from that same
competitor channel. Raw views alone are not success evidence.
vidIQ credit exhaustion is reported explicitly as `INSUFFICIENT_CREDITS`;
paid fallback calls are skipped after that response. The observed outlier tool
costs 5 credits per group query, so confirm the account balance covers the
enabled group queries before running discovery.

Repeated patterns must cite at least two successful videos from at least two
competitor channels. A structured generator first extracts the audience
curiosity, then must select a concrete subject explicitly supported by cited
provider titles, topics, tags, or topics before proposing an original RITZZ
angle. Evidence matching tolerates word-order differences while requiring all
subject terms in the cited provider metadata. Broad essay premises and
subjects without matching evidence are rejected as `TOO_ABSTRACT`; near-copy
titles are rejected as `NEAR_DUPLICATE`. Candidate artifacts retain source
video IDs, concrete-subject citations, detected patterns, curiosity family,
and an explanation of the original angle.
Format-competitor evidence has primary weight, emerging-format evidence has
early-signal weight, and topic competitors remain a secondary subject signal.
Keyword research runs afterward only to enrich generated candidates. A
keyword-research provider error is recorded as `PROVIDER_ERROR`; it does not
discard competitor-derived candidates. Demand and competition remain
explicitly unavailable when vidIQ supplies no values. A failure of primary
competitor-video research is surfaced as `PROVIDER_ERROR` and does not get
disguised as zero results.
The existing configurable trending/rising/evergreen sources remain secondary
fallbacks when competitor-derived ideas do not fill the candidate pool or
competitors are not configured. Their results are labeled as secondary
provider evidence, never as competitor evidence. Short raw terms are seeds,
not finished titles, and can reach editorial assessment. The proposed title
must then pass specificity and RITZZ-fit checks; this does not relax evidence,
inventory, or editorial gates.

The final gate requires a concrete, specific subject, RITZZ-fit `PASS`,
editorial `PASS`, no blocking niche or inventory reason, no exact/near
duplicate, and a `RECOMMENDED` evidence and opportunity validation status.
Eligible candidates are diversified across curiosity families where the
evidence supports a mix. `REVIEW` and `FAIL` items are never promoted to fill
the list. Obvious fixtures, promotional trailer queries, temporary event
terms, and final titles that remain ambiguous are held or rejected. Bare
provider entities may reach editorial scoring as seeds, but must be turned
into a specific explanatory title to qualify. Human approval remains
mandatory; discovery does not select or publish a topic.

If fewer than four candidates pass, the run stops before topic approval and
reports the request, provider capabilities, per-source raw/unique/duplicate
counts, filter-stage counts, missing M7 state, and candidate exclusion reasons.
Both JSON and Markdown diagnostics are uploaded even on failure. `history`
remains the preferred discovery lens, not a requirement that every final topic
be a current history trend.
Diagnostics distinguish advertised tools from selected source tools and
include response schema summaries when a call yields no topic rows. MCP
tool-level errors are reported by category (such as access denied, quota
limit, or argument validation) without writing provider response values to
the artifact.

Competitor diagnostics show enabled channels and, by group, configured,
resolved, queried, researched channels, videos inspected, and successful
outliers; they also show patterns extracted, candidates generated,
demand-enriched candidates, fit/editorial pass counts, duplicate exclusions,
and final count. Each provider operation records its selected tool, status,
error category, and fallback behavior without logging raw provider error text
that could contain credentials.

Topic intelligence optionally reads the existing M7 inventory at
`projects/inventory.json` (override with `RITZZ_M7_INVENTORY_FILE`). It reads
existing analytics snapshots only; absent or invalid M7 data is reported and
does not stop discovery. Historical sample size/confidence and lexical topic
matches are evidence only and cannot override any hard gate. The human issue
approval and numbered selection mechanism are unchanged.

Editorial scoring separately assesses fit with RITZZ's static 2D
stickman/cartoon style, hard cuts, and one-word callouts. Topics that
fundamentally depend on footage or camera motion are held for review unless
they can be explained convincingly through static illustrations; format-fit
scores below 55 cannot pass the RITZZ-fit gate.

## Repository setup

Configure these GitHub repository secrets:

- `OPENAI_API_KEY`
- `VIDIQ_MCP_API_KEY`
- `ELEVENLABS_API_KEY`
- `RITZZ_VOICE_ID`
- `GOOGLE_CLIENT_SECRETS_B64`
- `GOOGLE_TOKEN_B64`

Create these GitHub environments and require reviewers for each environment:

- `ritzz-topic-approval`
- `ritzz-test-approval`
- `ritzz-video-approval`
- `ritzz-packaging-approval`

The workflow requires issue write permission so it can create the topic approval
issue. Only trusted repository collaborators should reply to that issue.

## Test-video rule

M8 and M9 runs are test runs. Generated or uploaded test videos must remain
private or unlisted. Public publication is disabled until the complete pipeline
and approval flow have passed validation. V1 is the first actual public video.

## Next M8 slices

- Add final public-publication approval and the V1-only public release path.
- Add scheduled M7 analytics collection after a test upload.
