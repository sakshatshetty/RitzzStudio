import hashlib
import json
from pathlib import Path

from openai import OpenAIError

from modules.topic_intelligence.editorial import (
    EditorialEvaluator,
    apply_editorial_assessments,
)
from modules.topic_intelligence.evaluator import rank_candidates
from modules.topic_intelligence.inventory import ContentInventoryManager, inventory_path
from modules.topic_intelligence.market_intelligence import (
    MarketIntelligenceReport,
    build_market_intelligence_report,
    relevant_competitor_evidence,
    relevant_competitor_patterns,
)
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import (
    ProviderUnavailableError,
    TopicProvider,
)
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider
from modules.topic_intelligence.validation import (
    apply_niche_filter,
    validate_candidates,
)

SCORING_VERSION = "ritzz-opportunity-v3"
VALIDATION_VERSION = "ritzz-topic-validation-v2"
COMPETITOR_RESEARCH_VERSION = "competitor-topic-performance-v1"


def _competition_saturation_assessment(candidate: OpportunityCandidate) -> str:
    metric = candidate.competition_saturation_signal
    if metric is None or not metric.available or metric.value is None:
        assessment = "Current vidIQ competition signal unavailable."
    elif isinstance(metric.value, (int, float)):
        assessment = (
            f"Current vidIQ competition signal: {metric.value} {metric.unit or ''}; "
            "higher raw competition values reduce attractiveness."
        ).strip()
    else:
        level = str(metric.value).casefold()
        if "high" in level:
            assessment = "vidIQ labels competition high; this reduces topic attractiveness."
        elif "medium" in level or "moderate" in level:
            assessment = "vidIQ labels competition moderate; consider this competition pressure."
        elif "low" in level:
            assessment = "vidIQ labels competition low."
        else:
            assessment = f"Raw vidIQ competition signal: {metric.value}."
    if candidate.competitor_topic_patterns:
        channel_count = max(
            pattern.channel_count
            for pattern in candidate.competitor_topic_patterns
        )
        assessment += (
            f" A repeated matching topic pattern appeared across {channel_count} "
            "competitor channels; this may indicate saturation, not certain demand."
        )
    return assessment


