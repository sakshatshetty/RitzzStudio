"""Models and normalization for competitor and outlier research."""

import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class CompetitorEvidence(BaseModel):
    channel: dict[str, str | int | float | None] = Field(default_factory=dict)
    video: dict[str, str | int | float | None] = Field(default_factory=dict)
    topic: str | None = None
    observed_performance: dict[str, int | float] = Field(default_factory=dict)
    baseline: dict[str, int | float | str] = Field(default_factory=dict)
    outlier_signal: dict[str, int | float | str | None] = Field(default_factory=dict)
    source: str
    collected_at: str


class CompetitorTopicPattern(BaseModel):
    topic: str
    video_count: int
    channel_count: int
    channels: list[str] = Field(default_factory=list)
    video_ids: list[str] = Field(default_factory=list)


class OutlierVideo(BaseModel):
    video_id: str
    title: str
    topic: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    channel_subscribers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    baseline_views: float | None = None
    baseline_method: str | None = None
    baseline_sample_size: int | None = None
    relative_performance: float | None = None
    outlier_signal: str | None = None
    breakout_score: float | None = None
    engagement_rate: float | None = None
    views_per_hour: float | None = None
    published_at: int | str | None = None
    duration: str | None = None
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    raw_evidence: dict = Field(default_factory=dict)


class MarketIntelligenceReport(BaseModel):
    query: str
    provider: str = "vidIQ MCP"
    retrieved_at: str
    competitor_topic_performance_available: bool = False
    channels: list[dict[str, str | int | float | None]] = Field(default_factory=list)
    outliers: list[OutlierVideo] = Field(default_factory=list)
    topic_patterns: list[CompetitorTopicPattern] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def top_outliers(report: MarketIntelligenceReport, limit: int = 3) -> list[OutlierVideo]:
    """Return provider-scored examples without treating raw views as success."""
    return sorted(
        report.outliers,
        key=lambda item: (
            item.breakout_score is None,
            -(item.breakout_score or 0),
            item.channel_title or "",
            item.title,
        ),
    )[:limit]


def normalize_outlier(
    record: dict[str, Any],
    *,
    baseline_views: float | None = None,
    baseline_method: str | None = None,
    baseline_sample_size: int | None = None,
) -> OutlierVideo:
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
        for key, value in record.items()
    }

    def get(*keys: str) -> Any:
        for key in keys:
            value = normalized.get(re.sub(r"[^a-z0-9]", "", key.casefold()))
            if value is not None:
                return value
        return None

    views = _number(get("viewCount", "views", "videoViews"))
    provider_baseline = _number(
        get(
            "channelBaselineViews",
            "baselineViews",
            "channelAverageViews",
            "averageViews",
            "avgViews",
            "typicalViews",
        )
    )
    if provider_baseline is not None:
        baseline_views = provider_baseline
        baseline_method = "vidIQ provider baseline"
    relative_performance = (
        views / baseline_views
        if views is not None and baseline_views is not None and baseline_views > 0
        else None
    )
    if relative_performance is None:
        outlier_signal = None
    elif relative_performance >= 2:
        outlier_signal = "strong_outlier"
    elif relative_performance > 1:
        outlier_signal = "above_baseline"
    else:
        outlier_signal = "at_or_below_baseline"

    topics = get("videoTopics", "topics")
    if isinstance(topics, str):
        topics = [topics]
    if not isinstance(topics, list):
        topics = []
    topics = [str(item).strip() for item in topics if str(item).strip()]
    title = str(get("videoTitle", "title", "titleText") or "").strip()
    topic = str(get("topic", "topicName", "keyword") or (topics[0] if topics else title)).strip() or None
    return OutlierVideo(
        video_id=str(get("videoId", "id") or ""),
        title=title,
        topic=topic,
        channel_id=_optional_string(get("channelId", "channel_id")),
        channel_title=_optional_string(get("channelTitle", "channelName", "channel")),
        channel_subscribers=_integer(get("subscriberCount", "channelSubscribers", "subscribers")),
        views=_integer(get("viewCount", "views", "videoViews")),
        likes=_integer(get("likeCount", "likes")),
        comments=_integer(get("commentCount", "comments")),
        baseline_views=baseline_views,
        baseline_method=baseline_method,
        baseline_sample_size=baseline_sample_size,
        relative_performance=relative_performance,
        outlier_signal=outlier_signal,
        breakout_score=_number(get("breakoutScore", "breakout_score")),
        engagement_rate=_number(get("engagementRate", "engagement_rate")),
        views_per_hour=_number(get("vph", "viewsPerHour", "views_per_hour")),
        published_at=_timestamp(get("videoPublishedAt", "publishedAt", "published_at")),
        duration=_optional_string(get("videoDuration", "duration")),
        tags=_string_list(get("videoTags", "tags")),
        topics=topics,
        raw_evidence=record,
    )


