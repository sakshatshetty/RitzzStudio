import json

import pytest

from modules.content_workflow.engine import ContentWorkflow
from modules.research.models import KeyFact, Research, Source
from modules.project.config import ProductionConfig
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)


class FakeResearch:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail

    def research(self, topic, directory, force_refresh=False):
        self.events.append("research")
        (directory).mkdir(exist_ok=True)
        (directory / "research.json").write_text("{}")
        if self.fail:
            raise RuntimeError("research failed")


class FakeOutline:
    def __init__(self, events):
        self.events = events

    def create_outline(self, research_file, directory, force_refresh=False):
        self.events.append("outline")
        directory.mkdir(exist_ok=True)
        (directory / "outline.json").write_text("{}")


class FakeScript:
    def __init__(self, events):
        self.events = events

    def create_script(self, research_file, outline_file, directory, force_refresh=False):
        self.events.append("script")
        directory.mkdir(exist_ok=True)
        (directory / "script.json").write_text("{}")


class ValidatingResearch:
    def __init__(self, events, status="PASS"):
        self.events = events
        self.status = status

    def research(self, topic, directory, force_refresh=False):
        self.events.append("research")
        result = Research(
            topic=topic,
            category="Science",
            core_question=topic,
            short_answer="An answer.",
            key_facts=[KeyFact(
                fact="Supported fact.", importance="high", confidence="high", sources=["source_001"]
            )],
            sources=[Source(
                id="source_001", title="Source", url="https://example.com", publisher="Example",
                relevance="Supports the fact.", tier="2", source_type="journalism"
            )] if self.status == "PASS" else [],
        )
        directory.mkdir(exist_ok=True)
        (directory / "research.json").write_text(result.model_dump_json())
        return result


def workflow(tmp_path, events, research=None):
    return ContentWorkflow(
        tmp_path / "projects",
        research_engine=research or FakeResearch(events),
        outline_engine=FakeOutline(events),
        script_engine=FakeScript(events),
    )


def test_manual_topic_runs_existing_stages_in_order_and_records_status(tmp_path):
    events = []
    result = workflow(tmp_path, events).run("Why do cats purr?")
    assert events == ["research", "outline", "script"]
    assert result.project.steps["research"] is True
    assert result.project.steps["outline"] is True
    assert result.project.steps["script"] is True
    assert result.selection.source == "manual"
    assert json.loads((result.project_path / "topic_selection.json").read_text())["topic"] == "Why do cats purr?"


def test_selection_persists_duration_and_constraints(tmp_path):
    events = []
    result = workflow(tmp_path, events).run(
        "Why do owls hunt at night?",
        target_duration_seconds=360,
        minimum_duration_seconds=300,
        constraints=["keep it family friendly", "use historical sources"],
    )
    saved = json.loads((result.project_path / "topic_selection.json").read_text())
    assert saved["target_duration_seconds"] == 360
    assert saved["minimum_duration_seconds"] == 300
    assert saved["constraints"] == ["keep it family friendly", "use historical sources"]
    assert saved["locked_at"]
    config = json.loads((result.project_path / "production_config.json").read_text())
    assert config["target_duration_seconds"] == 360
    assert config["minimum_duration_seconds"] == 300


def test_duplicate_manual_topic_is_rejected(tmp_path):
    events = []
    first = workflow(tmp_path, events).run("Why do cats purr?")
    with pytest.raises(ValueError, match="overlaps"):
        workflow(tmp_path, events).run("Why Do Cats Purr?")


def test_selected_candidate_is_linked_to_report_and_project(tmp_path):
    events = []
    candidate = OpportunityCandidate(candidate_id="c1", topic="Why do cats purr?", provider="fixture")
    report = OpportunityReport(report_id="r1", request=TopicDiscoveryRequest(), provider="fixture", candidates=[candidate])
    result = workflow(tmp_path, events).run(candidate.topic, report=report, candidate_id="c1")
    assert result.selection.source == "discovery"
    assert result.selection.report_id == "r1"
    saved = json.loads((result.project_path / "topic_selection.json").read_text())
    assert saved["candidate_id"] == "c1"
    assert saved["project_id"] == result.project.project_id


def test_candidate_must_belong_to_report(tmp_path):
    candidate = OpportunityCandidate(candidate_id="c1", topic="Topic", provider="fixture")
    report = OpportunityReport(report_id="r1", request=TopicDiscoveryRequest(), provider="fixture", candidates=[candidate])
    with pytest.raises(ValueError, match="Candidate not found"):
        workflow(tmp_path, []).run("Topic", report=report, candidate_id="missing")


def test_failed_stage_preserves_completed_work_and_marks_failure(tmp_path):
    events = []
    bad_research = FakeResearch(events, fail=True)
    app = workflow(tmp_path, events, research=bad_research)
    with pytest.raises(RuntimeError, match="research failed"):
        app.run("Topic")
    project = app.manager.load_project(next((tmp_path / "projects").iterdir()).name[:12])
    assert project.status == "content_workflow_failed"
    assert project.steps["research"] is False
    assert events == ["research"]


def test_configured_duration_reaches_research_outline_and_script(tmp_path):
    events = []
    configs = {}

    class TrackingResearch:
        def research(self, topic, directory, force_refresh=False, production_config=None):
            configs["research"] = production_config
            events.append("research")
            result = Research(
                topic=topic,
                category="Science",
                core_question=topic,
                short_answer="An answer.",
                key_facts=[KeyFact(
                    fact="Supported fact.", importance="high", confidence="high", sources=["source_001"]
                )],
                sources=[Source(
                    id="source_001", title="Source", url="https://example.com", publisher="Example",
                    relevance="Supports the fact.", tier="2", source_type="journalism"
                )],
            )
            directory.mkdir(exist_ok=True)
            (directory / "research.json").write_text(result.model_dump_json())
            return result

    class TrackingOutline(FakeOutline):
        def create_outline(self, research_file, directory, force_refresh=False, production_config=None):
            configs["outline"] = production_config
            super().create_outline(research_file, directory, force_refresh)

    class TrackingScript(FakeScript):
        def create_script(self, research_file, outline_file, directory, force_refresh=False, production_config=None):
            configs["script"] = production_config
            super().create_script(research_file, outline_file, directory, force_refresh)

    result = ContentWorkflow(
        tmp_path / "projects",
        research_engine=TrackingResearch(),
        outline_engine=TrackingOutline(events),
        script_engine=TrackingScript(events),
    ).run(
        "Why do owls hunt at night?",
        target_duration_seconds=300,
        minimum_duration_seconds=240,
        constraints=["family friendly"],
    )

    assert events == ["research", "outline", "script"]
    assert all(isinstance(configs[name], ProductionConfig) for name in configs)
    assert all(configs[name].target_duration_seconds == 300 for name in configs)
    assert result.project.steps["script"] is True


def test_failed_research_validation_stops_before_outline(tmp_path):
    events = []
    app = workflow(tmp_path, events, research=ValidatingResearch(events, status="FAIL"))
    with pytest.raises(RuntimeError, match="Research validation failed"):
        app.run("A topic")
    assert events == ["research"]
    project_path = next((tmp_path / "projects").iterdir())
    assert (project_path / "research" / "research_validation.json").exists()
