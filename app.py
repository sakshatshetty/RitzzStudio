from pathlib import Path

from config import PROJECTS_DIR, VIDIQ_MCP_API_KEY
from modules.content_workflow import ContentWorkflow
from modules.topic_intelligence.engine import TopicIntelligenceEngine
from modules.topic_intelligence.market_intelligence import top_outliers
from modules.topic_intelligence.models import TopicDiscoveryRequest
from modules.topic_intelligence.providers.base import ProviderUnavailableError
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider


def _manual_topic() -> str:
    return input("Enter video topic:\n> ").strip()


def _print_outlier(index: int, video) -> None:
    views = f"{video.views:,}" if video.views is not None else "unavailable"
    breakout = f"{video.breakout_score:.1f}" if video.breakout_score is not None else "unavailable"
    print(f"{index}. {video.title}")
    print(f"   Channel: {video.channel_title or 'unknown'}")
    print(f"   Views: {views} | Breakout score: {breakout}")
    print("   Signal: competitor success example, not a guaranteed RITZZ result")


def _print_candidate(index: int, candidate) -> None:
    score = f"{candidate.opportunity_score}/100" if candidate.opportunity_score is not None else "unscored (insufficient normalized signals)"
    print(f"{index}. [{candidate.opportunity_type}] {candidate.topic} — {score}")
    print(f"   Validation: {candidate.validation_status}")
    if candidate.editorial_status:
        print(f"   RITZZ editorial fit: {candidate.editorial_status}")
    if candidate.primary_keyword:
        print(f"   Keyword: {candidate.primary_keyword}")
    print(f"   Evidence coverage: {candidate.score_completeness:.0%}")
    for name, metric in candidate.evidence.items():
        print(f"   {name.replace('_', ' ').title()}: {metric.value} {metric.unit or ''}".rstrip())
    if candidate.rationale:
        print(f"   Notes: {'; '.join(candidate.rationale[:3])}")
    if candidate.filter_reasons:
        print(f"   Review: {'; '.join(candidate.filter_reasons[:3])}")
    if candidate.validation_reasons:
        print(f"   Gate: {'; '.join(candidate.validation_reasons[:3])}")


def main() -> None:
    print("=" * 50)
    print("              RITZZ STUDIO")
    print("=" * 50)
    print("1. Discover trending topics with vidIQ")
    print("2. Find successful competitor videos")
    print("3. Enter a topic manually")
    mode = input("> ").strip()
    report = None
    candidate_id = None
    topic = ""
    target_duration_seconds = 480
    minimum_duration_seconds = 480
    constraints = []

    if mode == "1":
        if not VIDIQ_MCP_API_KEY:
            print("Live vidIQ discovery is not configured.")
            print("Add VIDIQ_MCP_API_KEY to .env using a vidIQ MCP API key.")
            print("You can still enter a topic manually.")
            mode = "3"
        else:
            timeframe = input("Trend timeframe [this week/this month]: ").strip() or "this week"
            opportunity_mode = input("Topic type: 1 trending, 2 evergreen [1]: ").strip()
            opportunity_mode = "EVERGREEN" if opportunity_mode == "2" else "TRENDING"
            trend_topic = None
            if opportunity_mode == "TRENDING":
                category = input(
                    "vidIQ rising category [history; enter ALL for unscoped trends]: "
                ).strip()
                trend_topic = None if category.casefold() == "all" else category or "history"
            print("Discovery uses one vidIQ MCP tool call and one OpenAI editorial assessment.")
            try:
                report = TopicIntelligenceEngine().discover(
                    TopicDiscoveryRequest(
                        timeframe=timeframe,
                        mode=opportunity_mode,
                        trend_topic=trend_topic,
                    )
                )
            except ProviderUnavailableError as exc:
                print(f"Topic discovery unavailable: {exc}")
                print("You can continue by entering a topic manually.")
                mode = "3"

    if mode == "2":
        if not VIDIQ_MCP_API_KEY:
            print("Live vidIQ discovery is not configured.")
            mode = "3"
        else:
            query = input(
                "RITZZ topic family [history mysteries science curiosity]: "
            ).strip() or "history mysteries science curiosity"
            try:
                market_report = VidiqMcpProvider().discover_outliers(query, limit=10)
                report_path = Path("cache") / "topic_intelligence" / "market_intelligence.json"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(market_report.model_dump_json(indent=2), encoding="utf-8")
                selected_outliers = top_outliers(market_report, limit=3)
                print(f"\nTop competitor success examples for: {query}")
                for index, video in enumerate(selected_outliers, start=1):
                    _print_outlier(index, video)
                print("\nChoose an idea number, or type M to enter a different topic.")
                choice = input("> ").strip()
                if choice.casefold() == "m":
                    topic = _manual_topic()
                else:
                    try:
                        topic = selected_outliers[int(choice) - 1].title
                    except (ValueError, IndexError):
                        print("Invalid idea selection.")
                        return
            except ProviderUnavailableError as exc:
                print(f"Competitor research unavailable: {exc}")
                mode = "3"
    if mode == "3":
        topic = _manual_topic()
    elif report:
        print(f"\nCandidates from {report.provider} ({report.created_at}):")
        for warning in report.warnings:
            print(f"Note: {warning}")
        for index, candidate in enumerate(report.candidates, start=1):
            _print_candidate(index, candidate)
        print("\nChoose a candidate number, or type M to enter a different topic.")
        choice = input("> ").strip()
        if choice.casefold() == "m":
            topic = _manual_topic()
            report = None
        else:
            try:
                selected = report.candidates[int(choice) - 1]
            except (ValueError, IndexError):
                print("Invalid candidate selection.")
                return
            topic = input(f"Confirm or edit topic [{selected.topic}]: ").strip() or selected.topic
            candidate_id = selected.candidate_id if topic == selected.topic else None
            if candidate_id is None:
                # An edited title is still traceable to the user's chosen discovery candidate.
                candidate_id = selected.candidate_id

    if not topic:
        print("Topic cannot be empty.")
        return

    try:
        target_duration_seconds = int(input("Target video duration in seconds [480]: ").strip() or "480")
        minimum_duration_seconds = int(input("Minimum allowed duration in seconds [480]: ").strip() or "480")
        constraints_text = input("Optional constraints, comma-separated [none]: ").strip()
        constraints = [item.strip() for item in constraints_text.split(",") if item.strip()]
    except ValueError:
        print("Duration values must be whole numbers of seconds.")
        return
    if minimum_duration_seconds > target_duration_seconds:
        print("Minimum duration cannot exceed target duration.")
        return

    try:
        result = ContentWorkflow(Path(PROJECTS_DIR)).run(
            topic=topic,
            report=report,
            candidate_id=candidate_id,
            target_duration_seconds=target_duration_seconds,
            minimum_duration_seconds=minimum_duration_seconds,
            constraints=constraints,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Content workflow failed: {exc}")
        return

    print("\nContent preparation complete.")
    print(f"Project ID: {result.project.project_id}")
    print(f"Topic: {result.project.title}")
    print(f"Project path: {result.project_path}")
    print(f"Status: {result.project.status}")
    print("Completed: Research → Outline → Script")


if __name__ == "__main__":
    main()
