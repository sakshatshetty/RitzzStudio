# GitHub Actions Pipeline

RITZZ video runs are started from the GitHub Actions web interface. Normal video
production does not require a local command-line command.

## Current workflow

Workflow file: `.github/workflows/ritzz-pipeline.yml`

The current M8 slice performs these steps:

When starting a run, the GitHub form provides `Discovery mode`, `Test run`,
`Target video duration in minutes`, and `Minimum allowed video duration in
minutes`. Both duration fields default to 8 minutes, and the minimum cannot
exceed the target.

Before tests or external providers run, the workflow validates that all required
secrets are present and that the Google client and token secrets decode to valid
OAuth JSON. This preflight makes no provider API calls, so it does not consume
quota or prove that a key has live service permission; provider failures still
stop their individual stage.

1. Run focused pipeline regression tests.
2. Discover exactly four trending or evergreen candidates.
3. Publish the candidates in a GitHub issue and workflow artifact.
4. Wait for a trusted collaborator to reply with `1`, `2`, `3`, or `4`.
5. Pause at the protected topic-approval environment.
6. Pause at the protected test-approval environment.
7. Run the existing Research -> Outline -> Script content workflow.
8. Upload the generated project artifacts to the GitHub Actions run.
9. Use the selected vidIQ candidate to inform titles, tags, description framing,
   and the thumbnail brief; persist the source report and candidate context.
10. Generate and validate ElevenLabs narration with character alignment.
11. Build the narrative and audio-timed static storyboard.
12. Render the test video and run deterministic technical QA.
13. Pause for human video review and approval.
14. Pause for packaging approval.
15. Upload the test video privately through YouTube OAuth.
16. Keep the current run marked as a test run; public publication remains
   disabled.

Topic duplicate prevention reads the durable repository inventory at
`data/content_inventory.json`. Test runs do not write to this file and therefore
do not reserve or permanently exclude their selected topics. A future approved
V1 release will update the inventory with the final topic and publication data.

For pipeline discovery, the provider targets 30 distinct candidates by
default (configurable from 15 to 30 with `RITZZ_CANDIDATE_POOL_TARGET`). It
starts with the requested category/timeframe, then attempts supported
broader-timeframe, rising-demand, evergreen, long-tail, competitor/outlier, and
unscoped discovery. Fallback stages are configurable with
`RITZZ_DISCOVERY_FALLBACK_STAGES`. Related keywords/questions are used only
when present in provider results. Unsupported or failed sources are recorded
in diagnostics and do not stop later sources.

The final gate requires RITZZ-fit `PASS`, editorial `PASS`, no blocking niche
or inventory reason, no exact/near duplicate, and a `RECOMMENDED` evidence and
opportunity validation status. `REVIEW` and `FAIL` items are never promoted to
fill the list. Obvious fixtures, promotional trailer queries, temporary event
terms, and ambiguous bare entities are held or rejected before editorial model
scoring; a supported related question may independently qualify as an
explanatory story.

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

Competitor channel groups are configured in `config/competitors.json`. The
checked-in registry is intentionally empty; no competitor names are fabricated.
Per-channel requests are made only if the advertised vidIQ outlier schema
supports a channel selector. Otherwise topic-level competitor discovery is
used and the limitation is reported. Raw views alone do not create an outlier
or repeated-success pattern; provider outlier scores or channel-relative
performance are required.

Topic intelligence optionally reads the existing M7 inventory at
`projects/inventory.json` (override with `RITZZ_M7_INVENTORY_FILE`). It reads
existing analytics snapshots only; absent or invalid M7 data is reported and
does not stop discovery. Historical sample size/confidence and lexical topic
matches are evidence only and cannot override any hard gate. The human issue
approval and numbered selection mechanism are unchanged.

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