class TopicIntelligenceEngine:
    def __init__(
        self,
        provider: TopicProvider | None = None,
        cache_dir: Path | None = None,
        editorial_evaluator: EditorialEvaluator | None = None,
        inventory_manager: ContentInventoryManager | None = None,
    ) -> None:
        self.provider = provider or VidiqMcpProvider()
        self.cache_dir = Path(cache_dir or Path("cache") / "topic_intelligence")
        self.editorial_evaluator = editorial_evaluator or EditorialEvaluator()
        self.inventory_manager = inventory_manager or ContentInventoryManager(inventory_path(self.cache_dir))

    def discover(self, request: TopicDiscoveryRequest | None = None) -> OpportunityReport:
        request = request or TopicDiscoveryRequest()
        cache_key = hashlib.sha256(
            json.dumps({
                "request": request.model_dump(exclude={"force_refresh"}),
                "provider": self.provider.name,
                "scoring_version": SCORING_VERSION,
                "validation_version": VALIDATION_VERSION,
                "competitor_research_version": COMPETITOR_RESEARCH_VERSION,
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()
        report_path = self.cache_dir / f"{cache_key}.json"
        if report_path.exists() and not request.force_refresh:
            report = OpportunityReport.model_validate_json(report_path.read_text(encoding="utf-8"))
            report.cached = True
            return report
        provider_request = request.model_copy(update={"limit": max(request.limit, 8)})
        candidates = self.provider.discover(provider_request)
        if not candidates:
            raise ProviderUnavailableError("Topic provider returned no candidates.")
        warnings = []
        eligible = []
        excluded = 0
        for candidate in candidates:
            overlaps = self.inventory_manager.find_overlap(candidate.topic)
            if overlaps:
                excluded += 1
                continue
            eligible.append(candidate)
        if excluded:
            warnings.append(f"Excluded {excluded} candidate(s) overlapping the RITZZ content inventory.")
        candidates = eligible[:max(request.limit, 4)]
        if len(candidates) < 4:
            warnings.append(f"Only {len(candidates)} distinct inventory-safe candidate(s) were available; four were requested.")
        apply_niche_filter(candidates)
        competitor_report: MarketIntelligenceReport | None = None
        competitor_report_payload: dict | None = None
        discover_competitor_research = getattr(
            self.provider, "discover_competitor_research", None
        )
        discover_outliers = getattr(self.provider, "discover_outliers", None)
        if callable(discover_competitor_research):
            try:
                result = discover_competitor_research(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=10,
                )
                if isinstance(result, MarketIntelligenceReport):
                    competitor_report = result
                else:
                    dump_method = getattr(result, "model_dump", None)
                    if callable(dump_method):
                        payload = dump_method()
                        if isinstance(payload, dict):
                            competitor_report_payload = payload
            except ProviderUnavailableError as exc:
                competitor_report = build_market_intelligence_report(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    [],
                    source=self.provider.name,
                    performance_tool_available=False,
                    warnings=[f"Competitor evidence was unavailable: {exc}"],
                )
        elif callable(discover_outliers):
            try:
                result = discover_outliers(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=10,
                )
                if isinstance(result, MarketIntelligenceReport):
                    competitor_report = result
                else:
                    dump_method = getattr(result, "model_dump", None)
                    if callable(dump_method):
                        payload = dump_method()
                        if isinstance(payload, dict):
                            competitor_report_payload = payload
            except ProviderUnavailableError as exc:
                competitor_report = build_market_intelligence_report(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    [],
                    source=self.provider.name,
                    performance_tool_available=False,
                    warnings=[f"Competitor evidence was unavailable: {exc}"],
                )
        else:
            competitor_report = build_market_intelligence_report(
                f"{request.trend_topic or request.niche} curiosity explainers",
                [],
                source=self.provider.name,
                performance_tool_available=False,
                warnings=[f"Provider '{self.provider.name}' does not support competitor-video research."],
            )
        if isinstance(competitor_report, MarketIntelligenceReport):
            for candidate in candidates:
                candidate.competitor_topic_performance_available = (
                    competitor_report.competitor_topic_performance_available
                )
                candidate.competitor_evidence = relevant_competitor_evidence(
                    candidate.topic,
                    competitor_report,
                )
                candidate.competitor_topic_patterns = relevant_competitor_patterns(
                    candidate.topic,
                    competitor_report,
                )
                candidate.current_vidiq_demand_signals = {
                    key: candidate.evidence[key]
                    for key in (
                        "search_volume",
                        "search_volume_score",
                        "growth",
                        "growth_percent",
                        "growth_score",
                        "trend_growth",
                        "trend_score",
                    )
                    if key in candidate.evidence
                }
                candidate.competition_saturation_signal = next(
                    (
                        candidate.evidence[key]
                        for key in (
                            "competition",
                            "competition_score",
                            "competition_opportunity_score",
                            "saturation",
                            "saturation_score",
                        )
                        if key in candidate.evidence
                    ),
                    None,
                )
                candidate.competition_saturation_assessment = (
                    _competition_saturation_assessment(candidate)
                )
        editorial_scored = False
        try:
            assessments = self.editorial_evaluator.assess(candidates)
            apply_editorial_assessments(candidates, assessments)
            editorial_scored = True
        except (OpenAIError, ValueError, RuntimeError):
            # Preserve actual provider data and keep discovery usable if editorial
            # scoring is temporarily unavailable. Never replace it with guessed scores.
            warnings.append(
                "OpenAI editorial scoring was unavailable; candidates retain provider "
                "signals only and the user should assess fit manually."
            )
        if isinstance(competitor_report, MarketIntelligenceReport):
            for candidate in candidates:
                candidate.ritzz_differentiation_angle = candidate.angle
        ranked_all = rank_candidates(candidates)
        all_recommended_ids = validate_candidates(ranked_all)
        if request.pipeline_topic_gate:
            ranked = [
                candidate
                for candidate in ranked_all
                if candidate.editorial_status == "PASS"
                and not candidate.filter_reasons
                and not any("near-duplicate" in reason.casefold() for reason in candidate.validation_reasons)
            ][:4]
            shortlist_candidate_ids = [candidate.candidate_id for candidate in ranked]
            excluded_count = len(ranked_all) - len(ranked)
            if excluded_count:
                warnings.append(
                    f"Pipeline topic gate excluded {excluded_count} candidate(s) without editorial PASS, with niche/format concerns, or near-duplicates."
                )
                selected_ids = {candidate.candidate_id for candidate in ranked}
                excluded_details = []
                for candidate in ranked_all:
                    if candidate.candidate_id in selected_ids:
                        continue
                    reasons = candidate.filter_reasons or candidate.validation_reasons
                    reason_text = "; ".join(reasons[:2]) or "editorial status was not PASS"
                    excluded_details.append(
                        f"{candidate.topic[:80]} [editorial={candidate.editorial_status or 'unavailable'}; {reason_text}]"
                    )
                    if len(excluded_details) == 6:
                        break
                if excluded_details:
                    warnings.append("Topic gate exclusions: " + " | ".join(excluded_details))
        else:
            ranked = ranked_all[:4]
            shortlist_candidate_ids = [
                candidate_id
                for candidate_id in all_recommended_ids
                if candidate_id in {candidate.candidate_id for candidate in ranked}
            ]
        if len(ranked) < 4:
            warnings.append(
                f"Only {len(ranked)} candidates passed the pipeline topic gate; four suitable options are required."
            )
        if any(candidate.score_completeness < 0.5 for candidate in ranked):
            warnings.append(
                "Some opportunity scores have low evidence coverage. Inspect each raw signal; "
                "missing editorial signals are not inferred."
            )
        flagged = sum(candidate.editorial_status in {"REVIEW", "FAIL"} for candidate in ranked)
        if flagged:
            warnings.append(
                f"{flagged} candidate(s) received a REVIEW or FAIL editorial flag; "
                "they remain visible and are not automatically deleted."
            )
        if not shortlist_candidate_ids:
            warnings.append("No candidate passed the recommendation gate; review the visible candidates or revise discovery criteria.")
        elif len(shortlist_candidate_ids) < 3:
            warnings.append(f"Only {len(shortlist_candidate_ids)} candidate(s) passed the recommendation gate.")
        report = OpportunityReport(
            report_id=cache_key,
            request=request,
            provider=self.provider.name,
            candidates=ranked,
            warnings=warnings,
            editorial_model=getattr(self.editorial_evaluator, "model_name", None)
            if editorial_scored
            else None,
            editorial_prompt_version=getattr(self.editorial_evaluator, "prompt_version", None)
            if editorial_scored
            else None,
            scoring_version=SCORING_VERSION,
            shortlist_candidate_ids=shortlist_candidate_ids,
            competitor_report=(
                competitor_report.model_dump()
                if competitor_report
                else competitor_report_payload
            ),
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report
