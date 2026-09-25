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
from modules.topic_intelligence.market_intelligence import MarketIntelligenceReport
from modules.topic_intelligence.models import OpportunityReport, TopicDiscoveryRequest
from modules.topic_intelligence.providers.base import (
    ProviderUnavailableError,
    TopicProvider,
)
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider
from modules.topic_intelligence.validation import apply_niche_filter, validate_candidates

SCORING_VERSION = "ritzz-opportunity-v3"
VALIDATION_VERSION = "ritzz-topic-validation-v2"


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
        discover_outliers = getattr(self.provider, "discover_outliers", None)
        if callable(discover_outliers):
            try:
                competitor_report = discover_outliers(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=10,
                )
            except ProviderUnavailableError as exc:
                warnings.append(f"Competitor evidence was unavailable: {exc}")
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
        ranked = rank_candidates(candidates)[:4]
        shortlist_candidate_ids = validate_candidates(ranked)
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
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report
