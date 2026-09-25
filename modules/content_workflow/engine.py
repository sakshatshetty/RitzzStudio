from dataclasses import dataclass
import inspect
from pathlib import Path

from modules.project import Project, ProjectManager
from modules.project.config import ProductionConfig
from modules.research.models import Research
from modules.research.validation import validate_research
from modules.topic_intelligence.inventory import ContentInventoryEntry, ContentInventoryManager, inventory_path, normalize_topic
from modules.topic_intelligence.models import OpportunityReport, TopicSelection


@dataclass
class ContentWorkflowResult:
    project: Project
    project_path: Path
    selection: TopicSelection


class ContentWorkflow:
    """Run a selected or manual topic through existing Research/Outline/Script engines."""

    def __init__(self, projects_dir: Path, project_manager: ProjectManager | None = None,
                 research_engine=None, outline_engine=None, script_engine=None,
                 inventory_manager: ContentInventoryManager | None = None) -> None:
        self.manager = project_manager or ProjectManager(projects_dir)
        # Lazy imports let unit tests inject fakes without requiring API credentials.
        self.research_engine = research_engine
        self.outline_engine = outline_engine
        self.script_engine = script_engine
        self.inventory_manager = inventory_manager or ContentInventoryManager(inventory_path(Path(projects_dir).parent / "cache" / "topic_intelligence"))

    def run(self, topic: str, report: OpportunityReport | None = None,
            candidate_id: str | None = None, project_id: str | None = None,
            force_refresh: bool = False, target_duration_seconds: int = 480,
            minimum_duration_seconds: int = 480, constraints: list[str] | None = None) -> ContentWorkflowResult:
        topic = topic.strip()
        if not topic:
            raise ValueError("Topic cannot be empty.")
        if report and not candidate_id:
            raise ValueError("A candidate_id is required when selecting from a discovery report.")
        if report and candidate_id and not any(c.candidate_id == candidate_id for c in report.candidates):
            raise ValueError(f"Candidate not found in report: {candidate_id}")
        if project_id is None and self.inventory_manager.find_overlap(topic):
            raise ValueError("Topic overlaps an existing RITZZ inventory entry.")

        project = self.manager.load_project(project_id) if project_id else self.manager.create_project(topic)
        project_path = self.manager.get_project_path(project)
        production_config = ProductionConfig(
            target_duration_seconds=target_duration_seconds,
            minimum_duration_seconds=minimum_duration_seconds,
            constraints=constraints or [],
        )
        (project_path / "production_config.json").write_text(
            production_config.model_dump_json(indent=2), encoding="utf-8"
        )
        selection = TopicSelection(
            report_id=report.report_id if report else None,
            candidate_id=candidate_id,
            topic=topic,
            source="discovery" if report else "manual",
            target_duration_seconds=target_duration_seconds,
            minimum_duration_seconds=minimum_duration_seconds,
            constraints=constraints or [],
            project_id=project.project_id,
        )
        selection_path = project_path / "topic_selection.json"
        selection_path.write_text(selection.model_dump_json(indent=2), encoding="utf-8")
        candidate = next((item for item in report.candidates if item.candidate_id == candidate_id), None) if report else None
        self.inventory_manager.add(ContentInventoryEntry(
            topic=topic,
            normalized_topic=normalize_topic(topic),
            keywords=(candidate.related_keywords if candidate else []),
            project_id=project.project_id,
            status="planned",
            title=candidate.proposed_title if candidate else topic,
            covered_concepts=(candidate.related_questions if candidate else []),
        ))

        research_engine, outline_engine, script_engine = self._engines()
        try:
            research_dir = project_path / "research"
            research_result = self._run_configured(
                research_engine.research,
                topic, research_dir,
                force_refresh=force_refresh,
                production_config=production_config,
            )
            self._complete_if_needed(project.project_id, "research")
            if isinstance(research_result, Research):
                validation = validate_research(research_result)
                validation_path = research_dir / "research_validation.json"
                validation_path.write_text(validation.model_dump_json(indent=2), encoding="utf-8")
                if validation.status == "FAIL":
                    raise ValueError("Research validation failed; inspect research_validation.json before outlining.")
                self._complete_if_needed(project.project_id, "research_validation")

            research_file = research_dir / "research.json"
            outline_dir = project_path / "outline"
            self._run_configured(
                outline_engine.create_outline,
                research_file, outline_dir,
                force_refresh=force_refresh,
                production_config=production_config,
            )
            self._complete_if_needed(project.project_id, "outline")

            script_dir = project_path / "script"
            self._run_configured(
                script_engine.create_script,
                research_file, outline_dir / "outline.json", script_dir,
                force_refresh=force_refresh, production_config=production_config,
            )
            self._complete_if_needed(project.project_id, "script")
        except Exception as exc:
            self.manager.update_status(project.project_id, "content_workflow_failed")
            raise RuntimeError(f"Content workflow failed for project {project.project_id}: {exc}") from exc

        return ContentWorkflowResult(
            project=self.manager.load_project(project.project_id),
            project_path=project_path,
            selection=selection,
        )

    def _engines(self):
        if self.research_engine is None:
            from modules.research.engine import ResearchEngine
            self.research_engine = ResearchEngine()
        if self.outline_engine is None:
            from modules.outline.engine import OutlineEngine
            self.outline_engine = OutlineEngine()
        if self.script_engine is None:
            from modules.script.engine import ScriptEngine
            self.script_engine = ScriptEngine()
        return self.research_engine, self.outline_engine, self.script_engine

    def _complete_if_needed(self, project_id: str, step: str) -> None:
        if not self.manager.load_project(project_id).steps.get(step, False):
            self.manager.complete_step(project_id, step)

    @staticmethod
    def _run_configured(function, *args, **kwargs):
        if "production_config" in inspect.signature(function).parameters:
            return function(*args, **kwargs)
        kwargs.pop("production_config", None)
        return function(*args, **kwargs)
