import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from openai import OpenAIError

from modules.topic_intelligence.competitor_opportunities import CompetitorOpportunityGenerator
from modules.topic_intelligence.editorial import (
    EditorialAssessmentProvider,
    EditorialEvaluator,
    apply_editorial_assessments,
)
from modules.topic_intelligence.evaluator import rank_candidates
from modules.topic_intelligence.inventory import ContentInventoryManager, inventory_path
from modules.topic_intelligence.market_intelligence import MarketIntelligenceReport
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import (
    ProviderUnavailableError,
    TopicDemandEnrichment,
    TopicProvider,
)
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider
from modules.topic_intelligence.ritzz_fit import build_ritzz_fit_result
from modules.topic_intelligence.validation import (
    apply_niche_filter,
    validate_candidates,
)

SCORING_VERSION = "ritzz-opportunity-v3"
VALIDATION_VERSION = "ritzz-topic-validation-v2"


@runtime_checkable
class OutlierResearchProvider(Protocol):
    def discover_outliers(
        self,
        query: str,
        limit: int = 10,
    ) -> MarketIntelligenceReport:
        ...


@runtime_checkable
class PipelineCandidateProvider(Protocol):
    def discover_pipeline_candidates(
        self,
        request: TopicDiscoveryRequest,
        *,
        include_competitor_research: bool = True,
    ) -> tuple[
        list[OpportunityCandidate],
        dict[str, Any],
        MarketIntelligenceReport | None,
    ]:
        ...


@runtime_checkable
class CompetitorResearchProvider(Protocol):
    def discover_competitor_research(
        self,
        query: str,
        limit: int = 10,
    ) -> MarketIntelligenceReport:
        ...


@runtime_checkable
class DemandEnrichmentProvider(Protocol):
    def enrich_topic_demand(self, topic: str) -> TopicDemandEnrichment:
        ...


