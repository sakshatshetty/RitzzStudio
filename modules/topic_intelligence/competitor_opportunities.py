"""Generate original RITZZ ideas from repeated competitor-video successes."""

import json
import re
from difflib import SequenceMatcher
from typing import Any

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
from modules.topic_intelligence.models import (
    RITZZ_CHANNEL_PROFILE,
    OpportunityCandidate,
    RitzzFitResult,
    StoryType,
)

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
    evidence_ids: list[str] = Field(min_length=1)


class OriginalTopicProposal(BaseModel):
    pattern_index: int = Field(ge=0)
    topic: str = Field(min_length=12)
    concrete_subject: str = Field(min_length=3)
    subject_evidence_ids: list[str] = Field(min_length=1)
    search_concepts: list[str] = Field(default_factory=list, max_length=3)
    angle: str = Field(min_length=12)
    story_type: StoryType = "OTHER"
    curiosity_family: str = Field(min_length=2)
    differentiation_angle: str = Field(min_length=12)
    originality_reason: str = Field(min_length=12)
    why_interesting: str = Field(min_length=8)


class CompetitorOpportunityBatch(BaseModel):
    patterns: list[CompetitorPatternProposal]
    opportunities: list[OriginalTopicProposal]


class CompetitorOpportunityGenerator:
    """Use observed cross-channel patterns to propose, never select, RITZZ topics."""

    prompt_version = "ritzz-competitor-opportunities-v4"

    def __init__(self, client=None) -> None:
        self.client = client
        self.model_name = OPENAI_MODEL

    def generate(
        self,
        report: MarketIntelligenceReport,
        *,
        candidate_limit: int = 8,
    ) -> tuple[list[OpportunityCandidate], list[CompetitorTopicPattern], dict[str, Any]]:
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
                "competitor_group": video.channel_group,
                "competitor_priority": video.channel_priority,
                "competitor_role": video.channel_role,
                "video_title": video.title,
                "underlying_topic_from_provider": video.topic,
                "tags": video.tags,
                "topics": video.topics,
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
            "gpt_topic_ideas_returned": 0,
            "topic_patterns_extracted": 0,
            "generated_candidates": 0,
            "rejected_copied_angles": 0,
            "candidate_rejections": [],
            "candidate_validation": [],
        }
        distinct_channels = {
            video.channel_id or video.channel_title
            for video in videos
            if video.channel_id or video.channel_title
        }
        if not videos or not distinct_channels:
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

        diagnostics["gpt_topic_ideas_returned"] = len(parsed.opportunities)
        diagnostics["gpt_proposals"] = [
            {
                "topic": proposal.topic,
                "pattern_index": proposal.pattern_index,
                "concrete_subject": proposal.concrete_subject,
                "subject_evidence_ids": proposal.subject_evidence_ids,
                "search_concepts": self._proposal_search_concepts(proposal),
            }
            for proposal in parsed.opportunities
        ]
        patterns = self._validated_patterns(parsed.patterns, evidence_by_id)
        diagnostics["topic_patterns_extracted"] = len(patterns)
        candidates, rejected, rejection_details = self._validated_candidates(
            parsed.opportunities,
            patterns,
            evidence_by_id,
            candidate_limit,
            report.retrieved_at,
        )
        diagnostics["generated_candidates"] = len(candidates)
        diagnostics["rejected_copied_angles"] = rejected
        diagnostics["candidate_rejections"] = rejection_details
        report.topic_patterns = patterns
        report.successful_outlier_count = len(videos)
        return candidates, patterns, diagnostics

    @staticmethod
    def _system_prompt(candidate_limit: int) -> str:
        return (
            "You are the RITZZ competitor-topic analyst. Channel profile: "
            + RITZZ_CHANNEL_PROFILE
            + " RITZZ makes English-language, story-driven explainers. "
            "Analyze only the supplied successful videos. Identify repeated patterns when "
            "multiple distinct videos and channels support them. A one-video signal may be "
            "reported as a tentative low-confidence pattern, but never describe it as repeated. "
            "Cite each pattern with evidence_ids exactly from the input. Do not rank channels. "
            "Treat format competitors, topic competitors, and emerging-format channels as "
            "distinct evidence groups. Format competitors primarily inform storytelling, "
            "curiosity, title, and visual patterns; topic competitors primarily inform "
            "subject/question demand; emerging-format channels inform tentative early "
            "patterns. A topic competitor must never override RITZZ visual compatibility. "
            "Use configured priority as context, not as a ranking of channels. "
            "Never rank competitors as best or worst. "
            "Use this evidence chain: successful competitor video -> underlying audience "
            "curiosity -> a concrete subject explicitly present in the supplied video title, "
            "topic, or tags -> an original RITZZ explanatory angle. Do not jump from an "
            "abstract pattern directly to a final title. Never invent a subject, event, "
            "phenomenon, source, or fact. Every opportunity must name one concrete_subject "
            "and cite subject_evidence_ids containing only supplied evidence IDs whose title, "
            "topic, or tags explicitly support that subject. The final topic/title itself "
            "must name that concrete subject and make the question understandable on its own. "
            "Reject broad essay premises, school-essay topics, generic categories, and titles "
            "that could describe many unrelated videos. If no evidenced concrete subject "
            "supports an original idea, return no opportunity. "
            "Generate approximately 8–12 original candidate ideas, and validate "
            "only ideas that pass the evidence and originality rules. Build an "
            "internal pool targeting " + str(candidate_limit) + " concrete "
            "opportunities, not merely four. Reach that target only when the evidence "
            "supports it; never relax a quality gate to fill the pool. Do not copy or paraphrase competitor titles, "
            "and do not reuse the same subject with a trivial wording change. Include a "
            "specific curiosity_family, original angle, and originality_reason explaining "
            "the substantive difference from cited videos. Format competitors are the primary "
            "signal (weight 1.0); emerging-format channels are early signals (weight 0.7); "
            "topic competitors are secondary subject signals (weight 0.5). Format competitors "
            "inform storytelling/visual opportunities, not factual truth. Build diverse ideas "
            "within the RITZZ ancient-human, ancient-civilization, ancient-life, survival, "
            "engineering, and history-curiosity niche. Prefer specific questions about how "
            "people in the past lived, survived, built, traveled, worked, ate, or solved "
            "problems. Do not propose current news, current disasters, sports, or unrelated "
            "general curiosity. For every opportunity, choose a zero-based pattern_index; "
            "set concrete_subject to a concrete name or phrase that appears in the final "
            "topic and in at least one cited supplied video title, topic, tag, or topic label. "
            "subject_evidence_ids must cite one or more supplied evidence_ids that explicitly "
            "support that concrete subject; they may cite any supplied video, not only the "
            "pattern's own evidence_ids. Include 1–3 concise underlying vidIQ search_concepts "
            "for the same opportunity (for example, 'ancient humans winter survival'), not "
            "a copy of the creative title. Favor subjects that can be explained with static "
            "illustrations, objects, maps, diagrams, or timelines. Never invent demand, "
            "competition, view counts, or competitor evidence."
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
            if not evidence_ids or not channels:
                continue
            confidence = (
                "HIGH" if len(evidence_ids) >= 3 and len(channels) >= 2
                else "MEDIUM" if len(evidence_ids) >= 2 and len(channels) >= 2
                else "LOW"
            )
            patterns.append(CompetitorTopicPattern(
                topic=proposal.core_question,
                video_count=len(evidence_ids),
                channel_count=len(channels),
                channels=sorted({
                    video.channel_title or video.channel_id or "unknown"
                    for video in videos
                }),
                channel_groups=sorted({
                    video.channel_group
                    for video in videos
                    if video.channel_group
                }),
                confidence=confidence,
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
                signal_weight=_competitor_signal_weight(videos),
            ))
        return patterns

    @staticmethod
    def _validated_candidates(
        proposals: list[OriginalTopicProposal],
        patterns: list[CompetitorTopicPattern],
        evidence_by_id: dict[str, OutlierVideo],
        candidate_limit: int,
        collected_at: str,
    ) -> tuple[list[OpportunityCandidate], int, list[dict[str, Any]]]:
        candidates = []
        rejected_copies = 0
        seen_topics: set[str] = set()
        rejection_details: list[dict[str, Any]] = []

        def rejection_detail(
            proposal: OriginalTopicProposal,
            code: str,
            reason: str,
            *,
            pattern: CompetitorTopicPattern | None = None,
        ) -> dict[str, Any]:
            return {
                "topic": proposal.topic,
                "code": code,
                "reason": reason,
                "pattern_index": proposal.pattern_index,
                "concrete_subject": proposal.concrete_subject,
                "subject_evidence_ids": list(proposal.subject_evidence_ids),
                "search_concepts": CompetitorOpportunityGenerator._proposal_search_concepts(
                    proposal
                ),
                "selected_pattern_evidence_ids": (
                    list(pattern.evidence_refs) if pattern is not None else []
                ),
                "cited_subject_evidence": [
                    {
                        "evidence_id": evidence_id,
                        "title": evidence_by_id[evidence_id].title,
                        "topic": evidence_by_id[evidence_id].topic,
                        "tags": evidence_by_id[evidence_id].tags,
                        "topics": evidence_by_id[evidence_id].topics,
                    }
                    for evidence_id in proposal.subject_evidence_ids
                    if evidence_id in evidence_by_id
                ],
                "validation_result": "NOT_RUN",
                "rejection_reason": reason,
                "vidiq_query": None,
                "raw_vidiq_response": None,
                "normalized_vidiq_evidence": None,
            }

        for proposal_index, proposal in enumerate(proposals):
            if len(candidates) >= candidate_limit:
                break
            if not 0 <= proposal.pattern_index < len(patterns):
                rejection_details.append(rejection_detail(
                    proposal,
                    "OTHER_HARD_FILTER",
                    "Proposal referenced a pattern that did not pass evidence validation.",
                ))
                continue
            pattern = patterns[proposal.pattern_index]
            topic = proposal.topic.strip()
            topic_key = _normalized_topic(topic)
            if not topic_key or topic_key in seen_topics:
                rejection_details.append(rejection_detail(
                    proposal,
                    "DUPLICATE",
                    "Topic was empty or duplicated an earlier generated candidate.",
                    pattern=pattern,
                ))
                continue
            supporting_videos = [
                evidence_by_id[video_id]
                for video_id in pattern.evidence_refs
                if video_id in evidence_by_id
            ]
            subject_evidence_ids = list(dict.fromkeys(proposal.subject_evidence_ids))
            if not subject_evidence_ids or any(
                evidence_id not in evidence_by_id
                for evidence_id in subject_evidence_ids
            ):
                rejection_details.append(rejection_detail(
                    proposal,
                    "TOO_ABSTRACT",
                    "Concrete subject citations were missing or did not identify returned competitor evidence.",
                    pattern=pattern,
                ))
                continue
            subject_sources = [
                evidence_by_id[evidence_id]
                for evidence_id in subject_evidence_ids
            ]
            subject_reason = _concrete_subject_issue(
                topic,
                proposal.concrete_subject,
                subject_sources,
            )
            if subject_reason:
                rejection_details.append(rejection_detail(
                    proposal,
                    "TOO_ABSTRACT",
                    subject_reason,
                    pattern=pattern,
                ))
                continue
            titles = [video.title for video in supporting_videos if video.title]
            if any(_is_title_copy(topic, title) for title in titles):
                rejected_copies += 1
                rejection_details.append(rejection_detail(
                    proposal,
                    "NEAR_DUPLICATE",
                    "Candidate title is too similar to a cited competitor title.",
                    pattern=pattern,
                ))
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
                curiosity_hook=proposal.why_interesting,
                primary_keyword=topic,
                opportunity_type="TREND_TO_EVERGREEN",
                provider="vidIQ MCP competitor research",
                discovery_sources=["competitor-topic-pattern"],
                competitor_topic_performance_available=True,
                competitor_evidence=competitor_evidence,
                competitor_topic_patterns=[pattern],
                ritzz_differentiation_angle=proposal.differentiation_angle,
                observed_pattern=pattern.observed_pattern,
                concrete_subject=proposal.concrete_subject.strip(),
                subject_evidence_refs=subject_evidence_ids,
                originality_reason=proposal.originality_reason.strip(),
                curiosity_family=proposal.curiosity_family.strip().casefold(),
                raw_evidence={
                    "pattern_index": proposal.pattern_index,
                    "pattern": pattern.model_dump(mode="json"),
                    "supporting_video_ids": pattern.video_ids,
                    "subject_evidence_ids": subject_evidence_ids,
                    "subject_evidence": [
                        {
                            "evidence_id": evidence_id,
                            "title": video.title,
                            "topic": video.topic,
                            "tags": video.tags,
                            "topics": video.topics,
                        }
                        for evidence_id, video in zip(
                            subject_evidence_ids,
                            subject_sources,
                            strict=True,
                        )
                    ],
                    "competitor_signal_weight": pattern.signal_weight,
                    "originality_reason": proposal.originality_reason.strip(),
                    "vidiq_search_concepts": (
                        CompetitorOpportunityGenerator._proposal_search_concepts(
                            proposal
                        )
                    ),
                },
                ritzz_fit=RitzzFitResult(
                    fit_status="REVIEW",
                    story_type=proposal.story_type,
                    reason="Competitor-derived idea awaits independent RITZZ-fit validation.",
                ),
            ))
        return candidates, rejected_copies, rejection_details

    @staticmethod
    def _proposal_search_concepts(
        proposal: OriginalTopicProposal,
    ) -> list[str]:
        concepts = list(dict.fromkeys(
            concept.strip()
            for concept in proposal.search_concepts
            if concept.strip()
        ))
        if concepts:
            return concepts[:3]
        return [proposal.concrete_subject.strip()]