def build_market_intelligence_report(
    query: str,
    records: list[dict[str, Any]],
    *,
    channels: list[dict[str, Any]] | None = None,
    source: str = "vidiq_outliers",
    performance_tool_available: bool = True,
    warnings: list[str] | None = None,
) -> MarketIntelligenceReport:
    """Normalize provider video records and compute only supported baselines."""
    channel_views: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for index, record in enumerate(records):
        preliminary = normalize_outlier(record)
        channel_key = preliminary.channel_id or preliminary.channel_title
        if channel_key and preliminary.views is not None:
            channel_views[channel_key].append((index, preliminary.views))

    outliers = []
    for index, record in enumerate(records):
        preliminary = normalize_outlier(record)
        channel_key = preliminary.channel_id or preliminary.channel_title or ""
        views = channel_views.get(channel_key, [])
        baseline_views = preliminary.baseline_views
        sample_size = None
        if baseline_views is None and len(views) >= 3:
            peer_views = [value for peer_index, value in views if peer_index != index]
            if len(peer_views) >= 2:
                baseline_views = float(statistics.median(peer_views))
                sample_size = len(peer_views)
        item = normalize_outlier(
            record,
            baseline_views=baseline_views,
            baseline_method=(
                "median of returned same-channel videos"
                if baseline_views is not None and preliminary.baseline_views is None
                else preliminary.baseline_method
            ),
            baseline_sample_size=sample_size or preliminary.baseline_sample_size,
        )
        outliers.append(item)

    report_warnings = list(warnings or [])
    has_performance = any(
        item.title
        and (
            item.views is not None
            or item.likes is not None
            or item.comments is not None
            or item.breakout_score is not None
            or item.engagement_rate is not None
            or item.views_per_hour is not None
        )
        for item in outliers
    )
    if performance_tool_available and not has_performance:
        report_warnings.append(
            "vidIQ exposed competitor-video results but no usable performance metrics; "
            "competitor topic performance is unavailable for this response."
        )
    elif not performance_tool_available:
        report_warnings.append(
            "The configured vidIQ MCP server does not expose competitor-video performance data."
        )
    return MarketIntelligenceReport(
        query=query,
        provider=source,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        competitor_topic_performance_available=performance_tool_available and has_performance,
        channels=_normalize_channels(channels or [], outliers),
        outliers=outliers,
        topic_patterns=_topic_patterns(outliers),
        warnings=report_warnings,
    )


def competitor_evidence_for_video(video: OutlierVideo, source: str, collected_at: str) -> CompetitorEvidence:
    observed = {
        key: value
        for key, value in {
            "views": video.views,
            "likes": video.likes,
            "comments": video.comments,
            "breakout_score": video.breakout_score,
            "engagement_rate": video.engagement_rate,
            "views_per_hour": video.views_per_hour,
        }.items()
        if value is not None
    }
    baseline: dict[str, int | float | str] = {}
    if video.baseline_views is not None:
        baseline["views"] = video.baseline_views
        baseline["method"] = video.baseline_method or "provider baseline"
        if video.baseline_sample_size is not None:
            baseline["sample_size"] = video.baseline_sample_size
    signal: dict[str, int | float | str | None] = {}
    if video.relative_performance is not None:
        signal = {
            "metric": "video_views / competitor_channel_baseline_views",
            "ratio": round(video.relative_performance, 3),
            "strong_outlier_threshold": 2.0,
            "classification": video.outlier_signal,
        }
    elif video.breakout_score is not None:
        signal = {
            "metric": "vidIQ breakout score",
            "value": video.breakout_score,
            "classification": "provider_score_only",
        }
    channel = {
        key: value
        for key, value in {
            "id": video.channel_id,
            "name": video.channel_title,
            "subscribers": video.channel_subscribers,
        }.items()
        if value is not None
    }
    video_data = {
        key: value
        for key, value in {
            "id": video.video_id or None,
            "title": video.title or None,
            "published_at": video.published_at,
            "duration": video.duration,
        }.items()
        if value is not None
    }
    return CompetitorEvidence(
        channel=channel,
        video=video_data,
        topic=video.topic,
        observed_performance=observed,
        baseline=baseline,
        outlier_signal=signal,
        source=source,
        collected_at=collected_at,
    )


