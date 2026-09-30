import hashlib
import json
import os
from pathlib import Path
from typing import cast

from openai import OpenAIError

from config.settings import (
    RITZZ_CANDIDATE_POOL_TARGET,
    RITZZ_COMPETITOR_LOOKBACK_DAYS,
    RITZZ_COMPETITOR_VIDEO_LIMIT,
    RITZZ_DISCOVERY_FALLBACK_STAGES,
    RITZZ_FIT_PASS_THRESHOLD,
    RITZZ_OUTLIER_MIN_SCORE,
)
from modules.topic_intelligence.competitor_opportunities import (
    CompetitorOpportunityGenerator,
)
from modules.topic_intelligence.editorial import (
    EditorialEvaluator,
    apply_editorial_assessments,
)
from modules.topic_intelligence.evaluator import rank_candidates
from modules.topic_intelligence.inventory import (
    ContentInventoryManager,
    inventory_path,
    normalize_topic,
)
from modules.topic_intelligence.learning import (
    load_m7_learning_signals,
    signals_for_topic,
)
from modules.topic_intelligence.market_intelligence import (
    MarketIntelligenceReport,
    build_market_intelligence_report,
    relevant_competitor_evidence,
    relevant_competitor_patterns,
)
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    OpportunityReport,
    RitzzFitResult,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import (
    ProviderUnavailableError,
    TopicDemandEnrichment,
    TopicProvider,
)
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider
from modules.topic_intelligence.ritzz_fit import (
    build_ritzz_fit_result,
    prefilter_reason,
)
from modules.topic_intelligence.validation import (
    apply_niche_filter,
    validate_candidates,
)

SCORING_VERSION = "ritzz-opportunity-v4"
VALIDATION_VERSION = "ritzz-topic-validation-v3"
COMPETITOR_RESEARCH_VERSION = "competitor-topic-performance-v2"


