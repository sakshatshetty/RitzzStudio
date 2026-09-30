"""Generate original RITZZ ideas from repeated competitor-video successes."""

import json
import re
from difflib import SequenceMatcher

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY, OPENAI_MODEL
from config.settings import RITZZ_OUTLIER_MIN_SCORE
from modules.topic_intelligence.market_intelligence import (
    CompetitorTopicPattern,
    MarketIntelligenceReport,
    OutlierVideo,
    competitor_evidence_for_video,
    is_successful_outlier_video,
)
from modules.topic_intelligence.models import OpportunityCandidate, StoryType

_STOP_WORDS = {
    "a", "an", "and", "are", "did", "do", "does", "for", "how", "in", "is",
    "it", "of", "on", "or", "the", "to", "was", "were", "what", "when",
    "where", "which", "who", "why", "with",
}


class CompetitorPatternProposal(BaseModel):
    observed_pattern: str = Field(min_length=12)
    topic_category: str = Field(min_length=2)
    curiosity_type: str = Field(min_length=2)
    core_question: str = Field(min_length=8)
    subject_entities: list[str] = Field(default_factory=list)
    why_interesting: str = Field(min_length=8)
    evidence_ids: list[str] = Field(min_length=2)


class OriginalTopicProposal(BaseModel):
    pattern_index: int = Field(ge=0)
    topic: str = Field(min_length=12)
    angle: str = Field(min_length=12)
    story_type: StoryType = "OTHER"
    differentiation_angle: str = Field(min_length=12)
    why_interesting: str = Field(min_length=8)


class CompetitorOpportunityBatch(BaseModel):
    patterns: list[CompetitorPatternProposal]
    opportunities: list[OriginalTopicProposal]