def relevant_competitor_evidence(
    topic: str,
    report: MarketIntelligenceReport,
) -> list[CompetitorEvidence]:
    """Attach only video evidence with a meaningful lexical topic match."""
    candidate_terms = set(_topic_key(topic).split())
    if not candidate_terms:
        return []
    collected_at = report.retrieved_at
    matched = []
    for video in report.outliers:
        competitor_terms = set(_topic_key(video.topic or video.title).split())
        overlap = candidate_terms & competitor_terms
        required_overlap = min(2, len(candidate_terms))
        if len(overlap) >= required_overlap and len(overlap) / len(candidate_terms) >= 0.5:
            matched.append(
                competitor_evidence_for_video(
                    video,
                    f"{report.provider} vidiq_outliers",
                    collected_at,
                )
            )
    return matched


def relevant_competitor_patterns(
    topic: str,
    report: MarketIntelligenceReport,
) -> list[CompetitorTopicPattern]:
    candidate_terms = set(_topic_key(topic).split())
    if not candidate_terms:
        return []
    matches = []
    for pattern in report.topic_patterns:
        pattern_terms = set(_topic_key(pattern.topic).split())
        overlap = candidate_terms & pattern_terms
        required_overlap = min(2, len(candidate_terms))
        if len(overlap) >= required_overlap and len(overlap) / len(candidate_terms) >= 0.5:
            matches.append(pattern)
    return matches


def _topic_patterns(outliers: list[OutlierVideo]) -> list[CompetitorTopicPattern]:
    grouped: dict[str, list[OutlierVideo]] = defaultdict(list)
    labels: dict[str, str] = {}
    for video in outliers:
        if not video.topic:
            continue
        key = _topic_key(video.topic)
        if key:
            labels.setdefault(key, video.topic)
            grouped[key].append(video)
    patterns = [
        CompetitorTopicPattern(
            topic=labels[key],
            video_count=len(videos),
            channel_count=len({video.channel_id or video.channel_title for video in videos}),
            channels=sorted({
                video.channel_title or video.channel_id or "unknown"
                for video in videos
            }),
            video_ids=sorted({video.video_id for video in videos if video.video_id}),
        )
        for key, videos in grouped.items()
        if len(videos) > 1
    ]
    return sorted(patterns, key=lambda item: (-item.channel_count, -item.video_count, item.topic.casefold()))


def _normalize_channels(
    records: list[dict[str, Any]],
    outliers: list[OutlierVideo],
) -> list[dict[str, str | int | float | None]]:
    result: dict[str, dict[str, str | int | float | None]] = {}
    for record in records:
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
            for key, value in record.items()
        }
        channel_id = normalized.get("channelid") or normalized.get("id")
        name = normalized.get("channeltitle") or normalized.get("channelname") or normalized.get("name") or normalized.get("title")
        if not channel_id and not name:
            continue
        key = str(channel_id or name)
        result[key] = {
            "id": str(channel_id) if channel_id is not None else None,
            "name": str(name) if name is not None else None,
            "subscribers": _integer(normalized.get("subscribercount") or normalized.get("subscribers")),
        }
    for item in outliers:
        key = item.channel_id or item.channel_title
        if key and key not in result:
            result[key] = {
                "id": item.channel_id,
                "name": item.channel_title,
                "subscribers": item.channel_subscribers,
            }
    return [result[key] for key in sorted(result)]


def _topic_key(topic: str) -> str:
    ignored = {"a", "an", "and", "are", "do", "does", "for", "how", "in", "is", "it", "of", "the", "to", "what", "why"}
    return " ".join(
        token for token in re.findall(r"[a-z0-9]+", topic.casefold())
        if token not in ignored
    )


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            number = float(value.replace(",", "").replace("%", "").strip())
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    if isinstance(number, float):
        return int(number) if number.is_integer() else None
    return number


def _timestamp(value: Any) -> int | str | None:
    if isinstance(value, str):
        return value.strip() or None
    return _integer(value)


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None and str(value).strip() else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []