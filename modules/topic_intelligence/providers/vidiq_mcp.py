"""Official vidIQ MCP provider using runtime tool/schema discovery.

The adapter deliberately inspects MCP tool schemas instead of assuming a
vidIQ-specific HTTP API or hard-coding undocumented tool arguments.
"""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from config.settings import (
    RITZZ_COMPETITOR_LOOKBACK_DAYS,
    RITZZ_COMPETITOR_VIDEO_LIMIT,
    RITZZ_COMPETITORS_FILE,
    RITZZ_DISCOVERY_FALLBACK_STAGES,
    RITZZ_OUTLIER_MIN_SCORE,
    VIDIQ_MCP_API_KEY,
    VIDIQ_MCP_URL,
)
from modules.topic_intelligence.market_intelligence import (
    MarketIntelligenceReport,
    build_market_intelligence_report,
    is_successful_outlier_video,
    normalize_outlier,
)
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import (
    ProviderUnavailableError,
    TopicDemandEnrichment,
)


def normalize_candidate_key(topic: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", topic.casefold()))


class VidiqMcpProvider:
    name = "vidiq_mcp"

    def __init__(
        self,
        endpoint: str = VIDIQ_MCP_URL,
        api_key: str | None = VIDIQ_MCP_API_KEY,
        timeout: float = 30,
        session: requests.Session | None = None,
        competitor_registry_path: str | Path | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session_id: str | None = None
        self._request_id = 0
        self._initialized = False
        self._tools_cache: list[dict[str, Any]] | None = None
        self.protocol_version = "2025-03-26"
        self.competitor_registry_path = Path(
            competitor_registry_path
            or RITZZ_COMPETITORS_FILE
        )

    def discover(self, request: TopicDiscoveryRequest) -> list[OpportunityCandidate]:
        if not self.api_key:
            raise ProviderUnavailableError(
                "vidIQ MCP is not configured. Add VIDIQ_MCP_API_KEY to .env "
                "using a vidIQ MCP API key, then retry discovery."
            )
        available = self._list_tools()
        tool = self._select_tool(available, request.mode)
        if tool is None:
            raise ProviderUnavailableError(
                f"The connected vidIQ MCP server did not expose a supported "
                f"{request.mode.casefold()} discovery tool."
            )
        result = self._rpc("tools/call", {
            "name": tool["name"],
            "arguments": self._arguments(tool, request),
        })
        records = self._extract_records(result)
        if not records:
            shape = self._response_shape(result)
            raise ProviderUnavailableError(
                "vidIQ returned a response that did not contain recognizable "
                f"topic rows ({shape}). No topics or metrics were guessed."
            )
        return [
            self._candidate(record, index, request.mode)
            for index, record in enumerate(records[:request.limit])
        ]

    def _list_tools(self) -> list[dict[str, Any]]:
        if self._tools_cache is not None:
            return self._tools_cache
        result = self._rpc("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list):
            raise ProviderUnavailableError(
                "vidIQ MCP tools/list did not return a tool list.",
                error_type="INVALID_CAPABILITY_RESPONSE",
                tool="tools/list",
            )
        self._tools_cache = [tool for tool in tools if isinstance(tool, dict)]
        return self._tools_cache

    def enrich_topic_demand(self, topic: str) -> TopicDemandEnrichment:
        """Optionally attach vidIQ keyword signals; failures never block a topic."""
        operation = {
            "source": "keyword_research_enrichment",
            "tool": "unavailable",
            "status": "unavailable",
            "error_type": "CAPABILITY_UNAVAILABLE",
            "message": "",
            "fallback_behavior": "Retain the candidate with demand and competition marked unavailable.",
        }
        result: TopicDemandEnrichment = {
            "available": False,
            "metrics": {},
            "related_keywords": [],
            "operation": operation,
        }
        if not self.api_key:
            operation["message"] = "vidIQ MCP is not configured."
            return result
        try:
            tools = self._list_tools()
            tool = self._find_keyword_research_tool(tools)
            if tool is None:
                operation["message"] = (
                    "The advertised vidIQ tool set has no schema-compatible keyword research capability."
                )
                return result
            operation["tool"] = str(tool["name"])
            arguments = self._keyword_research_arguments(tool, topic)
            if arguments is None:
                operation["error_type"] = "UNSUPPORTED_ARGUMENT_SCHEMA"
                operation["message"] = (
                    "The keyword-research tool has required fields that cannot be mapped safely."
                )
                return result
            response = self._rpc("tools/call", {
                "name": tool["name"],
                "arguments": arguments,
            })
            records = self._extract_records(response)
        except ProviderUnavailableError as exc:
            operation.update({
                "status": "failed",
                "error_type": exc.error_type,
                "tool": exc.tool or operation["tool"],
                "message": str(exc),
            })
            return result

        if not records:
            operation.update({
                "status": "valid_zero_results",
                "error_type": "VALID_ZERO_RESULTS",
                "message": (
                    "The keyword-research tool completed successfully but returned no "
                    f"recognizable rows ({self._response_schema(response)})."
                ),
            })
            return result
        candidate = self._candidate(records[0], 0, "EVERGREEN")
        result.update({
            "available": True,
            "metrics": {
                key: metric.model_dump(mode="json")
                for key, metric in candidate.evidence.items()
            },
            "related_keywords": candidate.related_keywords,
        })
        operation.update({
            "status": "success",
            "error_type": "NONE",
            "message": f"Keyword research returned {len(records)} evidence record(s).",
        })
        return result

    @classmethod
    def _find_keyword_research_tool(
        cls,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        candidates = []
        for tool in tools:
            label = f"{tool.get('name', '')} {tool.get('description', '')}".casefold()
            properties = cls._tool_properties(tool)
            fields = {
                re.sub(r"[^a-z0-9]", "", str(name).casefold())
                for name in properties
            }
            modes = next(
                (
                    definition.get("enum", [])
                    for name, definition in properties.items()
                    if re.sub(r"[^a-z0-9]", "", str(name).casefold()) == "mode"
                    and isinstance(definition, dict)
                ),
                [],
            )
            has_topic_input = bool(fields & {"keyword", "topic", "query"})
            supports_research = not modes or any(
                str(mode).casefold() == "research" for mode in modes
            )
            if (
                has_topic_input
                and supports_research
                and ("keyword" in label or "search volume" in label or "keyword research" in label)
            ):
                candidates.append((2 if "keyword" in label else 1, tool))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    @classmethod
    def _keyword_research_arguments(
        cls,
        tool: dict[str, Any],
        topic: str,
    ) -> dict[str, Any] | None:
        schema = tool.get("inputSchema", {})
        properties = cls._tool_properties(tool)
        required = schema.get("required", []) if isinstance(schema, dict) else []
        arguments: dict[str, Any] = {}
        properties_by_normalized = {
            re.sub(r"[^a-z0-9]", "", str(name).casefold()): name
            for name in properties
        }
        keyword_field = "keyword" if "keyword" in properties_by_normalized else None
        for name, definition in properties.items():
            key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            enum = definition.get("enum", []) if isinstance(definition, dict) else []
            if key == "mode":
                research_mode = next(
                    (item for item in enum if str(item).casefold() == "research"),
                    "research",
                )
                if enum and str(research_mode).casefold() != "research":
                    return None
                arguments[name] = research_mode
            elif key == keyword_field or (
                key in {"topic", "query"} and keyword_field is None
            ):
                arguments[name] = topic
            elif key == "includerelated":
                arguments[name] = True
            elif key == "limit":
                arguments[name] = 5
            elif key == "period":
                selected = next(
                    (item for item in enum if str(item).casefold() == "month"),
                    None,
                )
                if enum and selected is None:
                    if name in required:
                        return None
                elif selected is not None:
                    arguments[name] = selected
            elif key == "language":
                selected = next(
                    (item for item in enum if str(item).casefold() == "en"),
                    None,
                )
                if enum and selected is None:
                    if name in required:
                        return None
                elif selected is not None:
                    arguments[name] = selected
                else:
                    arguments[name] = "en"
            elif definition.get("default") is not None:
                arguments[name] = definition["default"]
            elif name in required:
                return None
        if any(name not in arguments for name in required):
            return None
        return arguments

    def discover_pipeline_candidates(
        self,
        request: TopicDiscoveryRequest,
        *,
        include_competitor_research: bool = True,
    ) -> tuple[list[OpportunityCandidate], dict[str, Any], MarketIntelligenceReport | None]:
        """Gather a bounded, source-aware topic pool before editorial scoring."""
        pool_limit = min(max(request.limit, 15), 30)
        try:
            tools = self._list_tools()
        except ProviderUnavailableError as exc:
            raise ProviderUnavailableError(
                f"Could not list vidIQ tools for multi-source discovery: {exc}"
            ) from exc
        diagnostics: dict[str, Any] = {
            "pool_target": pool_limit,
            "fallback_stages_configured": list(RITZZ_DISCOVERY_FALLBACK_STAGES),
            "sources_attempted": [],
            "sources_unavailable": [],
            "source_counts": {},
            "source_tools": {},
            "duplicate_counts": {},
            "stage_counts": [],
            "operations": [],
            "provider_capabilities": {
                "trending": self._select_trending_tool(tools) is not None,
                "rising": self._select_source_tool(tools, "rising") is not None,
                "evergreen": self._select_source_tool(tools, "evergreen") is not None,
                "long_tail": self._select_source_tool(tools, "long-tail") is not None,
                "competitor_videos": self._find_video_capability_tool(tools, "outliers") is not None,
                "competitor_channel_videos": (
                    self._find_video_capability_tool(tools, "channel_videos") is not None
                ),
            },
        }
        candidates: list[OpportunityCandidate] = []
        seen_topics: set[str] = set()
        competitor_report: MarketIntelligenceReport | None = None

        plan: list[tuple[str, str, TopicDiscoveryRequest]] = []
        unscoped_stage: tuple[str, str, TopicDiscoveryRequest] | None = None
        if request.mode == "TRENDING":
            plan.append(("trending", "TRENDING", request))
            broader_timeframe = self._broader_timeframe(request.timeframe)
            if (
                broader_timeframe != request.timeframe
                and "broader-trending" in RITZZ_DISCOVERY_FALLBACK_STAGES
            ):
                plan.append((
                    "broader-trending",
                    "TRENDING",
                    request.model_copy(update={"timeframe": broader_timeframe}),
                ))
            if "rising" in RITZZ_DISCOVERY_FALLBACK_STAGES:
                plan.append(("rising", "TRENDING", request))
            if "evergreen" in RITZZ_DISCOVERY_FALLBACK_STAGES:
                plan.append((
                    "evergreen",
                    "EVERGREEN",
                    request.model_copy(update={"mode": "EVERGREEN", "trend_topic": None}),
                ))
            if "long-tail" in RITZZ_DISCOVERY_FALLBACK_STAGES:
                plan.append((
                    "long-tail",
                    "EVERGREEN",
                    request.model_copy(update={"mode": "EVERGREEN", "trend_topic": None}),
                ))
            if "unscoped" in RITZZ_DISCOVERY_FALLBACK_STAGES:
                unscoped_stage = (
                    "unscoped-trending",
                    "TRENDING",
                    request.model_copy(update={"trend_topic": None}),
                )
        else:
            plan.append(("evergreen", "EVERGREEN", request))
            if "long-tail" in RITZZ_DISCOVERY_FALLBACK_STAGES:
                plan.append((
                    "long-tail",
                    "EVERGREEN",
                    request.model_copy(update={"mode": "EVERGREEN", "trend_topic": None}),
                ))
            if "unscoped" in RITZZ_DISCOVERY_FALLBACK_STAGES:
                unscoped_stage = (
                    "unscoped-evergreen",
                    "EVERGREEN",
                    request.model_copy(update={"trend_topic": None}),
                )

        def run_source(
            source: str,
            tool_mode: str,
            source_request: TopicDiscoveryRequest,
        ) -> None:
            diagnostics["sources_attempted"].append(source)
            if len(candidates) >= pool_limit:
                diagnostics.setdefault("sources_skipped", []).append(
                    f"{source}: raw candidate pool reached its {pool_limit} target"
                )
                return
            if source == "rising":
                tool = self._select_source_tool(tools, "rising")
            elif source == "evergreen":
                tool = self._select_source_tool(tools, "evergreen")
            elif source == "long-tail":
                tool = self._select_source_tool(tools, "long-tail")
            elif source in {"trending", "broader-trending", "unscoped-trending"}:
                tool = self._select_trending_tool(tools)
            else:
                tool = self._select_tool(tools, tool_mode)
            if tool is None:
                diagnostics["source_tools"][source] = None
                diagnostics["sources_unavailable"].append(
                    f"{source}: no supported vidIQ tool advertised"
                )
                diagnostics["source_counts"][source] = {"raw": 0, "unique": 0}
                diagnostics["operations"].append({
                    "source": source,
                    "tool": "unavailable",
                    "status": "unavailable",
                    "error_type": "CAPABILITY_UNAVAILABLE",
                    "message": "No schema-compatible vidIQ tool was advertised.",
                    "fallback_behavior": "Continue with the next configured secondary source.",
                })
                return
            diagnostics["source_tools"][source] = tool["name"]
            effective_request = source_request.model_copy(
                update={"mode": tool_mode, "limit": pool_limit}
            )
            try:
                arguments = self._arguments(tool, effective_request)
                if source == "rising":
                    arguments = self._rising_arguments(tool, effective_request, arguments)
                result = self._rpc("tools/call", {
                    "name": tool["name"],
                    "arguments": arguments,
                })
                records = self._extract_records(result)
                if not records:
                    raise ProviderUnavailableError(
                        f"vidIQ returned no recognizable records for {source} "
                        f"(response schema: {self._response_schema(result)}).",
                        error_type="VALID_ZERO_RESULTS",
                        tool=str(tool["name"]),
                    )
                accepted = 0
                duplicate_count = 0
                related_raw = 0
                related_unique = 0
                related_duplicate_count = 0
                for index, record in enumerate(records[:pool_limit]):
                    try:
                        candidate = self._candidate(
                            record,
                            index,
                            "EVERGREEN" if source == "evergreen" else "TRENDING",
                        )
                    except ProviderUnavailableError:
                        continue
                    candidate_key = normalize_candidate_key(candidate.topic)
                    if not candidate_key:
                        continue
                    existing = next(
                        (item for item in candidates if normalize_candidate_key(item.topic) == candidate_key),
                        None,
                    )
                    if existing is not None:
                        if source not in existing.discovery_sources:
                            existing.discovery_sources.append(source)
                        duplicate_count += 1
                        continue
                    if any(item.candidate_id == candidate.candidate_id for item in candidates):
                        candidate.candidate_id = f"{source}_{candidate.candidate_id}"
                    candidate.discovery_sources = [source]
                    candidates.append(candidate)
                    seen_topics.add(candidate_key)
                    accepted += 1
                    if len(candidates) >= pool_limit:
                        continue
                    normalized_record = {
                        re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
                        for key, value in record.items()
                    }
                    related_values = [
                        ("related-keyword", normalized_record.get("relatedkeywords")),
                        (
                            "related-question",
                            normalized_record.get("relatedquestions")
                            or normalized_record.get("questions"),
                        ),
                    ]
                    for related_source, values in related_values:
                        if not isinstance(values, list):
                            continue
                        for related_index, value in enumerate(values):
                            if not isinstance(value, str) or not value.strip():
                                continue
                            related_raw += 1
                            related_topic = value.strip()
                            related_key = normalize_candidate_key(related_topic)
                            if not related_key or related_key in seen_topics:
                                related_duplicate_count += 1
                                continue
                            related_candidate = OpportunityCandidate(
                                candidate_id=f"{candidate.candidate_id}_{related_source}_{related_index + 1}",
                                topic=related_topic,
                                primary_keyword=related_topic,
                                opportunity_type=candidate.opportunity_type,
                                provider=self.name,
                                discovery_sources=[f"{source}-{related_source}"],
                                raw_evidence={
                                    "related_to": candidate.topic,
                                    "relation": related_source,
                                    "provider_record": record,
                                },
                            )
                            if any(
                                item.candidate_id == related_candidate.candidate_id
                                for item in candidates
                            ):
                                related_candidate.candidate_id += f"_{index + 1}"
                            candidates.append(related_candidate)
                            seen_topics.add(related_key)
                            related_unique += 1
                            if len(candidates) >= pool_limit:
                                break
                        if len(candidates) >= pool_limit:
                            break
                diagnostics["source_counts"][source] = {
                    "raw": len(records),
                    "unique": accepted,
                }
                diagnostics["duplicate_counts"][source] = duplicate_count
                if related_raw:
                    diagnostics["source_counts"][f"{source}-related"] = {
                        "raw": related_raw,
                        "unique": related_unique,
                    }
                    diagnostics["duplicate_counts"][f"{source}-related"] = related_duplicate_count
                diagnostics["stage_counts"].append({
                    "stage": source,
                    "raw_total": len(records),
                    "pool_unique_total": len(candidates),
                })
                diagnostics["operations"].append({
                    "source": source,
                    "tool": str(tool["name"]),
                    "status": "success",
                    "error_type": "NONE",
                    "message": f"Returned {len(records)} recognizable record(s).",
                    "fallback_behavior": "Continue only if the candidate pool remains below target.",
                })
            except ProviderUnavailableError as exc:
                diagnostics["sources_unavailable"].append(f"{source}: {exc}")
                diagnostics["source_counts"][source] = {"raw": 0, "unique": 0}
                diagnostics["operations"].append({
                    "source": source,
                    "tool": str(tool["name"]),
                    "status": (
                        "valid_zero_results"
                        if exc.error_type == "VALID_ZERO_RESULTS"
                        else "failed"
                    ),
                    "error_type": exc.error_type,
                    "message": str(exc),
                    "fallback_behavior": "Continue with the next configured secondary source.",
                })

        for source, tool_mode, source_request in plan:
            run_source(source, tool_mode, source_request)

        if include_competitor_research and "competitor-outliers" in RITZZ_DISCOVERY_FALLBACK_STAGES:
            diagnostics["sources_attempted"].append("competitor-outliers")
        if (
            include_competitor_research
            and
            "competitor-outliers" in RITZZ_DISCOVERY_FALLBACK_STAGES
            and len(candidates) < pool_limit
        ):
            try:
                competitor_report = self.discover_competitor_research(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=pool_limit,
                )
                raw_videos = len(competitor_report.outliers)
                accepted = 0
                duplicate_count = 0
                for video in competitor_report.outliers:
                    if len(candidates) >= pool_limit:
                        break
                    if (
                        video.relative_performance is None
                        and video.breakout_score is None
                    ):
                        continue
                    topic = video.topic
                    if not topic or topic.casefold() == video.title.casefold():
                        topic = next((item for item in video.topics if item.casefold() != video.title.casefold()), None)
                    if not topic:
                        continue
                    key = normalize_candidate_key(topic)
                    if not key or key in seen_topics:
                        duplicate_count += 1
                        continue
                    candidate = OpportunityCandidate(
                        candidate_id=video.video_id or f"competitor_{len(candidates) + 1:03d}",
                        topic=topic,
                        proposed_title=None,
                        primary_keyword=topic,
                        related_keywords=video.tags,
                        opportunity_type="TREND_TO_EVERGREEN",
                        provider=self.name,
                        discovery_sources=["competitor-outliers"],
                        raw_evidence={"competitor_video": video.model_dump()},
                    )
                    if any(item.candidate_id == candidate.candidate_id for item in candidates):
                        candidate.candidate_id = f"competitor_{candidate.candidate_id}"
                    candidates.append(candidate)
                    seen_topics.add(key)
                    accepted += 1
                diagnostics["source_counts"]["competitor-outliers"] = {
                    "raw": raw_videos,
                    "unique": accepted,
                }
                diagnostics["duplicate_counts"]["competitor-outliers"] = duplicate_count
                diagnostics["stage_counts"].append({
                    "stage": "competitor-outliers",
                    "raw_total": raw_videos,
                    "pool_unique_total": len(candidates),
                })
            except ProviderUnavailableError as exc:
                diagnostics["sources_unavailable"].append(
                    f"competitor-outliers: {exc}"
                )
                diagnostics["source_counts"]["competitor-outliers"] = {
                    "raw": 0,
                    "unique": 0,
                }
        elif (
            include_competitor_research
            and "competitor-outliers" in RITZZ_DISCOVERY_FALLBACK_STAGES
        ):
            try:
                competitor_report = self.discover_competitor_research(
                    f"{request.trend_topic or request.niche} curiosity explainers",
                    limit=pool_limit,
                )
                diagnostics["source_counts"]["competitor-outliers"] = {
                    "raw": len(competitor_report.outliers),
                    "unique": 0,
                }
                diagnostics["duplicate_counts"]["competitor-outliers"] = 0
                diagnostics.setdefault("sources_skipped", []).append(
                    "competitor-outliers: raw candidate pool reached its target; evidence was collected but no fallback candidates were appended"
                )
            except ProviderUnavailableError as exc:
                diagnostics["sources_unavailable"].append(
                    f"competitor-outliers: {exc}"
                )
                diagnostics["source_counts"]["competitor-outliers"] = {
                    "raw": 0,
                    "unique": 0,
                }
                diagnostics["duplicate_counts"]["competitor-outliers"] = 0

        if (
            include_competitor_research
            and "competitor-outliers" not in RITZZ_DISCOVERY_FALLBACK_STAGES
        ):
            diagnostics.setdefault("sources_skipped", []).append(
                "competitor-outliers: disabled by RITZZ_DISCOVERY_FALLBACK_STAGES"
            )
        if unscoped_stage is None and "unscoped" not in RITZZ_DISCOVERY_FALLBACK_STAGES:
            diagnostics.setdefault("sources_skipped", []).append(
                "unscoped: disabled by RITZZ_DISCOVERY_FALLBACK_STAGES"
            )
        if unscoped_stage is not None and len(candidates) < pool_limit:
            run_source(*unscoped_stage)

        diagnostics["pool_unique_total"] = len(candidates)
        return candidates[:pool_limit], diagnostics, competitor_report

    @staticmethod
    def _broader_timeframe(timeframe: str) -> str:
        normalized = timeframe.casefold()
        if "week" in normalized or "day" in normalized:
            return "this month"
        if "month" in normalized:
            return "this year"
        return timeframe

    @staticmethod
    def _select_source_tool(
        tools: list[dict[str, Any]],
        source: str,
    ) -> dict[str, Any] | None:
        if source == "evergreen":
            for tool in tools:
                label = (
                    f"{tool.get('name', '')} {tool.get('description', '')}"
                    .casefold()
                    .replace("_", " ")
                    .replace("-", " ")
                )
                if any(term in label for term in ("keyword research", "evergreen")):
                    return tool
            return None
        if source == "long-tail":
            for tool in tools:
                label = (
                    f"{tool.get('name', '')} {tool.get('description', '')}"
                    .casefold()
                    .replace("_", " ")
                    .replace("-", " ")
                )
                if any(term in label for term in ("long tail", "longtail", "related question")):
                    return tool
            return None
        if source == "rising":
            for tool in tools:
                label = (
                    f"{tool.get('name', '')} {tool.get('description', '')}"
                    .casefold()
                    .replace("_", " ")
                    .replace("-", " ")
                )
                schema = tool.get("inputSchema", {})
                mode_values = (
                    schema.get("properties", {}).get("mode", {}).get("enum", [])
                    if isinstance(schema, dict)
                    else []
                )
                if any(
                    term in label
                    for term in (
                        "rising keyword",
                        "increasing demand",
                        "rising search",
                        "trend discovery",
                    )
                ) or any(str(value).casefold() == "rising" for value in mode_values):
                    return tool
            return None
        return None

    @staticmethod
    def _select_trending_tool(
        tools: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        ranked = []
        for tool in tools:
            label = (
                f"{tool.get('name', '')} {tool.get('description', '')}"
                .casefold()
                .replace("_", " ")
                .replace("-", " ")
            )
            if any(term in label for term in ("trending video", "trend discovery", "trending topic")):
                priority = 2 if "trending video" in label or "trending topic" in label else 1
                ranked.append((priority, tool))
        return max(ranked, key=lambda item: item[0])[1] if ranked else None

    @staticmethod
    def _rising_arguments(
        tool: dict[str, Any],
        request: TopicDiscoveryRequest,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        result = dict(arguments)
        for name in properties:
            key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            if key == "mode":
                enum = properties[name].get("enum", [])
                rising_mode = next(
                    (value for value in enum if str(value).casefold() == "rising"),
                    None,
                )
                if rising_mode is not None:
                    result[name] = rising_mode
            elif key in {"keyword", "query", "searchterm", "searchquery"} and name not in result:
                result[name] = (
                    f"{request.trend_topic} curiosity explainers"
                    if request.trend_topic
                    else f"{request.niche} YouTube topic opportunities"
                )
            elif key in {"topic", "category"} and request.trend_topic:
                result[name] = request.trend_topic
        return result

    def discover_outliers(self, query: str, limit: int = 10) -> MarketIntelligenceReport:
        """Compatibility wrapper for callers that require outlier results."""
        report = self.discover_competitor_research(query, limit)
        if not report.outliers:
            detail = "; ".join(report.warnings) or "No recognizable competitor videos were returned."
            raise ProviderUnavailableError(detail)
        return report

    def discover_competitor_research(
        self,
        query: str,
        limit: int = 10,
    ) -> MarketIntelligenceReport:
        """Inspect configured channels through capabilities advertised by MCP."""
        warnings: list[str] = []
        if not self.api_key:
            report = build_market_intelligence_report(
                query,
                [],
                source="vidIQ MCP",
                performance_tool_available=False,
                warnings=["vidIQ MCP is not configured; competitor research was not requested."],
            )
            report.operations.append({
                "source": "competitor_provider",
                "tool": "vidIQ MCP",
                "status": "failed",
                "error_type": "PROVIDER_UNAVAILABLE",
                "message": "VIDIQ_MCP_API_KEY is not configured.",
                "fallback_behavior": "No competitor metrics are fabricated.",
            })
            return report
        try:
            tools = self._list_tools()
        except ProviderUnavailableError as exc:
            report = build_market_intelligence_report(
                query,
                [],
                source="vidIQ MCP",
                performance_tool_available=False,
                warnings=[f"vidIQ competitor capabilities could not be listed: {exc}"],
            )
            report.operations.append({
                "source": "competitor_tools",
                "tool": "tools/list",
                "status": "failed",
                "error_type": exc.error_type,
                "message": str(exc),
                "fallback_behavior": "No competitor query was attempted.",
            })
            return report
        outlier_tool = self._find_video_capability_tool(tools, "outliers")
        channel_videos_tool = self._find_video_capability_tool(tools, "channel_videos")
        configured_competitors, registry_warnings = self._load_competitor_registry()
        warnings.extend(registry_warnings)
        operations: list[dict[str, str]] = []
        if not configured_competitors:
            message = (
                "No enabled competitor channels are configured; add a channel_id, "
                "channel_handle, or channel_url to "
                f"{self.competitor_registry_path} or set RITZZ_COMPETITORS_FILE."
            )
            warnings.append(message)
            operations.append({
                "source": "competitor_registry",
                "tool": "config/competitors.json",
                "status": "blocked",
                "error_type": "NO_COMPETITORS_CONFIGURED",
                "message": message,
                "fallback_behavior": "The pipeline may try clearly labeled secondary discovery; no competitor evidence is fabricated.",
            })
            report = build_market_intelligence_report(
                query,
                [],
                channels=[],
                source="vidIQ MCP",
                performance_tool_available=outlier_tool is not None,
                warnings=warnings,
            )
            report.configured_competitor_count = 0
            report.operations = operations
            return report

        supported_competitors = configured_competitors
        group_diagnostics: dict[str, dict[str, int]] = {}
        for group in (
            "format_competitors",
            "topic_competitors",
            "emerging_format",
            "core",
            "adjacent",
            "emerging",
        ):
            group_entries = [item for item in configured_competitors if item.get("group") == group]
            if group_entries:
                group_diagnostics[group] = {
                    "configured": len(group_entries),
                    "resolved": 0,
                    "queried": 0,
                    "researched": 0,
                    "videos_inspected": 0,
                    "successful_outliers": 0,
                }
        supported_competitors = self._verify_competitor_metadata(
            tools,
            supported_competitors,
            operations,
            warnings,
            reference_tool=outlier_tool or channel_videos_tool,
        )
        grouped_competitors = self._group_competitors(supported_competitors)
        videos: list[dict[str, Any]] = []
        queried_ids: set[str] = set()
        researched_ids: set[str] = set()
        outlier_error: ProviderUnavailableError | None = None
        if outlier_tool is not None and supported_competitors:
            competitors_by_id = {
                str(item["channel_id"]): item
                for item in supported_competitors
                if item.get("channel_id")
            }
            properties = self._tool_properties(outlier_tool)
            channel_ids_field = next(
                (
                    name for name in properties
                    if re.sub(r"[^a-z0-9]", "", name.casefold()) == "channelids"
                ),
                None,
            )
            channel_id_field = next(
                (
                    name for name in properties
                    if re.sub(r"[^a-z0-9]", "", name.casefold()) == "channelid"
                ),
                None,
            )
            if channel_ids_field or channel_id_field:
                report_limit = min(limit, RITZZ_COMPETITOR_VIDEO_LIMIT)
                group_count = len(grouped_competitors)
                shared_limit, limit_remainder = (
                    divmod(report_limit, group_count)
                    if group_count
                    else (report_limit, 0)
                )
                for group_index, (group, group_entries) in enumerate(grouped_competitors):
                    group_limit = max(
                        1,
                        shared_limit + (1 if group_index < limit_remainder else 0),
                    )
                    max_items = 50
                    if channel_ids_field:
                        definition = properties.get(channel_ids_field, {})
                        if isinstance(definition, dict):
                            try:
                                max_items = max(
                                    1,
                                    min(max_items, int(definition.get("maxItems", 50))),
                                )
                            except (TypeError, ValueError):
                                max_items = 50
                    batch_size = max_items if channel_ids_field else 1
                    for start in range(0, len(group_entries), batch_size):
                        batch_competitors = group_entries[start:start + batch_size]
                        arguments = self._market_arguments(
                            outlier_tool,
                            query,
                            group_limit,
                            competitors=batch_competitors,
                        )
                        if arguments is None:
                            warnings.append(
                                f"Advertised outlier tool '{outlier_tool['name']}' requires "
                                "unsupported arguments for scoped video research."
                            )
                            operations.append({
                                "source": "competitor_outliers",
                                "tool": str(outlier_tool["name"]),
                                "status": "unavailable",
                                "error_type": "UNSUPPORTED_ARGUMENT_SCHEMA",
                                "message": "Required tool fields could not be mapped safely.",
                                "fallback_behavior": "Attempt channel-scoped video-list research.",
                            })
                            break
                        queried_ids.update(
                            f"{group}:{entry['channel_ref']}" for entry in batch_competitors
                        )
                        try:
                            response = self._rpc("tools/call", {
                                "name": outlier_tool["name"],
                                "arguments": arguments,
                            })
                            researched_ids.update(
                                f"{group}:{entry['channel_ref']}"
                                for entry in batch_competitors
                            )
                            batch = self._extract_records(response)
                            for record in batch:
                                record_channel_id = self._record_channel_id(record)
                                matching_competitor = competitors_by_id.get(
                                    str(record_channel_id)
                                )
                                if matching_competitor is not None:
                                    record["channelGroup"] = matching_competitor.get("group")
                                    record.setdefault(
                                        "channelPriority",
                                        matching_competitor.get("priority"),
                                    )
                                    record.setdefault(
                                        "channelRole",
                                        matching_competitor.get("role"),
                                    )
                                elif not record.get("channelGroup"):
                                    record["channelGroup"] = group
                                if matching_competitor is not None:
                                    record.setdefault(
                                        "channelTitle",
                                        matching_competitor.get("name"),
                                    )
                                if len(batch_competitors) == 1:
                                    competitor = batch_competitors[0]
                                    record.setdefault("channelId", competitor["channel_id"])
                                    record.setdefault("channelTitle", competitor.get("name"))
                            videos.extend(batch)
                            operations.append({
                                "source": "competitor_outliers",
                                "tool": str(outlier_tool["name"]),
                                "status": "success" if batch else "valid_zero_results",
                                "error_type": "NONE" if batch else "VALID_ZERO_RESULTS",
                                "message": (
                                    f"Group '{group}' returned {len(batch)} video record(s) "
                                    f"for {len(batch_competitors)} configured channel(s)."
                                ),
                                "fallback_behavior": (
                                    "No fallback required." if batch
                                    else "Try channel-scoped recent/popular video lists."
                                ),
                            })
                        except ProviderUnavailableError as exc:
                            outlier_error = exc
                            operations.append({
                                "source": "competitor_outliers",
                                "tool": str(outlier_tool["name"]),
                                "status": "failed",
                                "error_type": exc.error_type,
                                "message": str(exc),
                                "fallback_behavior": (
                                    "Skip paid fallbacks because vidIQ credits are insufficient."
                                    if exc.error_type == "INSUFFICIENT_CREDITS"
                                    else "Try channel-scoped recent/popular video lists."
                                ),
                            })
                            warnings.append(
                                f"vidIQ competitor outlier operation failed for group "
                                f"'{group}': {exc}"
                            )
                            break
                    if (
                        outlier_error
                        and outlier_error.error_type == "INSUFFICIENT_CREDITS"
                    ):
                        break
            else:
                warnings.append(
                    f"Advertised video-outlier tool '{outlier_tool['name']}' has no "
                    "channel selector; it will not be used for unscoped competitor research."
                )
        elif outlier_tool is None:
            warnings.append("vidIQ MCP does not advertise a video-outlier capability.")

        has_comparable_performance = any(
            video.breakout_score is not None or video.relative_performance is not None
            for video in (normalize_outlier(record) for record in videos)
        )
        if (
            not has_comparable_performance
            and channel_videos_tool is not None
            and not (
                outlier_error
                and outlier_error.error_type == "INSUFFICIENT_CREDITS"
            )
        ):
            for competitor in supported_competitors:
                channel_id = str(competitor["channel_id"])
                call_records = []
                for popular in (False, True):
                    arguments = self._channel_videos_arguments(
                        channel_videos_tool,
                        channel_id,
                        popular=popular,
                    )
                    if arguments is None:
                        warnings.append(
                            f"Advertised channel-video tool '{channel_videos_tool['name']}' "
                            "requires unsupported arguments."
                        )
                        break
                    try:
                        queried_ids.add(
                            f"{competitor.get('group')}:{competitor['channel_ref']}"
                        )
                        response = self._rpc("tools/call", {
                            "name": channel_videos_tool["name"],
                            "arguments": arguments,
                        })
                        researched_ids.add(
                            f"{competitor.get('group')}:{competitor['channel_ref']}"
                        )
                        call_records.extend(self._extract_records(response))
                    except ProviderUnavailableError as exc:
                        operations.append({
                            "source": "competitor_channel_videos",
                            "tool": str(channel_videos_tool["name"]),
                            "status": "failed",
                            "error_type": exc.error_type,
                            "message": str(exc),
                            "fallback_behavior": "Use only outlier data already returned; no views are inferred.",
                        })
                        warnings.append(
                            f"vidIQ channel-video operation failed for "
                            f"{competitor.get('name') or channel_id}: {exc}"
                        )
                        break
                for record in call_records:
                    record.setdefault("channelId", channel_id)
                    record.setdefault("channelTitle", competitor.get("name"))
                    record.setdefault("channelGroup", competitor.get("group"))
                    record.setdefault("channelPriority", competitor.get("priority"))
                    record.setdefault("channelRole", competitor.get("role"))
                videos.extend(call_records)
                group = str(competitor.get("group") or "unknown")
                operations.append({
                    "source": "competitor_channel_videos",
                    "tool": str(channel_videos_tool["name"]),
                    "status": "success" if call_records else "valid_zero_results",
                    "error_type": "NONE" if call_records else "VALID_ZERO_RESULTS",
                    "message": (
                        f"Group '{group}' returned {len(call_records)} recent/popular video record(s) "
                        f"for {competitor.get('name') or channel_id}."
                    ),
                    "fallback_behavior": "Channel baseline is calculated only with sufficient returned metrics.",
                })
        elif (
            not has_comparable_performance
            and channel_videos_tool is not None
            and outlier_error
            and outlier_error.error_type == "INSUFFICIENT_CREDITS"
        ):
            operations.append({
                "source": "competitor_channel_videos",
                "tool": str(channel_videos_tool["name"]),
                "status": "blocked",
                "error_type": "INSUFFICIENT_CREDITS",
                "message": "Skipped paid fallback research because vidIQ reported insufficient credits.",
                "fallback_behavior": "Add vidIQ credits before retrying competitor research.",
            })
        elif videos and supported_competitors:
            channel_by_id = {
                str(entry["channel_id"]): entry for entry in supported_competitors
            }
            for record in videos:
                record_channel_id = self._record_channel_id(record)
                if record_channel_id in channel_by_id:
                    competitor = channel_by_id[record_channel_id]
                    record.setdefault("channelTitle", competitor.get("name"))
                    record.setdefault("channelGroup", competitor.get("group"))

        if outlier_tool is None and channel_videos_tool is None:
            warnings.append(
                "No channel-scoped video research capability is advertised by vidIQ MCP."
            )
        selected_records = self._limit_video_records_by_group(
            self._deduplicate_video_records(videos),
            min(limit, RITZZ_COMPETITOR_VIDEO_LIMIT),
            [group for group, _ in grouped_competitors],
        )
        normalized_videos = [
            normalize_outlier(record)
            for record in selected_records
        ]
        for group, stats in group_diagnostics.items():
            stats["queried"] = sum(
                1 for reference in queried_ids
                if reference.startswith(f"{group}:")
            )
            stats["researched"] = sum(
                1 for reference in researched_ids
                if reference.startswith(f"{group}:")
            )
            stats["resolved"] = sum(
                1 for item in supported_competitors
                if item.get("group") == group
                and (
                    item.get("metadata_status") == "verified"
                    or f"{group}:{item['channel_ref']}" in researched_ids
                )
            )
        for video in normalized_videos:
            group = video.channel_group
            if group is not None:
                stats = group_diagnostics.setdefault(group, {
                    "configured": 0,
                    "queried": 0,
                    "videos_inspected": 0,
                    "successful_outliers": 0,
                })
                stats["videos_inspected"] += 1
                if is_successful_outlier_video(video, RITZZ_OUTLIER_MIN_SCORE):
                    stats["successful_outliers"] += 1
        channel_records = [
            {
                "id": item.get("channel_id"),
                "configured_ref": item.get("channel_ref"),
                "name": item.get("name"),
                "group": item.get("group"),
                "priority": item.get("priority"),
                "role": item.get("role"),
                "reason": item.get("reason"),
                "metadata_status": item.get("metadata_status"),
                "handle": item.get("metadata_handle"),
                "description": item.get("metadata_description"),
                "channel_type": item.get("metadata_channel_type"),
                "faceless": item.get("metadata_faceless"),
            }
            for item in supported_competitors
        ]
        report = build_market_intelligence_report(
            query,
            [video.model_dump(mode="json", by_alias=True) for video in normalized_videos],
            channels=channel_records,
            source="vidIQ MCP",
            performance_tool_available=outlier_tool is not None or bool(videos),
            warnings=warnings,
        )
        report.channels = channel_records
        report.configured_competitor_count = len(configured_competitors)
        report.competitors_queried = len(queried_ids)
        report.videos_inspected = len(report.outliers)
        report.competitor_group_diagnostics = group_diagnostics
        report.operations = operations
        if outlier_error and not report.outliers:
            report.warnings.append(
                "Competitor outlier provider errors were classified separately from valid zero results."
            )
        return report

    def _load_competitor_registry(self) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            payload = json.loads(
                self.competitor_registry_path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return [], [
                f"Competitor registry is unavailable: {self.competitor_registry_path} was not found."
            ]
        except (OSError, json.JSONDecodeError) as exc:
            return [], [f"Competitor registry could not be read: {exc}"]
        if not isinstance(payload, dict):
            return [], ["Competitor registry must be a JSON object."]
        if any(
            key in payload
            for key in ("format_competitors", "topic_competitors", "emerging_format")
        ):
            groups = (
                "format_competitors",
                "topic_competitors",
                "emerging_format",
            )
        else:
            groups = ("core", "adjacent", "emerging")
        competitors = []
        warnings = []
        for group in groups:
            entries = payload.get(group, [])
            if not isinstance(entries, list):
                return [], [f"Competitor registry group '{group}' must be a list."]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("enabled", True) is False:
                    continue
                channel_ref = next(
                    (
                        str(entry[key]).strip()
                        for key in (
                            "channel_id",
                            "channel_handle",
                            "channel_url",
                            "channel",
                            "handle",
                        )
                        if entry.get(key)
                    ),
                    None,
                )
                if not channel_ref:
                    warnings.append(
                        f"Enabled entry in competitor group '{group}' has no "
                        "channel_id, channel_handle, or channel_url; it was skipped."
                    )
                    continue
                reference_type = (
                    "channel_id" if entry.get("channel_id")
                    else "channel_handle" if entry.get("channel_handle") or entry.get("handle")
                    else "channel_url" if entry.get("channel_url")
                    else "channel"
                )
                channel_url_id = re.search(
                    r"(?:youtube\.com/)?channel/(UC[\w-]+)",
                    channel_ref,
                    re.IGNORECASE,
                )
                if reference_type == "channel_url" and channel_url_id:
                    channel_ref = channel_url_id.group(1)
                    reference_type = "channel_id"
                competitors.append({
                    **entry,
                    "channel_id": channel_ref,
                    "channel_ref": channel_ref,
                    "reference_type": reference_type,
                    "group": group,
                })
        return competitors, warnings

    @staticmethod
    def _group_competitors(
        competitors: list[dict[str, Any]],
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for competitor in competitors:
            grouped.setdefault(str(competitor.get("group") or "unknown"), []).append(competitor)
        preferred_order = (
            "format_competitors",
            "topic_competitors",
            "emerging_format",
            "core",
            "adjacent",
            "emerging",
        )
        return [
            (group, grouped.pop(group))
            for group in preferred_order
            if group in grouped
        ] + list(grouped.items())

    @staticmethod
    def _limit_video_records_by_group(
        records: list[dict[str, Any]],
        limit: int,
        group_order: list[str],
    ) -> list[dict[str, Any]]:
        records_by_group: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            group = str(record.get("channelGroup") or "unknown")
            records_by_group.setdefault(group, []).append(record)
        ordered_groups = [
            group for group in group_order if group in records_by_group
        ] + [
            group for group in records_by_group if group not in group_order
        ]
        selected: list[dict[str, Any]] = []
        while len(selected) < limit and ordered_groups:
            remaining_groups = []
            for group in ordered_groups:
                group_records = records_by_group[group]
                if group_records and len(selected) < limit:
                    selected.append(group_records.pop(0))
                if group_records:
                    remaining_groups.append(group)
            ordered_groups = remaining_groups
        return selected

    def _verify_competitor_metadata(
        self,
        tools: list[dict[str, Any]],
        competitors: list[dict[str, Any]],
        operations: list[dict[str, str]],
        warnings: list[str],
        *,
        reference_tool: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        handle_tool = next(
            (
                tool for tool in tools
                if "channel_search" in str(tool.get("name", "")).casefold()
                and any(
                    re.sub(r"[^a-z0-9]", "", str(name).casefold()) == "handle"
                    for name in self._tool_properties(tool)
                )
            ),
            None,
        )
        id_tool = next(
            (
                tool for tool in tools
                if "channel" in str(tool.get("name", "")).casefold()
                and "ids" in str(tool.get("name", "")).casefold()
                and "outlier" not in str(tool.get("name", "")).casefold()
                and any(
                    re.sub(r"[^a-z0-9]", "", str(name).casefold()) == "channelids"
                    for name in self._tool_properties(tool)
                )
            ),
            None,
        )
        verified: list[dict[str, Any]] = []
        id_competitors = [
            competitor for competitor in competitors
            if competitor.get("reference_type") == "channel_id"
        ]
        handle_competitors = [
            competitor for competitor in competitors
            if competitor.get("reference_type") != "channel_id"
        ]
        if id_tool is not None and id_competitors:
            properties = self._tool_properties(id_tool)
            ids_property = next(
                (
                    definition for name, definition in properties.items()
                    if re.sub(r"[^a-z0-9]", "", str(name).casefold()) == "channelids"
                ),
                {},
            )
            try:
                max_items = int(ids_property.get("maxItems", 50)) if isinstance(ids_property, dict) else 50
            except (TypeError, ValueError):
                max_items = 50
            batch_size = max(1, min(max_items, 50))
            for start in range(0, len(id_competitors), batch_size):
                batch = id_competitors[start:start + batch_size]
                arguments = self._channel_metadata_arguments(
                    id_tool,
                    str(batch[0]["channel_ref"]),
                )
                if arguments is not None:
                    ids_field = next(
                        name for name in properties
                        if re.sub(r"[^a-z0-9]", "", str(name).casefold()) == "channelids"
                    )
                    arguments[ids_field] = [str(item["channel_id"]) for item in batch]
                try:
                    if arguments is None:
                        raise ValueError("Channel metadata tool requires unsupported fields.")
                    response = self._rpc("tools/call", {
                        "name": id_tool["name"],
                        "arguments": arguments,
                    })
                    records = self._extract_records(response)
                except (ProviderUnavailableError, ValueError) as exc:
                    for competitor in batch:
                        competitor["metadata_status"] = "provider_error"
                        verified.append(competitor)
                    error_type = (
                        exc.error_type if isinstance(exc, ProviderUnavailableError)
                        else "UNSUPPORTED_ARGUMENT_SCHEMA"
                    )
                    warnings.append(f"vidIQ channel metadata lookup failed: {exc}")
                    operations.append({
                        "source": "competitor_channel_metadata",
                        "tool": str(id_tool["name"]),
                        "status": "failed",
                        "error_type": error_type,
                        "message": str(exc),
                        "fallback_behavior": "Continue with configured canonical IDs and record verification unavailability.",
                    })
                    continue
                records_by_id = {
                    channel_id: record
                    for record in records
                    if (channel_id := self._record_channel_id(record)) is not None
                }
                for competitor in batch:
                    metadata = records_by_id.get(str(competitor["channel_id"]))
                    if metadata is None:
                        competitor["metadata_status"] = "not_found"
                        warnings.append(
                            f"vidIQ returned no channel metadata for configured channel "
                            f"{competitor['channel_ref']}; it was excluded from video research."
                        )
                        continue
                    self._apply_channel_metadata(competitor, metadata)
                    verified.append(competitor)
                operations.append({
                    "source": "competitor_channel_metadata",
                    "tool": str(id_tool["name"]),
                    "status": "success" if records else "valid_zero_results",
                    "error_type": "NONE" if records else "CHANNEL_NOT_FOUND",
                    "message": (
                        f"Returned metadata for {len(records)} of "
                        f"{len(batch)} configured channel(s)."
                    ),
                    "fallback_behavior": "Skip only channels that the metadata lookup confirmed absent.",
                })
        else:
            for competitor in id_competitors:
                competitor["metadata_status"] = "not_available"
                verified.append(competitor)

        for competitor in handle_competitors:
            if reference_tool and self._tool_accepts_channel_references(reference_tool):
                competitor["metadata_status"] = "provider_resolves_reference"
                verified.append(competitor)
                continue
            if handle_tool is None:
                competitor["metadata_status"] = "not_available"
                verified.append(competitor)
                continue
            arguments = self._channel_metadata_arguments(
                handle_tool,
                self._channel_lookup_reference(str(competitor["channel_ref"])),
            )
            if arguments is None:
                competitor["metadata_status"] = "unsupported_schema"
                warnings.append(
                    f"vidIQ channel metadata tool '{handle_tool['name']}' could not safely "
                    f"verify {competitor['channel_ref']}."
                )
                verified.append(competitor)
                continue
            try:
                response = self._rpc("tools/call", {
                    "name": handle_tool["name"],
                    "arguments": arguments,
                })
                records = self._extract_records(response)
            except ProviderUnavailableError as exc:
                competitor["metadata_status"] = "provider_error"
                warnings.append(
                    f"vidIQ channel metadata lookup failed for "
                    f"{competitor['channel_ref']}: {exc}"
                )
                operations.append({
                    "source": "competitor_channel_metadata",
                    "tool": str(handle_tool["name"]),
                    "status": "failed",
                    "error_type": exc.error_type,
                    "message": str(exc),
                    "fallback_behavior": "Use the configured handle/URL directly only where video tools support it.",
                })
                verified.append(competitor)
                continue
            if not records:
                competitor["metadata_status"] = "not_found"
                warnings.append(
                    f"vidIQ returned no channel metadata for configured channel "
                    f"{competitor['channel_ref']}; it was excluded from video research."
                )
                operations.append({
                    "source": "competitor_channel_metadata",
                    "tool": str(handle_tool["name"]),
                    "status": "valid_zero_results",
                    "error_type": "CHANNEL_NOT_FOUND",
                    "message": f"No channel metadata returned for {competitor['channel_ref']}.",
                    "fallback_behavior": "Skip the unverified channel and continue with other groups.",
                })
                continue
            self._apply_channel_metadata(competitor, records[0])
            operations.append({
                "source": "competitor_channel_metadata",
                "tool": str(handle_tool["name"]),
                "status": "success",
                "error_type": "NONE",
                "message": f"Verified configured channel {competitor['channel_ref']}.",
                "fallback_behavior": "Use provider metadata as channel identity evidence.",
            })
            verified.append(competitor)
        return verified

    @classmethod
    def _apply_channel_metadata(
        cls,
        competitor: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        canonical_id = cls._record_channel_id(metadata)
        if canonical_id:
            competitor["channel_id"] = canonical_id
        competitor["metadata_status"] = "verified"
        competitor["metadata_name"] = cls._metadata_value(
            metadata,
            "channelTitle",
            "channelName",
            "title",
            "name",
        )
        competitor["metadata_handle"] = cls._metadata_value(
            metadata,
            "handle",
            "channelHandle",
            "customUrl",
        )
        competitor["metadata_description"] = cls._metadata_value(
            metadata,
            "description",
            "channelDescription",
        )
        competitor["metadata_channel_type"] = cls._metadata_value(
            metadata,
            "channelType",
            "type",
        )
        competitor["metadata_faceless"] = cls._metadata_value(
            metadata,
            "faceless",
            "isFaceless",
        )
        if competitor.get("metadata_name") and not competitor.get("name"):
            competitor["name"] = competitor["metadata_name"]

    @staticmethod
    def _channel_lookup_reference(channel_ref: str) -> str:
        parsed = urlparse(channel_ref)
        if not parsed.netloc.casefold().endswith("youtube.com"):
            return channel_ref
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return channel_ref
        if parts[0].startswith("@"):
            return parts[0]
        if parts[0] in {"c", "user"} and len(parts) > 1:
            return parts[1]
        return channel_ref

    @classmethod
    def _channel_metadata_arguments(
        cls,
        tool: dict[str, Any],
        channel_ref: str,
    ) -> dict[str, Any] | None:
        schema = tool.get("inputSchema", {})
        required = schema.get("required", []) if isinstance(schema, dict) else []
        arguments: dict[str, Any] = {}
        for name, definition in cls._tool_properties(tool).items():
            key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            enum = definition.get("enum", []) if isinstance(definition, dict) else []
            default = definition.get("default") if isinstance(definition, dict) else None
            if key == "handle":
                arguments[name] = channel_ref
            elif key == "handlematch":
                if enum and "exact" not in enum:
                    return None
                arguments[name] = "exact"
            elif key == "channelids":
                arguments[name] = [channel_ref]
            elif key == "channelid":
                arguments[name] = channel_ref
            elif key in {"limit", "maxresults", "count"}:
                arguments[name] = 1
            elif default is not None:
                arguments[name] = default
            elif name in required:
                return None
        return arguments

    @staticmethod
    def _metadata_value(
        record: dict[str, Any],
        *names: str,
    ) -> str | int | float | bool | None:
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
            for key, value in record.items()
        }
        value = next(
            (
                normalized[re.sub(r"[^a-z0-9]", "", name.casefold())]
                for name in names
                if normalized.get(re.sub(r"[^a-z0-9]", "", name.casefold())) is not None
            ),
            None,
        )
        return value if isinstance(value, (str, int, float, bool)) else None

    @staticmethod
    def _tool_properties(tool: dict[str, Any]) -> dict[str, Any]:
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        return properties if isinstance(properties, dict) else {}

    @classmethod
    def _tool_accepts_channel_references(cls, tool: dict[str, Any]) -> bool:
        properties = cls._tool_properties(tool)
        for name, definition in properties.items():
            if re.sub(r"[^a-z0-9]", "", str(name).casefold()) not in {
                "channelid",
                "channelids",
            } or not isinstance(definition, dict):
                continue
            item_schema = definition.get("items", {})
            descriptions = [
                str(tool.get("description", "")),
                str(definition.get("description", "")),
            ]
            if isinstance(item_schema, dict):
                descriptions.append(str(item_schema.get("description", "")))
            description = " ".join(descriptions).casefold()
            if any(term in description for term in ("handle", "username", "channel url", "channel urls")):
                return True
        return False

    @classmethod
    def _find_video_capability_tool(
        cls,
        tools: list[dict[str, Any]],
        capability: str,
    ) -> dict[str, Any] | None:
        matches = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            label = f"{tool.get('name', '')} {tool.get('description', '')}".casefold()
            properties = cls._tool_properties(tool)
            fields = {
                re.sub(r"[^a-z0-9]", "", str(name).casefold())
                for name in properties
            }
            if capability == "outliers":
                has_signal = any(
                    term in label
                    for term in ("outlier", "breakout", "overperform", "viral video")
                )
                has_channel_filter = bool(fields & {"channelids", "channelid"})
                if has_signal and has_channel_filter:
                    matches.append((2 if "outlier" in label else 1, tool))
            elif capability == "channel_videos":
                if (
                    "channel" in label
                    and "video" in label
                    and "channelid" in fields
                    and "videoformat" in fields
                ):
                    matches.append((2 if "popular" in fields else 1, tool))
        return max(matches, key=lambda item: item[0])[1] if matches else None

    @classmethod
    def _market_arguments(
        cls,
        tool: dict[str, Any],
        query: str | None,
        limit: int,
        competitors: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        schema = tool.get("inputSchema", {})
        properties = cls._tool_properties(tool)
        required = schema.get("required", []) if isinstance(schema, dict) else []
        arguments: dict[str, Any] = {}
        channel_ids = [str(item["channel_id"]) for item in competitors if item.get("channel_id")]
        for name, definition in properties.items():
            key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            enum = definition.get("enum", []) if isinstance(definition, dict) else []
            default = definition.get("default") if isinstance(definition, dict) else None
            if key == "channelids" and channel_ids:
                arguments[name] = channel_ids
            elif key == "channelid" and len(channel_ids) == 1:
                arguments[name] = channel_ids[0]
            elif key in {"query", "keyword", "searchterm", "searchquery", "topic", "niche", "category"}:
                if name in required and query is None:
                    return None
                if name in required:
                    arguments[name] = query
            elif key in {"limit", "count", "maxresults", "numresults", "topn"}:
                arguments[name] = limit
            elif key == "minoutlierscore":
                arguments[name] = RITZZ_OUTLIER_MIN_SCORE
            elif key == "publishedwithin":
                preferred = cls._published_within(RITZZ_COMPETITOR_LOOKBACK_DAYS)
                selected = next(
                    (value for value in enum if str(value).casefold() == preferred.casefold()),
                    None,
                )
                if enum and selected is None:
                    if name in required:
                        return None
                else:
                    arguments[name] = selected or preferred
            elif key in {"language", "videotitlelanguage"}:
                selected = next(
                    (value for value in enum if str(value).casefold() == "en"),
                    None,
                )
                if enum and selected is None:
                    if name in required:
                        return None
                else:
                    arguments[name] = selected or "en"
            elif key in {"contenttype", "videotype"}:
                if enum and not any(str(value).casefold() in {"long", "longform"} for value in enum):
                    if name in required:
                        return None
                else:
                    arguments[name] = next(
                        (value for value in enum if str(value).casefold() in {"long", "longform"}),
                        "long",
                    )
            elif key in {"sort", "sortby", "order"}:
                preferred = ("breakoutscore", "outlierscore", "score", "outlier", "breakout")
                selected = next(
                    (value for value in enum if str(value).casefold() in preferred),
                    None,
                )
                if enum and selected is None:
                    if name in required:
                        return None
                else:
                    arguments[name] = selected or "score"
            elif default is not None:
                arguments[name] = default
            elif name in required:
                return None
        return arguments

    @staticmethod
    def _channel_videos_arguments(
        tool: dict[str, Any],
        channel_id: str,
        *,
        popular: bool,
    ) -> dict[str, Any] | None:
        schema = tool.get("inputSchema", {})
        properties = VidiqMcpProvider._tool_properties(tool)
        required = schema.get("required", []) if isinstance(schema, dict) else []
        arguments: dict[str, Any] = {}
        for name, definition in properties.items():
            key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            enum = definition.get("enum", []) if isinstance(definition, dict) else []
            if key == "channelid":
                arguments[name] = channel_id
            elif key in {"videoformat", "contenttype", "videotype"}:
                value = next(
                    (item for item in enum if str(item).casefold() in {"long", "longform"}),
                    "long",
                )
                if enum and value == "long" and not any(
                    str(item).casefold() in {"long", "longform"} for item in enum
                ):
                    return None
                arguments[name] = value
            elif key == "popular":
                arguments[name] = popular
            elif name in required:
                return None
        return arguments

    @staticmethod
    def _published_within(days: int) -> str:
        if days <= 7:
            return "thisWeek"
        if days <= 30:
            return "thisMonth"
        if days <= 90:
            return "threeMonths"
        if days <= 180:
            return "sixMonths"
        if days <= 365:
            return "oneYear"
        return "allTime"

    @staticmethod
    def _record_channel_id(record: dict[str, Any]) -> str | None:
        return next(
            (
                str(value)
                for key, value in record.items()
                if re.sub(r"[^a-z0-9]", "", str(key).casefold()) == "channelid"
                and value is not None
            ),
            None,
        )

    @staticmethod
    def _deduplicate_video_records(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique = []
        records_by_id: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records):
            normalized = {
                re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
                for key, value in record.items()
            }
            key = str(normalized.get("videoid") or normalized.get("id") or "")
            if not key:
                key = f"record:{normalized.get('channelid', '')}:{normalized.get('videotitle', '')}:{index}"
            existing = records_by_id.get(key)
            if existing is not None:
                for name, value in record.items():
                    if existing.get(name) is None and value is not None:
                        existing[name] = value
                continue
            records_by_id[key] = record
            unique.append(record)
        return unique

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if method != "initialize" and not self._initialized:
            self._initialize()
        self._request_id += 1
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "MCP-Protocol-Version": self.protocol_version,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            response = self.session.post(
                self.endpoint,
                headers=headers,
                json={"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderUnavailableError("Could not connect to the vidIQ MCP server.") from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"vidIQ MCP request failed with HTTP {response.status_code}.")
        self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
        payload = self._decode_response(response)
        if "error" in payload:
            raise ProviderUnavailableError(
                "vidIQ MCP returned a JSON-RPC protocol error.",
                error_type="MCP_PROTOCOL_ERROR",
                tool=str(params.get("name")) if params.get("name") else None,
            )
        result = payload.get("result", {})
        if method == "tools/call" and isinstance(result, dict) and result.get("isError") is True:
            tool_name = params.get("name", "unknown")
            error_kind = self._tool_error_kind(result)
            error_type = (
                "INSUFFICIENT_CREDITS"
                if error_kind == "insufficient vidIQ credits"
                else "PROVIDER_ERROR"
            )
            raise ProviderUnavailableError(
                f"vidIQ MCP tool '{tool_name}' reported an execution error "
                f"({error_kind}) "
                f"(response schema: {self._response_schema(result)}).",
                error_type=error_type,
                tool=str(tool_name),
            )
        return result

    def _initialize(self) -> None:
        self._request_id += 1
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            response = self.session.post(
                self.endpoint,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "ritzz-studio", "version": "1.0.0"},
                    },
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderUnavailableError("Could not connect to the vidIQ MCP server.") from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"vidIQ MCP initialization failed with HTTP {response.status_code}.")
        self.session_id = response.headers.get("Mcp-Session-Id")
        payload = self._decode_response(response)
        negotiated = payload.get("result", {}).get("protocolVersion")
        if isinstance(negotiated, str):
            self.protocol_version = negotiated
        headers["MCP-Protocol-Version"] = self.protocol_version
        try:
            initialized_response = self.session.post(
                self.endpoint,
                headers={**headers, **({"Mcp-Session-Id": self.session_id} if self.session_id else {})},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderUnavailableError("vidIQ MCP initialization acknowledgement failed.") from exc
        if initialized_response.status_code >= 400:
            raise ProviderUnavailableError("vidIQ MCP initialization acknowledgement failed.")
        self._initialized = True

    def _decode_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                    except ValueError:
                        continue
            if payload is None:
                raise ProviderUnavailableError("vidIQ MCP returned an unreadable response.")
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("vidIQ MCP returned an invalid JSON-RPC response.")
        return payload

    @staticmethod
    def _select_tool(tools: list[dict[str, Any]], mode: str = "TRENDING") -> dict[str, Any] | None:
        ranked = []
        for tool in tools:
            label = f"{tool.get('name', '')} {tool.get('description', '')}".casefold().replace("_", " ").replace("-", " ")
            trending = any(word in label for word in ("trending video", "trend discovery", "trending topic"))
            rising = any(word in label for word in ("rising keyword", "increasing demand", "rising search"))
            evergreen = "keyword research" in label
            schema = tool.get("inputSchema", {})
            mode_values = schema.get("properties", {}).get("mode", {}).get("enum", [])
            supports_rising = "rising" in mode_values
            if mode == "TRENDING" and trending:
                ranked.append((4 if "trending video" in label or "trending topic" in label else 3, tool))
            elif mode == "TRENDING" and (rising or supports_rising):
                ranked.append((2, tool))
            elif mode == "EVERGREEN" and evergreen:
                ranked.append((1, tool))
        return max(ranked, key=lambda item: item[0])[1] if ranked else None

    @staticmethod
    def _arguments(tool: dict[str, Any], request: TopicDiscoveryRequest) -> dict[str, Any]:
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        result: dict[str, Any] = {}
        for name, definition in properties.items():
            key = name.casefold()
            value_type = definition.get("type")
            enum = definition.get("enum")
            default = definition.get("default")
            if key == "mode":
                desired = "rising" if request.mode == "TRENDING" else "research"
                selected = next(
                    (option for option in enum or [] if str(option).casefold() == desired),
                    desired,
                )
                if enum and selected == desired and desired not in enum:
                    raise ProviderUnavailableError(
                        f"vidIQ tool does not support '{desired}' mode."
                    )
                result[name] = selected
            elif key in {"period", "timeframe", "time_frame", "date_range", "time_range"}:
                value = request.timeframe
                if enum:
                    normalized = re.sub(r"[^a-z0-9]", "", request.timeframe.casefold())
                    if "week" in normalized:
                        preferred = "week"
                    elif "month" in normalized:
                        preferred = "month"
                    elif "day" in normalized or "today" in normalized:
                        preferred = "day"
                    else:
                        preferred = normalized
                    matches = [
                        option
                        for option in enum
                        if preferred
                        in re.sub(r"[^a-z0-9]", "", str(option).casefold())
                    ]
                    if matches:
                        value = matches[0]
                    elif name in required:
                        raise ProviderUnavailableError(
                            f"vidIQ tool does not support requested timeframe '{request.timeframe}'."
                        )
                    else:
                        continue
                result[name] = value
            elif key in {"language", "locale"}:
                language = request.locale.strip()[:2].casefold()
                if enum:
                    selected = next((option for option in enum if str(option).casefold() == language), None)
                    if selected is None and name in required:
                        raise ProviderUnavailableError("vidIQ tool does not support the requested language.")
                    if selected is not None:
                        result[name] = selected
                else:
                    result[name] = language
            elif key == "topic" and request.mode == "TRENDING":
                # vidIQ expects one value from its dynamic availableTopics list.
                # Do not pass the free-form channel niche as though it were a category.
                if request.trend_topic:
                    result[name] = request.trend_topic
                else:
                    continue
            elif key in {"query", "keyword", "search_term", "search_query", "prompt"}:
                if key == "keyword" and request.mode == "TRENDING":
                    continue
                result[name] = f"{request.niche} YouTube topic opportunities"
            elif key in {"niche", "category"} and request.mode == "EVERGREEN":
                result[name] = request.niche
            elif key in {"limit", "count", "num_results", "max_results", "result_count", "number_of_results", "top_n"}:
                result[name] = request.limit
            elif default is not None:
                result[name] = default
            elif name in required:
                raise ProviderUnavailableError(
                    f"vidIQ tool requires the '{name}' argument, but the discovery "
                    "request does not provide a matching value."
                )
            elif value_type in {"boolean", "integer", "number"}:
                # Leave optional tool controls out so vidIQ can apply its default.
                continue
        return result

    @classmethod
    def _extract_records(cls, result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return cls._records_from_value(result)
        for key in ("structuredContent", "structured_content", "data", "result", "output"):
            if key in result:
                records = cls._records_from_value(result[key])
                if records:
                    return records
        for block in result.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                records = cls._records_from_text(block["text"])
                if records:
                    return records
            for key in ("data", "resource", "json"):
                if key in block:
                    records = cls._records_from_value(block[key])
                    if records:
                        return records
        return cls._records_from_value(result)

    @classmethod
    def _records_from_value(cls, value: Any) -> list[dict[str, Any]]:
        """Normalize common MCP result envelopes while preserving provider evidence."""
        topic_fields = {
            "topic", "title", "videotitle", "keyword", "idea", "name", "question",
            "channelid", "channeltitle", "channelname", "videoid",
        }
        if isinstance(value, str):
            return cls._records_from_text(value)
        if isinstance(value, list):
            rows = []
            for item in value:
                if isinstance(item, dict):
                    normalized_keys = {
                        re.sub(r"[^a-z0-9]", "", str(key).casefold()) for key in item
                    }
                    if normalized_keys & topic_fields:
                        rows.append(item)
                    else:
                        rows.extend(cls._records_from_value(item))
                elif isinstance(item, str) and item.strip():
                    rows.append({"keyword": item.strip()})
            return rows
        if not isinstance(value, dict):
            return []

        normalized_keys = {
            re.sub(r"[^a-z0-9]", "", str(key).casefold()) for key in value
        }
        if "videos" in value and isinstance(value["videos"], list):
            return cls._records_from_value(value["videos"])
        if normalized_keys & topic_fields:
            return [value]

        list_keys = {
            "candidates", "channels", "competitors", "keywords", "topics", "ideas", "results", "items", "videos",
            "trends", "trendingvideos", "risingkeywords", "relatedkeywords", "data",
        }
        for key, child in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized_key in list_keys and isinstance(child, list):
                rows = cls._records_from_value(child)
                if rows:
                    return rows
        # Servers may add arbitrary envelope names around their tool payload.
        for key, child in value.items():
            if key in {"content", "_meta", "metadata"}:
                continue
            if isinstance(child, (dict, list, str)):
                rows = cls._records_from_value(child)
                if rows:
                    return rows
        return []

    @classmethod
    def _records_from_text(cls, text: str) -> list[dict[str, Any]]:
        stripped = text.strip()
        if not stripped:
            return []
        unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
        decoder = json.JSONDecoder()
        for candidate_text in (unfenced, stripped):
            try:
                parsed = json.loads(candidate_text)
            except (ValueError, TypeError):
                parsed = None
            if parsed is not None:
                rows = cls._records_from_value(parsed)
                if rows:
                    return rows
        # MCP text often includes a short explanation before an embedded JSON value.
        for index, char in enumerate(unfenced):
            if char not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(unfenced[index:])
            except ValueError:
                continue
            rows = cls._records_from_value(parsed)
            if rows:
                return rows
        return cls._extract_explicit_text_rows(unfenced)

    @staticmethod
    def _extract_explicit_text_rows(text: str) -> list[dict[str, Any]]:
        """Parse explicit Markdown bullets, labeled topics, and result tables."""
        rows: list[dict[str, Any]] = []
        headers: list[str] | None = None
        topic_headers = {"keyword", "topic", "title", "videotitle", "video", "idea", "question"}
        for line in text.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) > 1:
                normalized = [re.sub(r"[^a-z0-9]", "", cell.casefold()) for cell in cells]
                if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                    continue
                if headers is None and any(header in topic_headers for header in normalized):
                    headers = normalized
                    continue
                if headers is not None:
                    values = dict(zip(headers, cells))
                    topic = next((values[key].strip() for key in ("keyword", "topic", "title", "videotitle", "video", "idea", "question") if values.get(key, "").strip()), "")
                    if len(topic) >= 4:
                        row: dict[str, Any] = {"keyword": topic, "provider_text": line.strip()}
                        for key, value in values.items():
                            if value and key not in topic_headers:
                                row[key] = value
                        rows.append(row)
                    continue

            match = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$", line)
            if not match:
                match = re.match(r"^\s*(?:keyword|topic|title)\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
            if not match:
                continue
            original = match.group(1).strip()
            topic = re.sub(r"\*\*([^*]+)\*\*", r"\1", original)
            topic = re.split(r"\s+(?:\||—|–)\s+", topic, maxsplit=1)[0].strip(" *`\t")
            topic = re.sub(r"^\[[^]]+\]\s*", "", topic)
            if len(topic) >= 4 and topic.casefold() not in {"none", "no results", "no trends"}:
                rows.append({"keyword": topic, "provider_text": original})
        return rows

    @staticmethod
    def _extract_markdown_rows(text: str) -> list[dict[str, Any]]:
        """Extract only explicit list entries; retain the original row as evidence."""
        rows = []
        for line in text.splitlines():
            match = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$", line)
            if not match:
                continue
            original = match.group(1).strip()
            topic = re.sub(r"\*\*([^*]+)\*\*", r"\1", original)
            topic = re.split(r"\s+(?:\||—|–)\s+", topic, maxsplit=1)[0].strip(" *`\t")
            topic = re.sub(r"^\[[^]]+\]\s*", "", topic)
            if len(topic) < 4 or topic.casefold() in {"none", "no results", "no trends"}:
                continue
            rows.append({"keyword": topic, "provider_text": original})
        return rows

    @staticmethod
    def _find_record_list(data: dict[str, Any]) -> list[dict[str, Any]]:
        for key, value in data.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized_key in {
                "candidates",
                "keywords",
                "topics",
                "ideas",
                "results",
                "items",
                "videos",
                "trends",
                "trendingvideos",
                "risingkeywords",
                "relatedkeywords",
                "data",
            } and isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if key.casefold() in {"data", "result", "payload"} and isinstance(value, dict):
                nested = VidiqMcpProvider._find_record_list(value)
                if nested:
                    return nested
        return []

    @staticmethod
    def _response_shape(result: Any) -> str:
        """Describe the result schema without exposing topic text or credentials."""
        if not isinstance(result, dict):
            return f"result type={type(result).__name__}"
        keys = sorted(str(key) for key in result if key not in {"content", "_meta"})
        blocks = result.get("content", [])
        details = []
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    details.append(type(block).__name__)
                    continue
                detail = f"{block.get('type', 'unknown')} keys={sorted(str(key) for key in block if key != 'text')}"
                if isinstance(block.get("text"), str):
                    detail += f" {VidiqMcpProvider._text_shape(block['text'])}"
                details.append(detail)
        return f"keys={keys}, content_blocks={details}"

    @staticmethod
    def _response_schema(result: Any) -> str:
        """Summarize response structure for CI diagnostics without logging its values."""
        if not isinstance(result, dict):
            return f"result_type={type(result).__name__}"
        keys = sorted(str(key) for key in result if key not in {"content", "_meta"})
        details = []
        blocks = result.get("content", [])
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    details.append(f"block_type={type(block).__name__}")
                    continue
                detail = f"type={block.get('type', 'unknown')}"
                if isinstance(block.get("text"), str):
                    detail += f" {VidiqMcpProvider._text_schema(block['text'])}"
                details.append(detail)
        return f"keys={keys}, content_blocks={details}"

    @staticmethod
    def _text_schema(text: str) -> str:
        stripped = text.strip()
        summary = f"text_length={len(text)} lines={len(text.splitlines())}"
        try:
            parsed = json.loads(
                re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
            )
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            summary += f" json_keys={sorted(str(key) for key in parsed)}"
        elif isinstance(parsed, list):
            summary += f" json_array_length={len(parsed)}"
        else:
            summary += " content_type=plain_text"
        return summary

    @staticmethod
    def _tool_error_kind(result: dict[str, Any]) -> str:
        text = " ".join(
            block["text"]
            for block in result.get("content", [])
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ).casefold()
        if any(term in text for term in ("not enough credits", "insufficient credits", "no credits")):
            return "insufficient vidIQ credits"
        if any(term in text for term in ("unauthorized", "forbidden", "invalid api key", "invalid credentials", "authentication")):
            return "authentication or access denied"
        if any(term in text for term in ("rate limit", "too many requests", "quota exceeded")):
            return "provider rate or quota limit"
        if any(term in text for term in ("invalid argument", "missing required", "validation error")):
            return "tool argument validation failed"
        return "provider-side tool failure"

    @staticmethod
    def _text_shape(text: str) -> str:
        """Summarize text structure without logging the text itself."""
        stripped = text.strip()
        summary = f"text_length={len(text)} lines={len(text.splitlines())}"
        try:
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
            parsed = json.loads(cleaned)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            summary += f" json_keys={sorted(str(key) for key in parsed)}"
        elif isinstance(parsed, list):
            summary += f" json_array_length={len(parsed)}"
        else:
            lines = text.splitlines()
            list_rows = sum(bool(re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)) for line in lines)
            summary += f" list_rows={list_rows}"
            for line in lines:
                if "|" in line:
                    columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    if len(columns) > 1 and any(
                        re.sub(r"[^a-z0-9]", "", cell.casefold()) in {"keyword", "topic", "title"}
                        for cell in columns
                    ):
                        summary += f" table_columns={columns}"
                        break
        summary += f" excerpt={VidiqMcpProvider._safe_text_excerpt(text)!r}"
        return summary

    @staticmethod
    def _safe_text_excerpt(text: str, limit: int = 300) -> str:
        """Bound response diagnostics and redact common credential formats."""
        excerpt = text[:limit]
        excerpt = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", excerpt)
        excerpt = re.sub(r"(?i)(api[_ -]?key\s*[:=]\s*)\S+", r"\1[REDACTED]", excerpt)
        excerpt = re.sub(r"\b(?:sk[-_]|vidiq_|mcp_)[A-Za-z0-9_-]{12,}\b", "[REDACTED_TOKEN]", excerpt, flags=re.IGNORECASE)
        if len(text) > limit:
            excerpt += "…"
        return excerpt

    @staticmethod
    def _candidate(record: dict[str, Any], index: int, default_type: str = "TRENDING") -> OpportunityCandidate:
        normalized_record = {re.sub(r"[^a-z0-9]", "", str(key).casefold()): value for key, value in record.items()}
        topic = next((normalized_record.get(key) for key in ("topic", "title", "videotitle", "keyword", "idea", "name", "question") if isinstance(normalized_record.get(key), str) and normalized_record[key].strip()), None)
        if not topic:
            raise ProviderUnavailableError("vidIQ candidate record lacked a recognizable topic field.")
        raw_type = str(record.get("opportunity_type", record.get("type", default_type))).upper()
        kind = "TREND_TO_EVERGREEN" if "TREND_TO_EVERGREEN" in raw_type else "EVERGREEN" if "EVERGREEN" in raw_type else "TRENDING"
        evidence: dict[str, EvidenceMetric] = {}
        aliases = {
            "search_volume": ("search_volume", "volume", "monthly_searches", "searchVolume", "monthlySearches", "countryVolume"),
            "keyword_score": ("keyword_score", "overall_score", "score", "keywordScore", "overallScore"),
            "competition": ("competition", "competition_score", "competitionScore"),
            "growth": ("growth", "growth_percent", "trend_growth", "growth_score", "searchDemandGrowthPct", "growthPercent", "growthPct", "volumeChange", "volume_change"),
        }
        for metric, keys in aliases.items():
            value = next((normalized_record.get(re.sub(r"[^a-z0-9]", "", key.casefold())) for key in keys if normalized_record.get(re.sub(r"[^a-z0-9]", "", key.casefold())) is not None), None)
            if value is not None:
                unit = "0-100" if metric == "keyword_score" and isinstance(value, (int, float)) and 0 <= value <= 100 else None
                evidence[metric] = EvidenceMetric(value=value if isinstance(value, (int, float, str)) else str(value), unit=unit, available=True, source="vidIQ MCP")
        keywords = normalized_record.get("relatedkeywords", [])
        questions = normalized_record.get("relatedquestions", normalized_record.get("questions", []))
        candidate_id = str(normalized_record.get("id", f"vidiq_{index + 1:03d}"))
        return OpportunityCandidate(
            candidate_id=candidate_id,
            topic=topic.strip(),
            primary_keyword=normalized_record.get("primarykeyword", normalized_record.get("keyword")),
            related_keywords=[str(item) for item in keywords] if isinstance(keywords, list) else [],
            related_questions=[str(item) for item in questions] if isinstance(questions, list) else [],
            opportunity_type=kind,
            evidence=evidence,
            provider="vidIQ MCP",
            raw_evidence=record,
        )