class CompetitorOpportunityGenerator:
    """Use observed cross-channel patterns to propose, never select, RITZZ topics."""

    prompt_version = "ritzz-competitor-opportunities-v1"

    def __init__(self, client=None) -> None:
        self.client = client
        self.model_name = OPENAI_MODEL

    def generate(
        self,
        report: MarketIntelligenceReport,
        *,
        candidate_limit: int = 8,
    ) -> tuple[list[OpportunityCandidate], list[CompetitorTopicPattern], dict[str, int]]:
        videos = [
            video for video in report.outliers
            if video.title and is_successful_outlier_video(video, RITZZ_OUTLIER_MIN_SCORE)
        ]
        evidence_by_id: dict[str, OutlierVideo] = {}
        serialized_videos = []
        for index, video in enumerate(videos):
            evidence_id = video.video_id or f"provider-record-{index + 1}"
            evidence_by_id.setdefault(evidence_id, video)
            serialized_videos.append({
                "evidence_id": evidence_id,
                "channel": video.channel_title or video.channel_id,
                "video_title": video.title,
                "underlying_topic_from_provider": video.topic,
                "topic_tags": video.topics,
                "published_at": video.published_at,
                "observed_performance": {
                    "views": video.views,
                    "views_per_hour": video.views_per_hour,
                    "breakout_score": video.breakout_score,
                    "relative_performance": video.relative_performance,
                    "baseline_views": video.baseline_views,
                    "baseline_method": video.baseline_method,
                },
            })
        diagnostics = {
            "videos_inspected": len(report.outliers),
            "successful_outlier_videos": len(videos),
            "topic_patterns_extracted": 0,
            "generated_candidates": 0,
            "rejected_copied_angles": 0,
        }
        distinct_channels = {
            video.channel_id or video.channel_title
            for video in videos
            if video.channel_id or video.channel_title
        }
        if len(videos) < 2 or len(distinct_channels) < 2:
            return [], [], diagnostics

        if self.client is None:
            self.client = OpenAI(api_key=OPENAI_API_KEY)
        response = self.client.responses.parse(
            model=self.model_name,
            input=[
                {"role": "system", "content": self._system_prompt(candidate_limit)},
                {
                    "role": "user",
                    "content": json.dumps(serialized_videos, ensure_ascii=True),
                },
            ],
            text_format=CompetitorOpportunityBatch,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no structured competitor-topic patterns.")

        patterns = self._validated_patterns(parsed.patterns, evidence_by_id)
        diagnostics["topic_patterns_extracted"] = len(patterns)
        candidates, rejected = self._validated_candidates(
            parsed.opportunities,
            patterns,
            evidence_by_id,
            candidate_limit,
            report.retrieved_at,
        )
        diagnostics["generated_candidates"] = len(candidates)
        diagnostics["rejected_copied_angles"] = rejected
        report.topic_patterns = patterns
        report.successful_outlier_count = len(videos)
        return candidates, patterns, diagnostics

    @staticmethod
    def _system_prompt(candidate_limit: int) -> str:
        return (
            "You are the RITZZ competitor-topic analyst. RITZZ is a general-audience "
            "English mixed-curiosity channel making educational, story-driven explainers. "
            "Analyze only the supplied successful videos. First identify patterns supported "
            "by at least two distinct videos from at least two distinct competitor channels. "
            "Cite each pattern with evidence_ids exactly from the input. Do not rank channels. "
            "Then create no more than " + str(candidate_limit) + " independently framed "
            "RITZZ topic opportunities from those patterns. Do not copy or paraphrase any "
            "competitor title. Move to a broader curiosity, mechanism, origin, consequence, "
            "or surprising comparison and express an original explanatory question. Each "
            "opportunity must reference one valid pattern index, explain the distinct angle, "
            "and be suitable for a researchable visual explainer. Never invent demand, "
            "competition, view counts, or competitor evidence. Return no opportunity when "
            "the source videos do not support a meaningfully distinct idea."
        )

    @staticmethod
    def _validated_patterns(
        proposals: list[CompetitorPatternProposal],
        evidence_by_id: dict[str, OutlierVideo],
    ) -> list[CompetitorTopicPattern]:
        patterns = []
        for proposal in proposals:
            evidence_ids = list(dict.fromkeys(
                evidence_id
                for evidence_id in proposal.evidence_ids
                if evidence_id in evidence_by_id
            ))
            videos = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
            channels = {
                video.channel_id or video.channel_title
                for video in videos
                if video.channel_id or video.channel_title
            }
            if len(evidence_ids) < 2 or len(channels) < 2:
                continue
            patterns.append(CompetitorTopicPattern(
                topic=proposal.core_question,
                video_count=len(evidence_ids),
                channel_count=len(channels),
                channels=sorted({
                    video.channel_title or video.channel_id or "unknown"
                    for video in videos
                }),
                video_ids=sorted({
                    video.video_id for video in videos if video.video_id
                }),
                observed_pattern=proposal.observed_pattern,
                topic_category=proposal.topic_category,
                curiosity_type=proposal.curiosity_type,
                core_question=proposal.core_question,
                subject_entities=proposal.subject_entities,
                why_interesting=proposal.why_interesting,
                evidence_refs=evidence_ids,
            ))
        return patterns

    @staticmethod
    def _validated_candidates(
        proposals: list[OriginalTopicProposal],
        patterns: list[CompetitorTopicPattern],
        evidence_by_id: dict[str, OutlierVideo],
        candidate_limit: int,
        collected_at: str,
    ) -> tuple[list[OpportunityCandidate], int]:
        candidates = []
        rejected_copies = 0
        seen_topics: set[str] = set()
        for proposal_index, proposal in enumerate(proposals):
            if len(candidates) >= candidate_limit:
                break
            if not 0 <= proposal.pattern_index < len(patterns):
                continue
            pattern = patterns[proposal.pattern_index]
            topic = proposal.topic.strip()
            topic_key = _normalized_topic(topic)
            if not topic_key or topic_key in seen_topics:
                continue
            supporting_videos = [
                evidence_by_id[video_id]
                for video_id in pattern.evidence_refs
                if video_id in evidence_by_id
            ]
            titles = [video.title for video in supporting_videos if video.title]
            if any(_is_title_copy(topic, title) for title in titles):
                rejected_copies += 1
                continue
            seen_topics.add(topic_key)
            competitor_evidence = [
                competitor_evidence_for_video(
                    video,
                    "vidIQ MCP competitor outliers",
                    collected_at,
                )
                for video in supporting_videos
            ]
            candidates.append(OpportunityCandidate(
                candidate_id=f"competitor-{proposal_index + 1:03d}",
                topic=topic,
                proposed_title=topic,
                angle=proposal.angle,
                why_interesting=proposal.why_interesting,
                primary_keyword=topic,
                opportunity_type="TREND_TO_EVERGREEN",
                provider="vidIQ MCP competitor research",
                discovery_sources=["competitor-topic-pattern"],
                competitor_topic_performance_available=True,
                competitor_evidence=competitor_evidence,
                competitor_topic_patterns=[pattern],
                ritzz_differentiation_angle=proposal.differentiation_angle,
                observed_pattern=pattern.observed_pattern,
                raw_evidence={
                    "pattern_index": proposal.pattern_index,
                    "pattern": pattern.model_dump(mode="json"),
                    "supporting_video_ids": pattern.video_ids,
                },
                ritzz_fit={
                    "fit_status": "REVIEW",
                    "story_type": proposal.story_type,
                    "reason": "Competitor-derived idea awaits independent RITZZ-fit validation.",
                },
            ))
        return candidates, rejected_copies


def _normalized_topic(topic: str) -> str:
    return " ".join(
        token
        for token in re.findall(r"[a-z0-9]+", topic.casefold())
        if token not in _STOP_WORDS
    )


def _is_title_copy(candidate_topic: str, competitor_title: str) -> bool:
    candidate_key = _normalized_topic(candidate_topic)
    title_key = _normalized_topic(competitor_title)
    if not candidate_key or not title_key:
        return False
    candidate_tokens = set(candidate_key.split())
    title_tokens = set(title_key.split())
    jaccard = len(candidate_tokens & title_tokens) / len(candidate_tokens | title_tokens)
    similarity = SequenceMatcher(None, candidate_key, title_key).ratio()
    return jaccard >= 0.7 or similarity >= 0.82