def _file_cache_signature(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


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
        learning_inventory_path: Path | None = None,
        competitor_opportunity_generator: CompetitorOpportunityGenerator | None = None,
    ) -> None:
        self.provider = provider or VidiqMcpProvider()
        self.cache_dir = Path(cache_dir or Path("cache") / "topic_intelligence")
        self.editorial_evaluator = editorial_evaluator or EditorialEvaluator()
        self.competitor_opportunity_generator = competitor_opportunity_generator
        self.inventory_manager = inventory_manager or ContentInventoryManager(inventory_path(self.cache_dir))
        self.learning_inventory_path = Path(
            learning_inventory_path or os.getenv("RITZZ_M7_INVENTORY_FILE", "projects/inventory.json")
        )

    def _discover_from_competitors(
        self,
        request: TopicDiscoveryRequest,
        primary_research,
        secondary_discovery,
    ) -> tuple[list[OpportunityCandidate], dict, MarketIntelligenceReport | None]:
        query = f"{request.niche} educational curiosity explainers"
        diagnostics: dict = {
            "pool_target": request.limit,
            "sources_attempted": ["configured_competitor_outliers"],
            "sources_unavailable": [],
            "source_counts": {},
            "operations": [],
            "stage_counts": [],
        }
        try:
            competitor_report = primary_research(
                query,
                limit=RITZZ_COMPETITOR_VIDEO_LIMIT,
            )
        except ProviderUnavailableError as exc:
            competitor_report = build_market_intelligence_report(
                query,
                [],
                source=self.provider.name,
                performance_tool_available=False,
                warnings=[f"Configured competitor-video research failed: {exc}"],
            )
            competitor_report.operations.append({
                "source": "configured_competitor_outliers",
                "tool": exc.tool or "vidIQ MCP",
                "status": "failed",
                "error_type": exc.error_type,
                "message": str(exc),
                "fallback_behavior": "Try optional secondary discovery if configured competitors exist.",
            })

        candidates: list[OpportunityCandidate] = []
        pattern_count = 0
        generation_diagnostics = {
            "videos_inspected": competitor_report.videos_inspected or len(competitor_report.outliers),
            "successful_outlier_videos": 0,
            "topic_patterns_extracted": 0,
            "generated_candidates": 0,
            "rejected_copied_angles": 0,
        }
        generator = self.competitor_opportunity_generator
        if competitor_report.outliers:
            if generator is None:
                generator = CompetitorOpportunityGenerator()
                self.competitor_opportunity_generator = generator
            try:
                candidates, patterns, generation_diagnostics = (
                    generator.generate(
                        competitor_report,
                        candidate_limit=min(max(request.limit, 4), 8),
                    )
                )
                pattern_count = len(patterns)
            except (OpenAIError, ValueError, RuntimeError) as exc:
                diagnostics["sources_unavailable"].append(
                    f"competitor_topic_generation: {type(exc).__name__}: {exc}"
                )
                diagnostics["operations"].append({
                    "source": "competitor_topic_generation",
                    "tool": getattr(
                        generator,
                        "model_name",
                        "structured topic generator",
                    ),
                    "status": "failed",
                    "error_type": "TOPIC_GENERATION_ERROR",
                    "message": str(exc),
                    "fallback_behavior": "Use optional secondary sources only when configured competitors were present.",
                })

        diagnostics.update({
            "competitor_channels_configured": competitor_report.configured_competitor_count,
            "competitors_queried": competitor_report.competitors_queried,
            "videos_inspected": generation_diagnostics["videos_inspected"],
            "successful_outlier_videos": generation_diagnostics["successful_outlier_videos"],
            "topic_patterns_extracted": pattern_count,
            "ritzz_candidates_generated": len(candidates),
            "rejected_copied_angles": generation_diagnostics["rejected_copied_angles"],
            "source_counts": {
                "competitor_outliers": {
                    "raw": generation_diagnostics["videos_inspected"],
                    "unique": generation_diagnostics["successful_outlier_videos"],
                },
                "competitor_topic_patterns": {
                    "raw": generation_diagnostics["successful_outlier_videos"],
                    "unique": pattern_count,
                },
                "competitor_generated_topics": {
                    "raw": len(candidates) + generation_diagnostics["rejected_copied_angles"],
                    "unique": len(candidates),
                },
            },
            "operations": list(competitor_report.operations),
        })
        diagnostics["sources_unavailable"].extend(
            f"competitor_report: {warning}"
            for warning in competitor_report.warnings
        )
        diagnostics["operations"].append({
            "source": "competitor_topic_patterns",
            "tool": getattr(
                generator,
                "model_name",
                "structured topic generator",
            ),
            "status": "success" if pattern_count else "insufficient_evidence",
            "error_type": "NONE" if pattern_count else "INSUFFICIENT_CROSS_CHANNEL_EVIDENCE",
            "message": (
                f"Extracted {pattern_count} repeated pattern(s) from "
                f"{generation_diagnostics['successful_outlier_videos']} successful video(s)."
            ),
            "fallback_behavior": (
                "Generate original RITZZ ideas from validated patterns."
                if pattern_count
                else "Do not generate ideas from isolated or unverified competitor videos."
            ),
        })

        demand_enriched = 0
        demand_enricher = getattr(self.provider, "enrich_topic_demand", None)
        if callable(demand_enricher):
            diagnostics["sources_attempted"].append("keyword_research_enrichment")
            for candidate in candidates:
                enrichment = cast(
                    TopicDemandEnrichment,
                    demand_enricher(candidate.topic),
                )
                operation = enrichment.get("operation", {})
                diagnostics["operations"].append(operation)
                if operation.get("status") in {"failed", "unavailable"}:
                    diagnostics["sources_unavailable"].append(
                        "keyword_research_enrichment: "
                        f"{operation.get('error_type', 'PROVIDER_ERROR')}: "
                        f"{operation.get('message', 'No additional details.')}"
                    )
                for name, metric in enrichment.get("metrics", {}).items():
                    candidate.evidence[name] = EvidenceMetric.model_validate(metric)
                    if name in {
                        "search_volume",
                        "growth",
                        "growth_percent",
                        "search_volume_score",
                        "growth_score",
                        "trend_score",
                    }:
                        candidate.current_vidiq_demand_signals[name] = candidate.evidence[name]
                    if name in {
                        "competition",
                        "competition_score",
                        "competition_opportunity_score",
                        "saturation",
                        "saturation_score",
                    }:
                        candidate.competition_saturation_signal = candidate.evidence[name]
                candidate.current_vidiq_demand_available = any(
                    metric.available and metric.value is not None
                    for metric in candidate.current_vidiq_demand_signals.values()
                )
                if enrichment.get("metrics"):
                    demand_enriched += 1
                candidate.competition_saturation_assessment = (
                    _competition_saturation_assessment(candidate)
                )
                for keyword in enrichment.get("related_keywords", []):
                    if keyword.casefold() != candidate.topic.casefold():
                        candidate.related_keywords.append(keyword)
            diagnostics["demand_enriched_candidates"] = demand_enriched
        else:
            diagnostics["demand_enriched_candidates"] = 0
            diagnostics["sources_unavailable"].append(
                "keyword_research_enrichment: provider does not support optional enrichment."
            )

        allow_secondary = (
            competitor_report.configured_competitor_count > 0
            or not isinstance(self.provider, VidiqMcpProvider)
        )
        if len(candidates) < 4 and allow_secondary:
            diagnostics["secondary_fallback_attempted"] = True
            diagnostics["sources_attempted"].append("secondary_topic_discovery")
            try:
                if callable(secondary_discovery):
                    if isinstance(self.provider, VidiqMcpProvider):
                        secondary_candidates, secondary_diagnostics, _ = (
                            secondary_discovery(
                                request,
                                include_competitor_research=False,
                            )
                        )
                    else:
                        secondary_candidates, secondary_diagnostics, _ = (
                            secondary_discovery(request)
                        )
                else:
                    secondary_candidates = self.provider.discover(request)
                    secondary_diagnostics = {
                        "source_counts": {
                            "provider.discover": {
                                "raw": len(secondary_candidates),
                                "unique": len(secondary_candidates),
                            }
                        },
                        "sources_unavailable": [],
                        "operations": [],
                        "stage_counts": [],
                    }
                seen = {normalize_topic(item.topic) for item in candidates}
                for item in secondary_candidates:
                    key = normalize_topic(item.topic)
                    if key and key not in seen:
                        candidates.append(item)
                        seen.add(key)
                diagnostics["source_counts"].update(
                    secondary_diagnostics.get("source_counts", {})
                )
                diagnostics["sources_unavailable"].extend(
                    f"secondary_topic_discovery: {item}"
                    for item in secondary_diagnostics.get("sources_unavailable", [])
                )
                diagnostics["operations"].extend(
                    secondary_diagnostics.get("operations", [])
                )
                diagnostics["stage_counts"].extend(
                    secondary_diagnostics.get("stage_counts", [])
                )
                diagnostics["secondary_candidate_count"] = len(secondary_candidates)
            except ProviderUnavailableError as exc:
                diagnostics["sources_unavailable"].append(
                    f"secondary_topic_discovery: {exc.error_type}: {exc}"
                )
                diagnostics["operations"].append({
                    "source": "secondary_topic_discovery",
                    "tool": exc.tool or "secondary discovery",
                    "status": "failed",
                    "error_type": exc.error_type,
                    "message": str(exc),
                    "fallback_behavior": "Keep only validated competitor-derived ideas.",
                })
        elif len(candidates) < 4:
            diagnostics["secondary_fallback_attempted"] = False
            diagnostics["sources_unavailable"].append(
                "secondary_topic_discovery: skipped because no competitors are configured; "
                "generic trend results are not substituted for competitor evidence."
            )
        diagnostics["pool_unique_total"] = len(candidates)
        diagnostics["stage_counts"].insert(0, {
            "stage": "configured_competitor_outliers",
            "raw_total": generation_diagnostics["videos_inspected"],
            "pool_unique_total": len(candidates),
        })
        return candidates[: request.limit], diagnostics, competitor_report

    def discover(self, request: TopicDiscoveryRequest | None = None) -> OpportunityReport:
        request = request or TopicDiscoveryRequest()
        registry_path = getattr(self.provider, "competitor_registry_path", None)
        registry_path = Path(registry_path) if registry_path is not None else None
        cache_key = hashlib.sha256(
            json.dumps({
                "request": request.model_dump(exclude={"force_refresh"}),
                "provider": self.provider.name,
                "scoring_version": SCORING_VERSION,
                "validation_version": VALIDATION_VERSION,
                "competitor_research_version": COMPETITOR_RESEARCH_VERSION,
                "candidate_pool_target": RITZZ_CANDIDATE_POOL_TARGET,
                "fallback_stages": RITZZ_DISCOVERY_FALLBACK_STAGES,
                "ritzz_fit_pass_threshold": RITZZ_FIT_PASS_THRESHOLD,
                "competitor_video_limit": RITZZ_COMPETITOR_VIDEO_LIMIT,
                "competitor_lookback_days": RITZZ_COMPETITOR_LOOKBACK_DAYS,
                "outlier_min_score": RITZZ_OUTLIER_MIN_SCORE,
                "learning_inventory": _file_cache_signature(self.learning_inventory_path),
                "competitor_registry": _file_cache_signature(registry_path),
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()
        report_path = self.cache_dir / f"{cache_key}.json"
        if report_path.exists() and not request.force_refresh:
            report = OpportunityReport.model_validate_json(report_path.read_text(encoding="utf-8"))
            report.cached = True
            return report
        provider_request = request.model_copy(
            update={
                "limit": min(max(RITZZ_CANDIDATE_POOL_TARGET, 15), 30)
                if request.pipeline_topic_gate
                else max(request.limit, 8)
            }
        )
        warnings: list[str] = []
        diagnostics: dict = {}
        diagnostics["request"] = request.model_dump(mode="json")
        competitor_report: MarketIntelligenceReport | None = None
        pipeline_discovery = getattr(self.provider, "discover_pipeline_candidates", None)
        primary_competitor_research = getattr(
            self.provider,
            "discover_competitor_research",
            None,
        )
        if request.pipeline_topic_gate and callable(primary_competitor_research):
            candidates, diagnostics, competitor_report = self._discover_from_competitors(
                provider_request,
                primary_competitor_research,
                pipeline_discovery,
            )
        else:
            try:
                if request.pipeline_topic_gate and callable(pipeline_discovery):
                    candidates, diagnostics, competitor_report = pipeline_discovery(provider_request)
                else:
                    candidates = self.provider.discover(provider_request)
                    diagnostics = {
                        "pool_target": provider_request.limit,
                        "sources_attempted": ["provider.discover"],
                        "sources_unavailable": [],
                        "source_counts": {
                            "provider.discover": {
                                "raw": len(candidates),
                                "unique": len(candidates),
                            }
                        },
                        "stage_counts": [],
                    }
            except ProviderUnavailableError as exc:
                candidates = []
                diagnostics = {
                    "pool_target": provider_request.limit,
                    "sources_attempted": ["provider.discover_pipeline_candidates"],
                    "sources_unavailable": [str(exc)],
                    "source_counts": {},
                    "stage_counts": [],
                    "operations": [{
                        "source": "secondary_discovery",
                        "tool": exc.tool or "provider.discover_pipeline_candidates",
                        "status": "failed",
                        "error_type": exc.error_type,
                        "message": str(exc),
                        "fallback_behavior": "No topic metrics are fabricated.",
                    }],
                }
        warnings.extend(
            f"Discovery source unavailable: {source}"
            for source in diagnostics.get("sources_unavailable", [])
        )
        raw_count = len(candidates)
        normalized_candidates: list[OpportunityCandidate] = []
        seen_topics: set[str] = set()
        duplicate_exclusions: list[dict[str, str]] = []
        for candidate in candidates:
            normalized = normalize_topic(candidate.topic)
            if not normalized:
                duplicate_exclusions.append({
                    "topic": candidate.topic,
                    "reason": "Topic was empty after normalization.",
                })
                continue
            if normalized in seen_topics:
                duplicate_exclusions.append({
                    "topic": candidate.topic,
                    "reason": "Exact normalized duplicate of an earlier candidate.",
                })
                continue
            seen_topics.add(normalized)
            normalized_candidates.append(candidate)
        candidates = normalized_candidates
        diagnostics["after_normalization"] = len(candidates)
        diagnostics["duplicates_removed"] = duplicate_exclusions
        learning_signals, learning_videos = load_m7_learning_signals(
            self.learning_inventory_path
        )
        diagnostics["m7_learning"] = {
            "status": learning_signals.status,
            "historical_video_count": learning_signals.historical_video_count,
            "sample_size": learning_signals.sample_size,
            "data_quality": learning_signals.data_quality,
            "inventory_path": str(self.learning_inventory_path),
        }
        if learning_signals.status != "AVAILABLE":
            warnings.extend(learning_signals.warnings)
        for candidate in candidates:
            candidate.ritzz_learning_signals = signals_for_topic(
                candidate.topic,
                learning_signals,
                learning_videos,
            )
        eligible = []
        inventory_excluded: list[dict[str, str]] = []
        for candidate in candidates:
            overlaps = self.inventory_manager.find_overlap(candidate.topic)
            if overlaps:
                inventory_excluded.append({
                    "topic": candidate.topic,
                    "reason": "Overlaps existing RITZZ inventory: "
                    + ", ".join(item.topic for item in overlaps),
                })
                continue
            eligible.append(candidate)
        candidates = eligible
        diagnostics["raw_candidates"] = raw_count
        diagnostics["after_inventory_filter"] = len(candidates)
        diagnostics["inventory_exclusions"] = inventory_excluded
        if inventory_excluded:
            warnings.append(
                f"Excluded {len(inventory_excluded)} candidate(s) overlapping the RITZZ content inventory."
            )
        apply_niche_filter(candidates)
        diagnostics["after_niche_filter"] = sum(not item.filter_reasons for item in candidates)
        diagnostics["niche_filter_exclusions"] = [
            {"topic": item.topic, "reasons": item.filter_reasons}
            for item in candidates if item.filter_reasons
        ]
        fit_prefilter_exclusions: list[dict[str, str]] = []
        editorial_candidates = []
        for candidate in candidates:
            prefilter = prefilter_reason(candidate)
            if prefilter is None and not candidate.filter_reasons:
                editorial_candidates.append(candidate)
                candidate.ritzz_fit = RitzzFitResult(
                    fit_status="REVIEW",
                    reason="Editorial fit assessment pending.",
                )
                continue
            if prefilter is None:
                fit_status = "REVIEW"
                reason = "Niche/format filter must be resolved before editorial assessment."
            else:
                fit_status, reason = prefilter
            candidate.ritzz_fit = RitzzFitResult(
                fit_status=fit_status,
                reason=reason,
            )
            fit_prefilter_exclusions.append({"topic": candidate.topic, "reason": reason})
        diagnostics["after_ritzz_fit_prefilter"] = len(editorial_candidates)
        diagnostics["ritzz_fit_exclusions"] = fit_prefilter_exclusions
        competitor_report_payload: dict | None = None
        discover_competitor_research = (
            getattr(self.provider, "discover_competitor_research", None)
            if competitor_report is None else None
        )
        discover_outliers = (
            getattr(self.provider, "discover_outliers", None)
            if competitor_report is None else None
        )
        if callable(discover_competitor_research):
            try:
                result = discover_competitor_research(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=10,
                )
                if isinstance(result, MarketIntelligenceReport):
                    competitor_report = result
                elif competitor_report is None:
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
                matched_evidence = relevant_competitor_evidence(
                    candidate.topic,
                    competitor_report,
                )
                existing_evidence_ids = {
                    str(item.video.get("id"))
                    for item in candidate.competitor_evidence
                    if item.video.get("id") is not None
                }
                candidate.competitor_evidence.extend(
                    item for item in matched_evidence
                    if str(item.video.get("id")) not in existing_evidence_ids
                )
                matched_patterns = relevant_competitor_patterns(
                    candidate.topic,
                    competitor_report,
                )
                existing_patterns = {
                    (item.observed_pattern or item.topic).casefold()
                    for item in candidate.competitor_topic_patterns
                }
                candidate.competitor_topic_patterns.extend(
                    item for item in matched_patterns
                    if (item.observed_pattern or item.topic).casefold() not in existing_patterns
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
                candidate.current_vidiq_demand_available = any(
                    metric.available and metric.value is not None
                    for metric in candidate.current_vidiq_demand_signals.values()
                )
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
            if editorial_candidates:
                assessments = self.editorial_evaluator.assess(editorial_candidates)
                apply_editorial_assessments(editorial_candidates, assessments)
                editorial_scored = True
        except (OpenAIError, ValueError, RuntimeError):
            # Preserve actual provider data and keep discovery usable if editorial
            # scoring is temporarily unavailable. Never replace it with guessed scores.
            warnings.append(
                "OpenAI editorial scoring was unavailable; candidates retain provider "
                "signals only and the user should assess fit manually."
            )
        for candidate in editorial_candidates:
            story_type = candidate.ritzz_fit.story_type if candidate.ritzz_fit else "OTHER"
            fit = build_ritzz_fit_result(
                candidate,
                story_type=story_type,
                editorial_status=candidate.editorial_status,
                editorial_scores=candidate.editorial_scores,
                pass_threshold=RITZZ_FIT_PASS_THRESHOLD,
            )
            candidate.ritzz_fit = fit
        if isinstance(competitor_report, MarketIntelligenceReport):
            for candidate in candidates:
                if candidate.ritzz_differentiation_angle is None:
                    candidate.ritzz_differentiation_angle = candidate.angle
        ranked_all = rank_candidates(candidates)
        all_recommended_ids = validate_candidates(ranked_all)
        diagnostics["after_editorial_filter"] = sum(
            item.editorial_status == "PASS"
            and not item.filter_reasons
            for item in ranked_all
        )
        diagnostics["after_near_duplicate_filter"] = sum(
            item.editorial_status == "PASS"
            and item.ritzz_fit is not None
            and item.ritzz_fit.fit_status == "PASS"
            and not item.filter_reasons
            and not any("near-duplicate" in reason.casefold() for reason in item.validation_reasons)
            for item in ranked_all
        )
        diagnostics["after_final_validation"] = sum(
            item.editorial_status == "PASS"
            and item.ritzz_fit is not None
            and item.ritzz_fit.fit_status == "PASS"
            and not item.filter_reasons
            and item.validation_status == "RECOMMENDED"
            for item in ranked_all
        )
        diagnostics["candidate_exclusions"] = [
            {
                "topic": item.topic,
                "sources": item.discovery_sources,
                "editorial_status": item.editorial_status,
                "validation_status": item.validation_status,
                "ritzz_fit": item.ritzz_fit.model_dump(mode="json") if item.ritzz_fit else None,
                "filter_reasons": item.filter_reasons,
                "validation_reasons": item.validation_reasons,
            }
            for item in ranked_all
            if (
                item.editorial_status != "PASS"
                or item.ritzz_fit is None
                or item.ritzz_fit.fit_status != "PASS"
                or item.filter_reasons
                or any("near-duplicate" in reason.casefold() for reason in item.validation_reasons)
                or item.validation_status != "RECOMMENDED"
            )
        ]
        diagnostics["missing_signals"] = [
            {
                "topic": item.topic,
                "signals": [
                    name
                    for name in (
                        "search_volume",
                        "search_volume_score",
                        "growth",
                        "growth_score",
                        "competition",
                    )
                    if (
                        name not in item.evidence
                        or not item.evidence[name].available
                        or item.evidence[name].value is None
                    )
                ],
            }
            for item in ranked_all
        ]
        if request.pipeline_topic_gate:
            ranked = [
                candidate
                for candidate in ranked_all
                if candidate.editorial_status == "PASS"
                and candidate.ritzz_fit is not None
                and candidate.ritzz_fit.fit_status == "PASS"
                and not candidate.filter_reasons
                and not any("near-duplicate" in reason.casefold() for reason in candidate.validation_reasons)
                and candidate.validation_status == "RECOMMENDED"
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
                    if candidate.ritzz_fit is None or candidate.ritzz_fit.fit_status != "PASS":
                        reasons = [
                            candidate.ritzz_fit.reason
                            if candidate.ritzz_fit
                            else "RITZZ fit did not pass"
                        ]
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
        diagnostics["final_count"] = len(ranked)
        diagnostics["sources_attempted"] = diagnostics.get("sources_attempted", [])
        diagnostics["sources_unavailable"] = diagnostics.get("sources_unavailable", [])
        diagnostics["source_counts"] = diagnostics.get("source_counts", {})
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
            discovery_diagnostics=diagnostics,
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report
