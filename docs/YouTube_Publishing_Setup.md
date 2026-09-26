# YouTube Publishing Setup

The live provider is opt-in. Existing workflows continue to use `FakeYouTubeProvider` unless a `YouTubeProvider` instance is passed to `PublishingEngine`.

## Credentials

1. Create OAuth desktop credentials in Google Cloud for the YouTube Data API v3.
2. Keep the downloaded client secret outside source control, for example `secrets/youtube-client-secret.json`.
3. Choose a writable token path outside source control, for example `secrets/youtube-token.json`.
4. Install the Google packages from `requirements.txt`.

The first live publish opens the local OAuth consent flow and stores the refreshable token at the configured token path. Credentials are never embedded in project artifacts or source code.

## Provider wiring

```python
from modules.publishing import PublishingEngine, YouTubeProvider

provider = YouTubeProvider(
    credentials_file="secrets/youtube-client-secret.json",
    token_file="secrets/youtube-token.json",
)
engine = PublishingEngine(projects_dir, provider=provider)
```

Live upload still requires both `approval.json` and `schedule.json`. A scheduled upload is sent as a private video with YouTube's `publishAt` timestamp. No live upload is performed by the test suite.

Create the approval as a separate step after a human has reviewed the final video and packaging. `publish_project` will not create or overwrite approval; its `approved_by` value must match the identity in the existing approved artifact:

```python
engine.create_approval(project, approved=True, approved_by="reviewer")
result = engine.publish_project(
    project=project,
    video_file=final_video,
    title=selected_title,
    description=description,
    metadata=metadata,
    approved_by="reviewer",
    scheduled_for="2026-10-03T12:00:00+00:00",
)
```

This guards against an orchestration call implicitly approving its own upload. A live upload still requires deliberate use of the configured OAuth provider and is not run by offline tests.