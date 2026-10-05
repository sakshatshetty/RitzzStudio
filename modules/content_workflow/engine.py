import inspect
import json
from dataclasses import dataclass
from pathlib import Path

from modules.outline.models import Outline
from modules.project import Project, ProjectManager
from modules.project.config import ProductionConfig
from modules.project.packaging import PackagingArtifact, PackagingEngine
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult
from modules.research.models import Research
from modules.research.validation import validate_research
from modules.script.models import Script
from modules.topic_intelligence.inventory import (
    ContentInventoryEntry,
    ContentInventoryManager,
    inventory_path,
    normalize_topic,
)
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
                 inventory_manager: ContentInventoryManager | None = None,
                 packaging_engine: PackagingEngine | None = None) -> None:
        self.manager = project_manager or ProjectManager(projects_dir)
        # Lazy imports let unit tests inject fakes without requiring API credentials.
        self.research_engine = research_engine
        self.outline_engine = outline_engine
        self.script_engine = script_engine
        self.packaging_engine = packaging_engine or PackagingEngine(projects_dir)
        self.inventory_manager = inventory_manager or ContentInventoryManager(inventory_path(Path(projects_dir).parent / "cache" / "topic_intelligence"))

    def run(self, topic: str, report: OpportunityReport | None = None,
            candidate_id: str | None = None, project_id: str | None = None,
            force_refresh: bool = False, target_duration_seconds: int = 480,
            minimum_duration_seconds: int = 480, constraints: list[str] | None = None,
            force_refresh_research: bool = False,
            ) -> ContentWorkflowResult:
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
        candidate = next((item for item in report.candidates if item.candidate_id == candidate_id), None) if report else None
        selection = selection.model_copy(update={
            "angle": candidate.angle if candidate else None,
            "source_evidence": {
                "discovery_sources": candidate.discovery_sources,
                "raw_evidence": candidate.raw_evidence,
            } if candidate else {},
            "trend_evidence": {
                key: metric.model_dump(mode="json")
                for key, metric in candidate.current_vidiq_demand_signals.items()
            } if candidate else {},
            "competitor_evidence": [
                item.model_dump(mode="json")
                for item in candidate.competitor_evidence
            ] if candidate else [],
            "ritzz_fit": (
                candidate.ritzz_fit.model_dump(mode="json")
                if candidate and candidate.ritzz_fit
                else None
            ),
        })
        selection_path = project_path / "topic_selection.json"
        selection_path.write_text(selection.model_dump_json(indent=2), encoding="utf-8")
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
        current_stage = "research"
        qa_recorded = False
        try:
            research_dir = project_path / "research"
            research_result = self._run_configured(
                research_engine.research,
                topic, research_dir,
                force_refresh=force_refresh or force_refresh_research,
                production_config=production_config,
            )
            self._complete_if_needed(project.project_id, "research")
            if isinstance(research_result, Research):
                validation = validate_research(research_result)
                validation_path = research_dir / "research_validation.json"
                validation_path.write_text(validation.model_dump_json(indent=2), encoding="utf-8")
                validation_findings = list(validation.issues)
                validation_findings.extend(
                    f"{claim.claim}: {issue}"
                    for claim in validation.claims
                    for issue in claim.issues
                )
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage="research",
                        status=validation.status,
                        checks={"claim_source_coverage": validation.status},
                        findings=validation_findings,
                        recommendations=(
                            ["Resolve unsupported important claims before continuing."]
                            if validation.status == "FAIL"
                            else ["Use cautious wording for claims marked REVIEW."]
                            if validation.status == "REVIEW"
                            else []
                        ),
                    ),
                )
                qa_recorded = True
                if validation.status == "FAIL":
                    raise ValueError("Research validation failed; inspect research_validation.json before outlining.")
                self._complete_if_needed(project.project_id, "research_validation")

            research_file = research_dir / "research.json"
            outline_dir = project_path / "outline"
            current_stage = "outline"
            qa_recorded = False
            outline_result = self._run_configured(
                outline_engine.create_outline,
                research_file, outline_dir,
                force_refresh=force_refresh,
                production_config=production_config,
            )
            if isinstance(outline_result, Outline):
                section_total = sum(section.estimated_seconds for section in outline_result.sections)
                section_sum_ok = section_total == outline_result.total_estimated_seconds
                duration_ok = (
                    production_config.minimum_acceptable_duration_seconds
                    <= section_total
                    <= production_config.maximum_acceptable_duration_seconds
                )
                outline_status = "PASS" if section_sum_ok and duration_ok else "FAIL"
                findings = []
                if not section_sum_ok:
                    findings.append("Section durations do not sum to the reported outline duration.")
                if not duration_ok:
                    findings.append(
                        "Outline duration is outside the configured minimum and "
                        "±60-second target range."
                    )
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage="outline",
                        status=outline_status,
                        checks={"section_duration_sum": "PASS" if section_sum_ok else "FAIL",
                                "target_duration_range": "PASS" if duration_ok else "FAIL"},
                        findings=findings,
                        recommendations=["Regenerate the outline with the configured duration as a hard constraint."] if findings else [],
                    ),
                )
                qa_recorded = True
                if outline_status == "FAIL":
                    raise ValueError("Outline QA failed; inspect qa/qa_report.json before script generation.")
            self._complete_if_needed(project.project_id, "outline")

            script_dir = project_path / "script"
            current_stage = "script"
            qa_recorded = False
            script_result = self._run_configured(
                script_engine.create_script,
                research_file, outline_dir / "outline.json", script_dir,
                force_refresh=force_refresh,
                production_config=production_config,
            )
            if isinstance(script_result, Script) and isinstance(outline_result, Outline) and isinstance(research_result, Research):
                from modules.script.engine import ScriptEngine

                ScriptEngine._validate_script(
                    script_result,
                    research_result,
                    outline_result,
                    minimum_word_count=production_config.minimum_word_count,
                    minimum_duration_seconds=production_config.minimum_duration_seconds,
                )
                findings: list[str] = []
                recommendations: list[str] = []
                hook_section = next(
                    (section for section in script_result.sections if section.section_type == "hook"),
                    script_result.sections[0] if script_result.sections else None,
                )
                hook_matches_opening = bool(
                    hook_section
                    and script_result.hook.strip()
                    and hook_section.narration.lstrip().casefold().startswith(script_result.hook.strip().casefold())
                )
                hook_words = ScriptEngine._count_words(script_result.hook)
                hook_ok = hook_matches_opening and 13 <= hook_words <= 38
                if not hook_matches_opening:
                    findings.append("Script.hook does not match the opening narration in the first hook section.")
                    recommendations.append("Rewrite the first spoken section so it begins with the hook exactly once.")
                if not 13 <= hook_words <= 38:
                    findings.append(f"Opening hook has {hook_words} words; target is approximately 25 words (about 10 seconds).")
                    recommendations.append("Adjust the opening hook toward approximately 25 spoken words.")
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage="script",
                        status="PASS" if hook_ok else "REVIEW",
                        checks={"script_structure_and_duration": "PASS",
                                "hook_matches_spoken_opening": "PASS" if hook_matches_opening else "REVIEW",
                                "hook_duration": "PASS" if 13 <= hook_words <= 38 else "REVIEW"},
                        findings=findings,
                        recommendations=recommendations,
                    ),
                )
                qa_recorded = True
            self._complete_if_needed(project.project_id, "script")

            opportunity_context = (
                {
                    "report_id": report.report_id,
                    "provider": report.provider,
                    **candidate.model_dump(mode="json"),
                }
                if report and candidate
                else {}
            )
            provisional_package = PackagingArtifact(
                selected_title=str(
                    opportunity_context.get("proposed_title") or topic
                ).strip(),
                opportunity_context=opportunity_context,
            )
            (project_path / "packaging.json").write_text(
                json.dumps(provisional_package.to_dict(), indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            if not qa_recorded:
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage=current_stage,
                        status="FAIL",
                        checks={"stage_execution": "FAIL"},
                        findings=[str(exc)],
                        recommendations=["Inspect the stage artifact and error, then retry only this stage."],
                    ),
                )
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
    def _extract_script_excerpt(script_file: Path) -> str:
        if not script_file.exists():
            return ""

        try:
            payload = json.loads(script_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ""

        pieces: list[str] = []
        hook = payload.get("hook")
        if isinstance(hook, str) and hook.strip():
            pieces.append(hook)

        for section in payload.get("sections", [])[:5]:
            if not isinstance(section, dict):
                continue
            narration = section.get("narration")
            if isinstance(narration, str) and narration.strip():
                pieces.append(narration)

        return " ".join(pieces)[:400]

    @staticmethod
    def _run_configured(function, *args, **kwargs):
        parameters = inspect.signature(function).parameters
        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            return function(*args, **kwargs)
        supported_kwargs = {key: value for key, value in kwargs.items() if key in parameters}
        return function(*args, **supported_kwargs)

    @staticmethod
    def _run_ai_reviewed(
        stage: str,
        generate,
        args: tuple,
        kwargs: dict,
        evidence: dict,
        project_directory: str | Path,
        reviewer,
    ):
        artifact = generate(*args, **kwargs)
        for attempt in range(2):
            result = reviewer.review(stage, evidence, artifact)
            record_stage_qa(project_directory, result)
            if result.status != "FAIL":
                return artifact
            if attempt == 1:
                raise RuntimeError(
                    f"AI review failed after one feedback-guided retry for stage '{stage}'."
                )
            feedback = "\n".join(
                result.recommendations or result.findings
            )
            retry_kwargs = dict(kwargs)
            retry_kwargs["force_refresh"] = True
            retry_kwargs["qa_feedback"] = feedback
            artifact = ContentWorkflow._run_configured(
                generate,
                *args,
                **retry_kwargs,
            )
        raise RuntimeError(f"AI review did not complete for stage '{stage}'.")
