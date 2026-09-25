"""Models and normalization for competitor and outlier research."""

from pydantic import BaseModel, Field


class OutlierVideo(BaseModel):
    video_id: str
    title: str
    channel_id: str | None = None
    channel_title: str | None = None
    channel_subscribers: int | None = None
    views: int | None = None
    breakout_score: float | None = None
    engagement_rate: float | None = None
    views_per_hour: float | None = None
    published_at: int | None = None
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    raw_evidence: dict = Field(default_factory=dict)


class MarketIntelligenceReport(BaseModel):
    query: str
    provider: str = "vidIQ MCP"
    retrieved_at: str
    outliers: list[OutlierVideo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def top_outliers(report: MarketIntelligenceReport, limit: int = 3) -> list[OutlierVideo]:
    """Return the strongest competitor examples without inventing a success rate."""
    return sorted(
        report.outliers,
        key=lambda item: (
            item.breakout_score is None,
            -(item.breakout_score or 0),
            item.views is None,
            -(item.views or 0),
        ),
    )[:limit]


def normalize_outlier(record: dict) -> OutlierVideo:
    return OutlierVideo(
        video_id=str(record.get("videoId", "")),
        title=str(record.get("videoTitle", "")).strip(),
        channel_id=record.get("channelId"),
        channel_title=record.get("channelTitle"),
        channel_subscribers=record.get("subscriberCount"),
        views=record.get("viewCount"),
        breakout_score=record.get("breakoutScore"),
        engagement_rate=record.get("engagementRate"),
        views_per_hour=record.get("vph"),
        published_at=record.get("videoPublishedAt"),
        tags=[str(item) for item in record.get("videoTags", [])],
        topics=[str(item) for item in record.get("videoTopics", [])],
        raw_evidence=record,
    )