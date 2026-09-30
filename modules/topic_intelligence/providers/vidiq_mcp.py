"""Official vidIQ MCP provider using runtime tool/schema discovery.

The adapter deliberately inspects MCP tool schemas instead of assuming a
vidIQ-specific HTTP API or hard-coding undocumented tool arguments.
"""

import json
import re
from pathlib import Path
from typing import Any

import requests

from config.settings import (
    RITZZ_DISCOVERY_FALLBACK_STAGES,
    VIDIQ_MCP_API_KEY,
    VIDIQ_MCP_URL,
)
from modules.topic_intelligence.market_intelligence import (
    MarketIntelligenceReport,
    build_market_intelligence_report,
)
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import ProviderUnavailableError


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
        self.protocol_version = "2025-03-26"
        self.competitor_registry_path = Path(
            competitor_registry_path
            or Path(__file__).resolve().parents[3] / "config" / "competitors.json"
        )

    def discover(self, request: TopicDiscoveryRequest) -> list[OpportunityCandidate]:
        if not self.api_key:
            raise ProviderUnavailableError(
                "vidIQ MCP is not configured. Add VIDIQ_MCP_API_KEY to .env "
                "using a vidIQ MCP API key, then retry discovery."
            )
        tools = self._rpc("tools/list", {})
        available = tools.get("tools", []) if isinstance(tools, dict) else []
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

    def discover_pipeline_candidates(
        self,
        request: TopicDiscoveryRequest,
    ) -> tuple[list[OpportunityCandidate], dict[str, Any], MarketIntelligenceReport | None]:
        """Gather a bounded, source-aware topic pool before editorial scoring."""
        pool_limit = min(max(request.limit, 15), 30)
        try:
            tool_result = self._rpc("tools/list", {})
        except ProviderUnavailableError as exc:
            raise ProviderUnavailableError(
                f"Could not list vidIQ tools for multi-source discovery: {exc}"
            ) from exc
        tools = tool_result.get("tools", []) if isinstance(tool_result, dict) else []
        if not isinstance(tools, list):
            raise ProviderUnavailableError("vidIQ MCP tools/list did not return a tool list.")
        diagnostics: dict[str, Any] = {
            "pool_target": pool_limit,
            "fallback_stages_configured": list(RITZZ_DISCOVERY_FALLBACK_STAGES),
            "sources_attempted": [],
            "sources_unavailable": [],
            "source_counts": {},
            "duplicate_counts": {},
            "stage_counts": [],
            "provider_capabilities": {
                "trending": self._select_trending_tool(tools) is not None,
                "rising": self._select_source_tool(tools, "rising") is not None,
                "evergreen": self._select_source_tool(tools, "evergreen") is not None,
                "long_tail": self._select_source_tool(tools, "long-tail") is not None,
                "competitor_videos": self._find_market_tool(tools, {"vidiq_outliers"}) is not None,
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
                diagnostics["sources_unavailable"].append(
                    f"{source}: no supported vidIQ tool advertised"
                )
                diagnostics["source_counts"][source] = {"raw": 0, "unique": 0}
                return
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
                        f"vidIQ returned no recognizable records for {source}."
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
            except ProviderUnavailableError as exc:
                diagnostics["sources_unavailable"].append(f"{source}: {exc}")
                diagnostics["source_counts"][source] = {"raw": 0, "unique": 0}

        for source, tool_mode, source_request in plan:
            run_source(source, tool_mode, source_request)

        if "competitor-outliers" in RITZZ_DISCOVERY_FALLBACK_STAGES:
            diagnostics["sources_attempted"].append("competitor-outliers")
        if (
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
        elif "competitor-outliers" in RITZZ_DISCOVERY_FALLBACK_STAGES:
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

        if "competitor-outliers" not in RITZZ_DISCOVERY_FALLBACK_STAGES:
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
        """Collect competitor channels/videos only through advertised MCP tools."""
        warnings: list[str] = []
        if not self.api_key:
            return build_market_intelligence_report(
                query,
                [],
                source="vidIQ MCP",
                performance_tool_available=False,
                warnings=["vidIQ MCP is not configured; competitor research was not requested."],
            )
        try:
            result = self._rpc("tools/list", {})
        except ProviderUnavailableError as exc:
            return build_market_intelligence_report(
                query,
                [],
                source="vidIQ MCP",
                performance_tool_available=False,
                warnings=[f"vidIQ competitor capabilities could not be listed: {exc}"],
            )
        tools = result.get("tools", []) if isinstance(result, dict) else []
        outlier_tool = self._find_market_tool(tools, {"vidiq_outliers"})
        channel_tool = self._find_market_tool(tools, {"vidiq_similar_channels"})
        configured_competitors, registry_warnings = self._load_competitor_registry()
        warnings.extend(registry_warnings)
        if outlier_tool is None:
            warnings.append("vidIQ MCP does not advertise the vidiq_outliers competitor-video tool.")
        if channel_tool is None:
            warnings.append("vidIQ MCP does not advertise the vidiq_similar_channels channel tool.")

        channels: list[dict[str, Any]] = []
        videos: list[dict[str, Any]] = []
        if channel_tool is not None:
            arguments = self._market_arguments(channel_tool, query, limit)
            if arguments is None:
                warnings.append("The advertised vidIQ similar-channel tool requires unsupported arguments.")
            else:
                try:
                    response = self._rpc("tools/call", {
                        "name": channel_tool["name"],
                        "arguments": arguments,
                    })
                    channels = self._extract_records(response)
                except ProviderUnavailableError as exc:
                    warnings.append(f"vidIQ similar-channel research failed: {exc}")
        if outlier_tool is not None:
            channel_schema = outlier_tool.get("inputSchema", {})
            properties = channel_schema.get("properties", {}) if isinstance(channel_schema, dict) else {}
            channel_fields = {
                re.sub(r"[^a-z0-9]", "", str(name).casefold())
                for name in properties
            } & {"channel", "channelid", "channelhandle", "channelurl"}
            can_scope_channels = bool(channel_fields)
            scopes = (
                [(entry, entry.get("group")) for entry in configured_competitors]
                if configured_competitors and can_scope_channels
                else [(None, None)]
            )
            if configured_competitors and not can_scope_channels:
                warnings.append(
                    "Configured competitor channels were not individually queried because "
                    "the advertised vidIQ outlier schema has no channel selector."
                )
            for competitor, group in scopes:
                arguments = self._market_arguments(
                    outlier_tool,
                    query,
                    limit,
                    competitor=competitor,
                )
                if arguments is None:
                    warnings.append("The advertised vidIQ outlier tool requires unsupported arguments.")
                    continue
                try:
                    response = self._rpc("tools/call", {
                        "name": outlier_tool["name"],
                        "arguments": arguments,
                    })
                    batch = self._extract_records(response)
                    if competitor is not None:
                        for record in batch:
                            record.setdefault("channelGroup", group)
                            record.setdefault(
                                "channelId",
                                competitor.get("channel_id")
                                or competitor.get("channel")
                                or competitor.get("handle"),
                            )
                            record.setdefault("channelTitle", competitor.get("name"))
                    videos.extend(batch)
                except ProviderUnavailableError as exc:
                    scope_name = (
                        competitor.get("name") or competitor.get("channel_id")
                        if competitor
                        else "topic query"
                    )
                    warnings.append(f"vidIQ competitor-video research failed for {scope_name}: {exc}")

        return build_market_intelligence_report(
            query,
            videos[:limit],
            channels=channels,
            source="vidIQ MCP",
            performance_tool_available=outlier_tool is not None,
            warnings=warnings,
        )

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
        competitors = []
        for group in ("core", "adjacent", "emerging"):
            entries = payload.get(group, [])
            if not isinstance(entries, list):
                return [], [f"Competitor registry group '{group}' must be a list."]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("enabled", True) is False:
                    continue
                if not any(entry.get(key) for key in ("channel_id", "channel", "handle")):
                    continue
                competitors.append({**entry, "group": group})
        return competitors, []

    @staticmethod
    def _find_market_tool(
        tools: list[dict[str, Any]],
        names: set[str],
    ) -> dict[str, Any] | None:
        return next(
            (
                tool for tool in tools
                if isinstance(tool, dict)
                and str(tool.get("name", "")).casefold() in names
            ),
            None,
        )

    @staticmethod
    def _market_arguments(
        tool: dict[str, Any],
        query: str,
        limit: int,
        competitor: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        arguments: dict[str, Any] = {}
        for name, definition in properties.items():
            key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            enum = definition.get("enum", []) if isinstance(definition, dict) else []
            default = definition.get("default") if isinstance(definition, dict) else None
            if key in {"channel", "channelid", "channelhandle", "channelurl"} and competitor:
                arguments[name] = (
                    competitor.get("channel_id")
                    or competitor.get("handle")
                    or competitor.get("channel")
                )
            elif key in {"query", "keyword", "searchterm", "searchquery", "topic", "niche", "category"}:
                arguments[name] = query
            elif key in {"limit", "count", "maxresults", "numresults", "topn"}:
                arguments[name] = limit
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
                if enum and not any(str(value).casefold() in {"score", "outlier", "breakout"} for value in enum):
                    if name in required:
                        return None
                else:
                    arguments[name] = next(
                        (value for value in enum if str(value).casefold() in {"score", "outlier", "breakout"}),
                        "score",
                    )
            elif default is not None:
                arguments[name] = default
            elif name in required:
                return None
        return arguments

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
            raise ProviderUnavailableError(f"vidIQ MCP error: {payload['error'].get('message', 'request failed')}")
        return payload.get("result", {})

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