class TopicIntelligenceEngine:
    def __init__(
        self,
        provider: TopicProvider | None = None,
        cache_dir: Path | None = None,
        editorial_evaluator: EditorialAssessmentProvider | None = None,
        inventory_manager: ContentInventoryManager | None = None,
        competitor_opportunity_generator: CompetitorOpportunityGenerator | None = None,
    ) -> None:
        self.provider = provider or VidiqMcpProvider()
        self.cache_dir = Path(cache_dir or Path("cache") / "topic_intelligence")
        self.editorial_evaluator = editorial_evaluator or EditorialEvaluator()
        self.inventory_manager = inventory_manager or ContentInventoryManager(inventory_path(self.cache_dir))
        self.competitor_opportunity_generator = competitor_opportunity_generator

    def discover(self, request: TopicDiscoveryRequest | None = None) -> OpportunityReport:
        request = request or TopicDiscoveryRequest()
        cache_key = hashlib.sha256(
            json.dumps({
                "request": request.model_dump(exclude={"force_refresh"}),
                "provider": self.provider.name,
                "scoring_version": SCORING_VERSION,
                "validation_version": VALIDATION_VERSION,
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()
        report_path = self.cache_dir / f"{cache_key}.json"
        if report_path.exists() and not request.force_refresh:
            report = OpportunityReport.model_validate_json(report_path.read_text(encoding="utf-8"))
            report.cached = True
            return report
        provider_request = request.model_copy(update={"limit": max(request.limit, 8)})
        discovery_diagnostics: dict[str, Any] = {}
        competitor_report: MarketIntelligenceReport | None = None
        if self.competitor_opportunity_generator is not None:
            if isinstance(self.provider, PipelineCandidateProvider):
                candidates, discovery_diagnostics, competitor_report = (
                    self.provider.discover_pipeline_candidates(
                    provider_request,
                    include_competitor_research=True,
                    )
                )
            else:
                candidates = self.provider.discover(provider_request)
        else:
            candidates = self.provider.discover(provider_request)
        if self.competitor_opportunity_generator is not None:
            if competitor_report is None and isinstance(
                self.provider,
                CompetitorResearchProvider,
            ):
                competitor_report = self.provider.discover_competitor_research(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=10,
                )
            if competitor_report is None and isinstance(self.provider, OutlierResearchProvider):
                try:
                    competitor_report = self.provider.discover_outliers(
                        f"{request.trend_topic or request.niche} curiosity explainers",
                        limit=10,
                    )
                except ProviderUnavailableError as exc:
                    discovery_diagnostics.setdefault("sources_unavailable", []).append(
                        f"competitor-outliers: {exc}"
                    )
            if competitor_report is not None:
                generated, patterns, generator_diagnostics = (
                    self.competitor_opportunity_generator.generate(
                        competitor_report,
                        candidate_limit=8,
                    )
                )
                candidates.extend(generated)
                discovery_diagnostics["competitor_opportunity_generation"] = (
                    generator_diagnostics
                )
                discovery_diagnostics["competitor_topic_patterns"] = [
                    pattern.model_dump(mode="json") for pattern in patterns
                ]
                if isinstance(self.provider, DemandEnrichmentProvider):
                    for candidate in generated:
                        self._enrich_competitor_candidate(
                            candidate,
                            self.provider.enrich_topic_demand,
                            discovery_diagnostics,
                        )
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
        if competitor_report is None and isinstance(self.provider, OutlierResearchProvider):
            try:
                competitor_report = self.provider.discover_outliers(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=10,
                )
            except ProviderUnavailableError as exc:
                warnings.append(f"Competitor evidence was unavailable: {exc}")
        editorial_scored = False
        try:
            assessments = self.editorial_evaluator.assess(candidates)
            apply_editorial_assessments(candidates, assessments)
            assessment_by_id = {
                assessment.candidate_id: assessment
                for assessment in assessments
            }
            for candidate in candidates:
                assessment = assessment_by_id.get(candidate.candidate_id)
                if assessment is None or not candidate.discovery_sources:
                    continue
                candidate.ritzz_fit = build_ritzz_fit_result(
                    candidate,
                    story_type=assessment.story_type or "OTHER",
                    editorial_status=assessment.status,
                    editorial_scores=candidate.editorial_scores,
                )
            editorial_scored = True
        except (OpenAIError, ValueError, RuntimeError):
            # Preserve actual provider data and keep discovery usable if editorial
            # scoring is temporarily unavailable. Never replace it with guessed scores.
            warnings.append(
                "OpenAI editorial scoring was unavailable; candidates retain provider "
                "signals only and the user should assess fit manually."
            )
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
            competitor_report=competitor_report.model_dump() if competitor_report else None,
            discovery_diagnostics=discovery_diagnostics,
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report

    @staticmethod
    def _enrich_competitor_candidate(
        candidate: OpportunityCandidate,
        enrich,
        diagnostics: dict[str, Any],
    ) -> None:
        try:
            enrichment = enrich(candidate.topic)
        except ProviderUnavailableError as exc:
            operation = {
                "source": "keyword_research_enrichment",
                "tool": exc.tool or "vidIQ MCP",
                "status": "failed",
                "error_type": "PROVIDER_ERROR",
                "message": str(exc),
            }
            diagnostics.setdefault("operations", []).append(operation)
            diagnostics.setdefault("sources_unavailable", []).append(
                f"keyword_research_enrichment: PROVIDER_ERROR: {exc}"
            )
            candidate.competition_saturation_assessment = (
                "Current vidIQ competition signal unavailable."
            )
            return
        candidate.current_vidiq_demand_available = enrichment["available"]
        candidate.current_vidiq_demand_signals = {
            key: EvidenceMetric.model_validate(value)
            for key, value in enrichment["metrics"].items()
        }
        candidate.vidiq_status = (
            "SCORED" if candidate.current_vidiq_demand_available else "UNAVAILABLE"
        )
        if not candidate.current_vidiq_demand_available:
            candidate.competition_saturation_assessment = (
                "Current vidIQ competition signal unavailable."
            )
        operation = enrichment["operation"]
        diagnostics.setdefault("operations", []).append(operation)
        if operation.get("status") in {"failed", "unavailable"}:
            diagnostics.setdefault("sources_unavailable", []).append(
                "keyword_research_enrichment: "
                f"{operation.get('error_type', 'PROVIDER_ERROR')}: "
                f"{operation.get('message', '')}"
            )