_ABSTRACT_SUBJECTS = {
    "big questions",
    "history",
    "science",
    "science mysteries",
    "mysteries",
    "human behavior",
    "technology",
    "ancient civilizations",
    "strange things",
    "global problems",
    "data",
}

_ABSTRACT_TITLE_RE = re.compile(
    r"\b(?:some|many|certain|various|different)\b.{0,90}\b"
    r"(?:questions?|mysteries|problems?|things|topics|phenomena|events)\b"
    r"|\b(?:big|major|unanswered)\s+(?:questions?|mysteries|problems?)\b"
    r"|\b(?:science|history|technology|humanity)\s+"
    r"(?:questions?|mysteries|problems?)\b"
    r"|\b(?:local|global|regional)\s+(?:disaster|problem|event)\b",
    re.IGNORECASE,
)
_SPECIFICITY_FILLER_WORDS = {
    "big", "certain", "different", "event", "events", "explainer", "explainers",
    "history", "idea", "ideas", "many", "mysteries", "mystery", "phenomena",
    "phenomenon", "problem", "problems", "question", "questions", "science",
    "some", "specified", "strong", "technology", "thing", "things", "topic",
    "topics", "under", "various",
}


def _competitor_signal_weight(videos: list[OutlierVideo]) -> float:
    groups = {video.channel_group for video in videos}
    if "format_competitors" in groups or "core" in groups:
        return 1.0
    if "emerging_format" in groups or "emerging" in groups:
        return 0.7
    return 0.5


