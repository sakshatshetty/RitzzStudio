"""Official vidIQ MCP provider using runtime tool/schema discovery.

The adapter deliberately inspects MCP tool schemas instead of assuming a
vidIQ-specific HTTP API or hard-coding undocumented tool arguments.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any

import requests

from config.settings import VIDIQ_MCP_API_KEY, VIDIQ_MCP_URL
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.market_intelligence import MarketIntelligenceReport, normalize_outlier
from modules.topic_intelligence.providers.base import ProviderUnavailableError


class VidiqMcpProvider:
    name = "vidiq_mcp"

    def __init__(self, endpoint: str = VIDIQ_MCP_URL, api_key: str | None = VIDIQ_MCP_API_KEY,
                 timeout: float = 30, session: requests.Session | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session_id: str | None = None
        self._request_id = 0
        self._initialized = False
        self.protocol_version = "2025-03-26"

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

    def discover_outliers(self, query: str, limit: int = 10) -> MarketIntelligenceReport:
        """Find long-form videos that outperform their channel baseline."""
        if not self.api_key:
            raise ProviderUnavailableError(
                "vidIQ MCP is not configured. Add VIDIQ_MCP_API_KEY before competitor research."
            )
        result = self._rpc("tools/call", {
            "name": "vidiq_outliers",
            "arguments": {
                "keyword": query,
                "contentType": "long",
                "sort": "score",
                "limit": limit,
            },
        })
        records = self._extract_records(result)
        if not records:
            raise ProviderUnavailableError("vidIQ returned no recognizable outlier videos.")
        outliers = [normalize_outlier(record) for record in records[:limit]]
        return MarketIntelligenceReport(
            query=query,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            outliers=outliers,
        )

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
            trending = any(word in label for word in ("rising keyword", "trending video", "trend discovery", "trending topic"))
            evergreen = "keyword research" in label
            schema = tool.get("inputSchema", {})
            mode_values = schema.get("properties", {}).get("mode", {}).get("enum", [])
            supports_rising = "rising" in mode_values
            if mode == "TRENDING" and trending:
                ranked.append((3 if supports_rising else 2 if "rising keyword" in label or "trend discovery" in label else 1, tool))
            elif mode == "TRENDING" and supports_rising:
                ranked.append((3, tool))
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
                if enum and desired not in enum:
                    raise ProviderUnavailableError(
                        f"vidIQ tool does not support '{desired}' mode."
                    )
                result[name] = desired
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
        topic_fields = {"topic", "title", "videotitle", "keyword", "idea", "name", "question"}
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
            "candidates", "keywords", "topics", "ideas", "results", "items", "videos",
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