def _concrete_subject_issue(
    topic: str,
    subject: str,
    evidence: list[OutlierVideo],
) -> str | None:
    if _ABSTRACT_TITLE_RE.search(topic):
        return "The title is a broad abstract premise and does not identify a specific subject."
    subject_key = _normalized_topic(subject)
    title_key = _normalized_topic(topic)
    if not subject_key or subject_key in _ABSTRACT_SUBJECTS:
        return "The proposed subject is a broad category rather than a concrete object, event, place, person, or phenomenon."
    subject_tokens = subject_key.split()
    if len(subject_tokens) < 2 and len(subject_tokens[0]) < 5:
        return "The proposed subject is too broad to identify a specific story."
    if not all(token in title_key.split() for token in subject_tokens):
        return "The final title does not explicitly name its proposed concrete subject."
    for video in evidence:
        source_text = _normalized_topic(" ".join([
            video.title,
            video.topic or "",
            *video.tags,
            *video.topics,
        ]))
        if all(token in source_text.split() for token in subject_tokens):
            break
    else:
        return "The cited provider evidence does not explicitly identify the proposed concrete subject."
    return None


def candidate_specificity_issue(
    candidate: OpportunityCandidate,
    *,
    final_title: bool = False,
) -> tuple[str, str] | None:
    """Reject abstract topics and validate specificity once a final title exists."""
    title = (
        candidate.proposed_title
        if final_title and candidate.proposed_title
        else candidate.topic
    )
    if _ABSTRACT_TITLE_RE.search(title):
        return (
            "TOO_ABSTRACT",
            "Title describes a broad category or essay premise instead of an identifiable subject.",
        )
    meaningful_title_terms = [
        token
        for token in _normalized_topic(title).split()
        if not token.isdigit() and token not in _SPECIFICITY_FILLER_WORDS
    ]
    requires_specific_title = (
        final_title or "competitor-topic-pattern" in candidate.discovery_sources
    )
    if requires_specific_title and len(meaningful_title_terms) < 2:
        return (
            "TOO_ABSTRACT",
            "Title lacks enough identifying subject detail to distinguish it from a generic essay topic.",
        )
    if "competitor-topic-pattern" not in candidate.discovery_sources:
        return None
    subject_records = candidate.raw_evidence.get("subject_evidence", [])
    records_by_id = {
        str(item.get("evidence_id")): item
        for item in subject_records
        if isinstance(item, dict) and item.get("evidence_id") is not None
    } if isinstance(subject_records, list) else {}
    cited = [
        records_by_id[evidence_id]
        for evidence_id in candidate.subject_evidence_refs
        if evidence_id in records_by_id
    ]
    if len(cited) != len(candidate.subject_evidence_refs):
        return (
            "TOO_ABSTRACT",
            "Concrete subject is missing valid competitor-video provenance.",
        )
    def string_values(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    video_sources = [
        OutlierVideo(
            video_id=str(item.get("evidence_id") or ""),
            title=str(item.get("title") or ""),
            topic=str(item.get("topic") or ""),
            tags=string_values(item.get("tags")),
            topics=string_values(item.get("topics")),
        )
        for item in cited
    ]
    reason = _concrete_subject_issue(
        title,
        candidate.concrete_subject or "",
        video_sources,
    )
    if reason:
        return "TOO_ABSTRACT", reason
    if not candidate.originality_reason:
        return (
            "OTHER_HARD_FILTER",
            "Candidate lacks an explicit explanation of its substantive originality.",
        )
    return None


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
    return jaccard >= 0.55 or similarity >= 0.82
