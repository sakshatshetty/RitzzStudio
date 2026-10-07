import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.outline.models import Outline
from modules.project.config import ProductionConfig
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult
from modules.research.models import Research
from modules.script.hook_quality import HookCandidateScores, HookQualityReview
from modules.script.models import (
    NarrativeMovement,
    Script,
    ScriptQualityFinding,
    ScriptQualityReview,
    ScriptSectionRevision,
)
from modules.script.profiles import get_script_profile


class ScriptEngine:
    """Generates narration scripts from approved research and outlines."""

    # ---------------------------------------------------------
    # Script requirements
    # ---------------------------------------------------------

    WORDS_PER_MINUTE = 140
    TEN_SECOND_HOOK_WORDS = 30

    MINIMUM_DURATION_SECONDS = 480

    MINIMUM_WORD_COUNT = 1150

    MAX_GENERATION_ATTEMPTS = 3

    # ---------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=OPENAI_API_KEY
        )

    # ---------------------------------------------------------
    # Create script
    # ---------------------------------------------------------

    def create_script(
        self,
        research_file: Path,
        outline_file: Path,
        script_directory: Path,
        force_refresh: bool = False,
        production_config: ProductionConfig | None = None,
        qa_feedback: str | None = None,
    ) -> Script:
        """Generate a narration script from research and outline."""

        config = production_config or ProductionConfig()
        get_script_profile(config.script_profile)
        script_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        script_file = (
            script_directory / "script.json"
        )

        research = self._load_research(research_file)
        outline = self._load_outline(outline_file)
        if research.topic != outline.topic:
            raise ValueError("Research and outline topics do not match.")
        input_fingerprint = self._script_input_fingerprint(
            research,
            outline,
            config,
        )

        # -------------------------------------------------
        # Cache
        # -------------------------------------------------

        if (
            script_file.exists()
            and not force_refresh
            and not qa_feedback
        ):
            cached = self._load_script(script_file)
            quality_report_file = script_directory / "script_quality_review.json"
            hook_report_file = script_directory / "hook_evaluation.json"
            if (
                cached.script_profile == config.script_profile
                and cached.input_fingerprint == input_fingerprint
                and cached.narrative_arc
                and quality_report_file.is_file()
                and hook_report_file.is_file()
            ):
                quality_report = json.loads(
                    quality_report_file.read_text(encoding="utf-8")
                )
                hook_report = json.loads(
                    hook_report_file.read_text(encoding="utf-8")
                )
                if (
                    quality_report.get("profile") == config.script_profile
                    and quality_report.get("status") == "PASS"
                    and hook_report.get("status") == "PASS"
                    and hook_report.get("version") == 2
                ):
                    try:
                        self._validate_script(
                            cached,
                            research,
                            outline,
                            minimum_word_count=config.minimum_word_count,
                            minimum_duration_seconds=config.minimum_duration_seconds,
                            words_per_minute=config.words_per_minute,
                            maximum_duration_seconds=(
                                config.maximum_acceptable_duration_seconds
                            ),
                        )
                        self._validate_narrative_metadata(
                            cached,
                            research,
                            outline,
                            profile_id=config.script_profile,
                        )
                    except ValueError as exc:
                        qa_feedback = f"Saved script cache failed validation: {exc}"
                    else:
                        return cached

        # -------------------------------------------------
        # Generate script with retries
        # -------------------------------------------------

        minimum_word_count = config.minimum_word_count
        maximum_duration_seconds = config.maximum_acceptable_duration_seconds
        last_word_count = 0

        for attempt in range(
            1,
            self.MAX_GENERATION_ATTEMPTS + 1,
        ):
            print(
                f"Generating script "
                f"(attempt {attempt}/"
                f"{self.MAX_GENERATION_ATTEMPTS})..."
            )

            # ---------------------------------------------
            # First generation
            # ---------------------------------------------

            if attempt == 1:
                user_prompt = self._build_user_prompt(
                    research,
                    outline,
                    config,
                )

            # ---------------------------------------------
            # Corrective generation
            # ---------------------------------------------

            elif last_word_count and self._calculate_duration_seconds(
                last_word_count,
                config.words_per_minute,
            ) > maximum_duration_seconds:
                user_prompt = self._build_contraction_prompt(
                    research,
                    outline,
                    last_word_count,
                    config,
                )
            else:
                user_prompt = self._build_expansion_prompt(
                    research,
                    outline,
                    last_word_count,
                    config,
                )
            if qa_feedback:
                user_prompt = (
                    f"{user_prompt}\n\n"
                    "QA issues to correct in this revision:\n"
                    f"{qa_feedback}"
                )

            # ---------------------------------------------
            # OpenAI structured generation
            # ---------------------------------------------

            response = self.client.responses.parse(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": self._system_prompt(config),
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                text_format=Script,
            )

            script = response.output_parsed

            if script is None:
                raise RuntimeError(
                    "OpenAI returned no structured script."
                )

            # ---------------------------------------------
            # Calculate actual word count
            # ---------------------------------------------

            actual_word_count = (
                self._calculate_word_count(
                    script
                )
            )

            last_word_count = actual_word_count

            # ---------------------------------------------
            # Calculate actual duration
            # ---------------------------------------------

            actual_duration_seconds = (
                self._calculate_duration_seconds(
                    actual_word_count,
                    config.words_per_minute,
                )
            )

            # ---------------------------------------------
            # Replace model-generated metadata
            # ---------------------------------------------

            script = script.model_copy(
                update={
                    "target_duration_seconds": config.target_duration_seconds,
                    "target_word_count": minimum_word_count,
                    "script_profile": config.script_profile,
                    "input_fingerprint": input_fingerprint,
                    "total_word_count": (
                        actual_word_count
                    ),
                    "total_estimated_seconds": (
                        actual_duration_seconds
                    ),
                }
            )

            print(
                f"Generated "
                f"{actual_word_count} words "
                f"({actual_duration_seconds}s)."
            )

            # ---------------------------------------------
            # Check minimum requirements
            # ---------------------------------------------

            if (
                actual_word_count
                >= minimum_word_count
                and actual_duration_seconds
                >= config.minimum_duration_seconds
                and actual_duration_seconds
                <= maximum_duration_seconds
            ):
                script = self._review_and_repair_narrative(
                    script,
                    research,
                    outline,
                    script_directory,
                    config,
                )
                script = self._review_and_strengthen_hook(
                    script,
                    research,
                    script_directory,
                    config,
                )

                # -----------------------------------------
                # Full validation
                # -----------------------------------------

                self._validate_script(
                    script,
                    research,
                    outline,
                    minimum_word_count=minimum_word_count,
                    minimum_duration_seconds=(
                        config.minimum_duration_seconds
                    ),
                    words_per_minute=config.words_per_minute,
                    maximum_duration_seconds=maximum_duration_seconds,
                )

                # -----------------------------------------
                # Save
                # -----------------------------------------

                self._save_script(
                    script_file,
                    script,
                )

                return script

            print("Script duration is outside configured limits. Retrying...")

        # -------------------------------------------------
        # All attempts failed
        # -------------------------------------------------

        raise ValueError(
            "Unable to generate a script within configured duration limits "
            f"after {self.MAX_GENERATION_ATTEMPTS} "
            f"attempts. "
            f"Last result contained "
            f"{last_word_count} words."
        )

    def _review_and_strengthen_hook(
        self,
        script: Script,
        research: Research,
        script_directory: Path,
        config: ProductionConfig | None = None,
    ) -> Script:
        config = config or ProductionConfig()
        threshold_text = os.getenv("RITZZ_HOOK_MIN_SCORE", "3.5")
        try:
            threshold = float(threshold_text)
        except ValueError as exc:
            raise ValueError("RITZZ_HOOK_MIN_SCORE must be a number from 0 to 5.") from exc
        if not 0 <= threshold <= 5:
            raise ValueError("RITZZ_HOOK_MIN_SCORE must be a number from 0 to 5.")

        source_ids = {source.id for source in research.sources}
        minimum_hook_words = self._ten_second_hook_word_target(
            config.words_per_minute
        )
        report: dict = {
            "version": 2,
            "topic": script.topic,
            "words_per_minute": config.words_per_minute,
            "minimum_hook_words": minimum_hook_words,
            "minimum_hook_seconds": 10,
            "retention_gate": {
                "minimum_curiosity": 4,
                "minimum_open_loop": 4,
                "minimum_payoff_promise": 4,
            },
            "threshold": threshold,
            "original_hook": script.hook,
            "selected_hook": script.hook,
            "iterations": [],
        }
        report_path = script_directory / "hook_evaluation.json"

        for iteration in range(1, 3):
            hook_section = next(
                (
                    section
                    for section in script.sections
                    if section.section_type == "hook"
                ),
                script.sections[0] if script.sections else None,
            )
            if hook_section is None:
                raise ValueError("Cannot evaluate a hook without script sections.")
            response = self.client.responses.parse(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Evaluate and improve a fact-grounded YouTube opening hook. "
                            "Score curiosity, tension, specificity, stakes, novelty, clarity, "
                            "open loop, payoff promise, viewer relevance, and factual support "
                            "from 0 to 5. "
                            "Do not use simplistic banned-phrase rules. Judge whether the "
                            "actual opening earns attention and promises a supported answer. "
                            "Use a modern-life connection only when it fits the approved "
                            "topic and evidence; do not force one. "
                            "Provide three distinct, stronger alternatives when the current "
                            f"hook is weak. Each alternative must be {minimum_hook_words}–38 "
                            "spoken words and "
                            "score at least 4/5 for curiosity, open loop, and payoff promise, "
                            "and cite source IDs that support its claims. Do not rewrite the "
                            "script or reveal the full answer in the hook."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Current hook:\n{script.hook}\n\n"
                            "Opening section context:\n"
                            f"{hook_section.narration}\n\n"
                            "Approved research and source IDs:\n"
                            f"{research.model_dump_json(indent=2)}\n\n"
                            f"Minimum average quality score: {threshold:.2f}/5.\n"
                            "Return scores for the current hook and three alternatives. "
                            "If prior alternatives were supplied, do not repeat their wording; "
                            "address the prior weaknesses."
                            + (
                                "\n\nPreviously attempted alternatives:\n"
                                + json.dumps(report["iterations"], ensure_ascii=False)
                                if report["iterations"]
                                else ""
                            )
                        ),
                    },
                ],
                text_format=HookQualityReview,
            )
            review = response.output_parsed
            if not isinstance(review, HookQualityReview):
                raise TypeError("Hook evaluator returned no valid structured result.")
            if review.current.text.strip().casefold() != script.hook.strip().casefold():
                raise ValueError(
                    "Hook evaluator scored a different current hook than the script contains."
                )
            current = review.current
            valid_alternatives = [
                candidate
                for candidate in review.alternatives
                if self._hook_meets_retention_gate(
                    candidate,
                    minimum_hook_words,
                    source_ids,
                )
            ]
            iteration_result = {
                "iteration": iteration,
                "current": current.model_dump(mode="json"),
                "current_score": current.quality_score,
                "alternatives": [
                    {
                        **candidate.model_dump(mode="json"),
                        "quality_score": candidate.quality_score,
                        "word_count": self._count_words(candidate.text),
                        "eligible": candidate in valid_alternatives,
                    }
                    for candidate in review.alternatives
                ],
                "improvement_notes": review.improvement_notes,
            }
            report["iterations"].append(iteration_result)

            current_is_supported = (
                self._hook_meets_retention_gate(
                    current,
                    minimum_hook_words,
                    source_ids,
                )
            )
            if current.quality_score >= threshold and current_is_supported:
                report["status"] = "PASS"
                report["selected_hook"] = script.hook
                report["regenerated"] = script.hook != report["original_hook"]
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._save_script(script_directory / "script.json", script)
                return script

            qualified_alternatives = [
                candidate
                for candidate in valid_alternatives
                if candidate.quality_score >= threshold
            ]
            if not qualified_alternatives:
                qualified_alternatives = [
                    candidate
                    for candidate in valid_alternatives
                    if candidate.quality_score > current.quality_score
                ]
            if not qualified_alternatives:
                if iteration < 2:
                    continue
                report["status"] = "FAIL"
                report["failure"] = (
                    "No fact-supported alternative met the minimum hook length "
                    "and curiosity/open-loop/payoff retention gate."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Hook quality did not meet the minimum duration and retention gate; "
                    "no fact-supported alternative passed after two attempts. "
                    "Inspect hook_evaluation.json."
                )
            selected = max(
                qualified_alternatives,
                key=lambda candidate: candidate.quality_score,
            )
            script = self._replace_opening_hook(
                script,
                selected.text,
                words_per_minute=config.words_per_minute,
            )
            report["selected_hook"] = selected.text
            if selected.quality_score >= threshold:
                report["status"] = "PASS"
                report["regenerated"] = selected.text != report["original_hook"]
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._save_script(script_directory / "script.json", script)
                return script

        report["status"] = "FAIL"
        report["failure"] = "Hook remained below the configured quality threshold."
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        raise ValueError(
            "Hook remained below the configured quality and retention thresholds "
            "after two hook-only improvement attempts; inspect hook_evaluation.json."
        )

    @classmethod
    def _hook_meets_retention_gate(
        cls,
        candidate: HookCandidateScores,
        minimum_words: int,
        source_ids: set[str],
    ) -> bool:
        return (
            minimum_words <= cls._count_words(candidate.text) <= 38
            and candidate.curiosity >= 4
            and candidate.open_loop >= 4
            and candidate.payoff_promise >= 4
            and candidate.factual_support >= 4
            and bool(candidate.source_ids)
            and set(candidate.source_ids).issubset(source_ids)
        )

    def _review_and_repair_narrative(
        self,
        script: Script,
        research: Research,
        outline: Outline,
        script_directory: Path,
        config: ProductionConfig,
    ) -> Script:
        profile = get_script_profile(config.script_profile)
        minimum_hook_words = self._ten_second_hook_word_target(
            config.words_per_minute
        )
        section_by_id = {section.section_id: section for section in outline.sections}
        report: dict = {
            "version": 1,
            "status": "RUNNING",
            "profile": profile.profile_id,
            "topic": script.topic,
            "iterations": [],
        }
        report_path = script_directory / "script_quality_review.json"
        source_ids = {source.id for source in research.sources}

        for attempt in range(1, 3):
            response = self.client.responses.parse(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Review a complete original RITZZ narration script against "
                            "its approved research, outline, profile, and structured "
                            "narrative plan. Check every supplied quality dimension. "
                            "Research is the only factual authority: flag claims not "
                            "supported there and ensure uncertainty is not strengthened. "
                            "Check that the hook opens a question without resolving it, "
                            "questions evolve, sections have narrative purpose, evidence "
                            "is interpreted rather than listed, any modern connection is "
                            "relevant and not forced, the ending pays off the opening, and "
                            "major beats can be visualized. Do not imitate or quote any "
                            "reference transcript. For each actionable defect, return "
                            "the exact affected section IDs and one concrete revision "
                            "instruction. Do not request edits to passing sections. "
                            "Use REVIEW when evidence is genuinely inconclusive; only "
                            "provide a repair instruction when a safe, research-grounded "
                            "section-only correction is possible."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Profile: {profile.profile_id}\n"
                            f"Profile principles:\n{profile.instructions()}\n\n"
                            f"APPROVED RESEARCH:\n{research.model_dump_json(indent=2)}\n\n"
                            f"APPROVED OUTLINE:\n{outline.model_dump_json(indent=2)}\n\n"
                            f"SCRIPT:\n{script.model_dump_json(indent=2)}"
                        ),
                    },
                ],
                text_format=ScriptQualityReview,
            )
            review = response.output_parsed
            if not isinstance(review, ScriptQualityReview):
                raise TypeError(
                    "Script quality reviewer returned no valid structured result."
                )
            checks = review.checks.model_dump()
            failed_checks = {
                name for name, status in checks.items() if status != "PASS"
            }
            iteration = {
                "attempt": attempt,
                "status": review.status,
                "checks": checks,
                "findings": [
                    finding.model_dump(mode="json")
                    for finding in review.findings
                ],
                "targeted_section_ids": sorted(
                    {
                        section_id
                        for finding in review.findings
                        for section_id in finding.section_ids
                    }
                ),
            }
            report["iterations"].append(iteration)
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if review.status == "PASS" and (failed_checks or review.findings):
                report["status"] = "FAIL"
                report["blocking_reason"] = (
                    "The reviewer marked unresolved checks or findings as PASS."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Script quality review cannot PASS with unresolved checks: "
                    + ", ".join(sorted(failed_checks or {"findings"}))
                )
            if review.status != "PASS" and not failed_checks:
                report["status"] = review.status
                report["blocking_reason"] = (
                    "The reviewer returned a non-PASS status without identifying "
                    "an unresolved quality check."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Script quality review status did not match its checks; "
                    "inspect script_quality_review.json."
                )
            unknown_sections = {
                section_id
                for finding in review.findings
                for section_id in finding.section_ids
                if section_id not in section_by_id
            }
            unknown_sources = {
                source_id
                for finding in review.findings
                for source_id in finding.research_source_ids
                if source_id not in source_ids
            }
            if unknown_sections or unknown_sources:
                report["status"] = "FAIL"
                report["blocking_reason"] = (
                    "The reviewer referenced an unknown section or source ID."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Script quality review referenced unknown section/source IDs: "
                    + ", ".join(sorted(unknown_sections | unknown_sources))
                )

            record_stage_qa(
                script_directory.parent,
                QAStageResult(
                    stage="script_narrative_review",
                    status=review.status,
                    checks=checks,
                    findings=[finding.rationale for finding in review.findings],
                    recommendations=[
                        finding.revision_instruction
                        for finding in review.findings
                        if finding.revision_instruction
                    ],
                    reviewer="openai",
                ),
            )
            if review.status == "PASS":
                try:
                    self._validate_narrative_metadata(
                        script,
                        research,
                        outline,
                        profile_id=profile.profile_id,
                    )
                except ValueError as exc:
                    report["status"] = "FAIL"
                    report["blocking_reason"] = str(exc)
                    report_path.write_text(
                        json.dumps(report, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    raise
                report["status"] = "PASS"
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return script

            if not review.findings or any(
                not finding.revision_instruction.strip()
                for finding in review.findings
            ):
                report["status"] = "REVIEW" if review.status == "REVIEW" else "FAIL"
                report["blocking_reason"] = (
                    "The reviewer did not provide a safe, targeted correction."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Script quality review could not provide a targeted correction; "
                    "inspect script_quality_review.json."
                )
            if attempt == 2:
                report["status"] = review.status
                report["blocking_reason"] = (
                    "Targeted script QA remained unresolved after one section-only repair."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Script quality review remains unresolved after a targeted repair; "
                    "inspect script_quality_review.json."
                )

            report["status"] = "REPAIRING"
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            updates: dict[str, ScriptSectionRevision] = {}
            findings_by_section: dict[str, list[ScriptQualityFinding]] = {}
            for finding in review.findings:
                for section_id in finding.section_ids:
                    findings_by_section.setdefault(section_id, []).append(finding)
            current_narration = {
                section.section_id: section.narration
                for section in script.sections
            }
            for section_id, section_findings in findings_by_section.items():
                section = section_by_id[section_id]
                arc = next(
                    (
                        movement
                        for movement in script.narrative_arc
                        if movement.section_id == section_id
                    ),
                    None,
                )
                if arc is None:
                    outline_index = next(
                        index
                        for index, item in enumerate(outline.sections)
                        if item.section_id == section_id
                    )
                    next_section = (
                        outline.sections[outline_index + 1]
                        if outline_index + 1 < len(outline.sections)
                        else None
                    )
                    supported_evidence = [
                        source_id
                        for source_id in section.research_sources
                        if source_id in source_ids
                    ]
                    arc = NarrativeMovement(
                        section_id=section_id,
                        purpose=section.purpose,
                        question=(
                            f"What does the evidence reveal about {section.title}?"
                        ),
                        evidence_source_ids=supported_evidence,
                        reveal=(
                            section.key_points[0]
                            if section.key_points
                            else section.purpose
                        ),
                        next_question=(
                            f"What does this mean for {next_section.title}?"
                            if next_section
                            else "What does this answer change about the opening mystery?"
                        ),
                        visual_opportunity=(
                            section.key_points[0]
                            if section.key_points
                            else section.purpose
                        ),
                    )
                repair_summary = "\n".join(
                    (
                        f"{finding.category}: {finding.rationale}\n"
                        f"Correction: {finding.revision_instruction}"
                    )
                    for finding in section_findings
                )
                revision_response = self.client.responses.parse(
                        model=OPENAI_MODEL,
                        input=[
                            {
                                "role": "system",
                                "content": (
                                    "Revise only the one identified script section. "
                                    "Preserve all supported facts and source limits. "
                                    "Return a complete replacement narration for this "
                                    "section plus its narrative movement metadata. Do "
                                    "not rewrite other sections, add facts, or alter "
                                    "the section ID. If this is the hook section, provide "
                                    f"a {minimum_hook_words}–38-word hook that exactly "
                                    "begins the revised narration, scores at least 4/5 "
                                    "for curiosity, open loop, and payoff promise, and "
                                    "keeps the central mystery open."
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"Profile: {profile.profile_id}\n"
                                    f"Profile principles:\n{profile.instructions()}\n\n"
                                    f"Required repairs for this section:\n"
                                    f"{repair_summary}\n\n"
                                    f"Outline section:\n{section.model_dump_json(indent=2)}\n\n"
                                    f"Current narrative movement:\n"
                                    f"{arc.model_dump_json(indent=2)}\n\n"
                                    f"Current narration:\n"
                                    f"{current_narration[section_id]}\n\n"
                                    f"Approved research:\n"
                                    f"{research.model_dump_json(indent=2)}"
                                ),
                            },
                        ],
                        text_format=ScriptSectionRevision,
                )
                revision = revision_response.output_parsed
                if not isinstance(revision, ScriptSectionRevision):
                    raise TypeError(
                        "Targeted script revision returned no valid section."
                    )
                if (
                    revision.section_id != section_id
                    or revision.movement.section_id != section_id
                ):
                    raise ValueError(
                        "Targeted script revision changed the requested section ID."
                    )
                allowed_sources = set(section.research_sources) & source_ids
                if not set(revision.movement.evidence_source_ids).issubset(
                    allowed_sources
                ):
                    report["status"] = "FAIL"
                    report["blocking_reason"] = (
                        "Targeted section revision cited unapproved research sources."
                    )
                    report_path.write_text(
                        json.dumps(report, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    raise ValueError(
                        "Targeted script revision cited evidence outside its "
                        f"approved section sources: {section_id}."
                    )
                if section.section_type == "hook":
                    hook_words = self._count_words(revision.hook)
                    if not minimum_hook_words <= hook_words <= 38:
                        raise ValueError(
                            "Targeted hook revision must contain at least "
                            f"{minimum_hook_words} words for the 10-second opening."
                        )
                    if not revision.narration.lstrip().casefold().startswith(
                        revision.hook.strip().casefold()
                    ):
                        raise ValueError(
                            "Targeted hook revision does not match its spoken opening."
                        )
                updates[section_id] = revision

            revised_sections = [
                section.model_copy(
                    update={"narration": updates[section.section_id].narration}
                )
                if section.section_id in updates
                else section
                for section in script.sections
            ]
            existing_movements = {
                movement.section_id: movement for movement in script.narrative_arc
            }
            revised_arc = [
                (
                    updates[section.section_id].movement
                    if section.section_id in updates
                    else existing_movements[section.section_id]
                )
                for section in outline.sections
                if section.section_id in updates
                or section.section_id in existing_movements
            ]
            iteration["targeted_section_ids"] = sorted(updates)
            script_updates: dict[str, Any] = {
                "sections": revised_sections,
                "narrative_arc": revised_arc,
                "major_reveals": [movement.reveal for movement in revised_arc],
                "visual_opportunities": [
                    movement.visual_opportunity for movement in revised_arc
                ],
            }
            if revised_arc:
                script_updates["final_payoff"] = (
                    script.final_payoff or revised_arc[-1].reveal
                )
            for section_id, revision in updates.items():
                section = section_by_id[section_id]
                if section.section_type == "hook":
                    script_updates["hook"] = revision.hook.strip()
                    script_updates["hook_plan"] = revision.hook_plan
                if revision.viewer_connection:
                    script_updates["viewer_connection"] = revision.viewer_connection
                if revision.myth_or_assumption:
                    script_updates["myth_or_assumption"] = revision.myth_or_assumption
                if revision.uncertainty:
                    script_updates["uncertainties"] = [
                        *script.uncertainties,
                        revision.uncertainty,
                    ]
            script = script.model_copy(update=script_updates)
            word_count = self._calculate_word_count(script)
            script = script.model_copy(
                update={
                    "total_word_count": word_count,
                    "total_estimated_seconds": self._calculate_duration_seconds(
                        word_count,
                        config.words_per_minute,
                    ),
                }
            )

        raise RuntimeError("Script narrative QA repair loop ended unexpectedly.")

    @staticmethod
    def _validate_narrative_metadata(
        script: Script,
        research: Research,
        outline: Outline,
        *,
        profile_id: str,
    ) -> None:
        if script.script_profile != profile_id:
            raise ValueError("Script profile metadata does not match configuration.")
        if not all(
            value.strip()
            for value in (
                script.hook_plan.central_question,
                script.hook_plan.open_loop,
                script.hook_plan.stakes,
                script.final_payoff,
            )
        ):
            raise ValueError(
                "Script hook plan and final payoff metadata must be complete."
            )
        section_ids = [section.section_id for section in outline.sections]
        movement_ids = [movement.section_id for movement in script.narrative_arc]
        if movement_ids != section_ids:
            raise ValueError(
                "Script narrative arc must contain one ordered movement per outline section."
            )
        source_ids = {source.id for source in research.sources}
        sections = {section.section_id: section for section in outline.sections}
        script_sections = {
            section.section_id: section for section in script.sections
        }
        if set(script_sections) != set(section_ids):
            raise ValueError(
                "Script sections do not match the outline section IDs."
            )
        for section_id in section_ids:
            if set(script_sections[section_id].research_sources) != set(
                sections[section_id].research_sources
            ):
                raise ValueError(
                    f"Script section {section_id} did not preserve its outline "
                    "research source IDs."
                )
        for movement in script.narrative_arc:
            if not all(
                value.strip()
                for value in (
                    movement.purpose,
                    movement.question,
                    movement.reveal,
                    movement.next_question,
                    movement.visual_opportunity,
                )
            ):
                raise ValueError(
                    f"Narrative movement {movement.section_id} is incomplete."
                )
            allowed_sources = set(sections[movement.section_id].research_sources)
            if not set(movement.evidence_source_ids).issubset(
                allowed_sources & source_ids
            ):
                raise ValueError(
                    f"Narrative movement {movement.section_id} cites evidence "
                    "outside its approved research sources."
                )
            if allowed_sources and not movement.evidence_source_ids:
                raise ValueError(
                    f"Narrative movement {movement.section_id} omits its approved "
                    "evidence source IDs."
                )

    @staticmethod
    def _script_input_fingerprint(
        research: Research,
        outline: Outline,
        config: ProductionConfig,
    ) -> str:
        payload = {
            "research": research.model_dump(mode="json"),
            "outline": outline.model_dump(mode="json"),
            "target_duration_seconds": config.target_duration_seconds,
            "minimum_duration_seconds": config.minimum_duration_seconds,
            "words_per_minute": config.words_per_minute,
            "script_profile": config.script_profile,
            "constraints": config.constraints,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _replace_opening_hook(
        cls,
        script: Script,
        new_hook: str,
        *,
        words_per_minute: int | None = None,
    ) -> Script:
        if not script.sections or not new_hook.strip():
            raise ValueError("Cannot replace a missing opening hook.")
        hook_section_index = next(
            (
                index
                for index, section in enumerate(script.sections)
                if section.section_type == "hook"
            ),
            0,
        )
        section = script.sections[hook_section_index]
        leading = len(section.narration) - len(section.narration.lstrip())
        narration = section.narration[leading:]
        if not narration.casefold().startswith(script.hook.strip().casefold()):
            raise ValueError(
                "Script.hook does not match the first spoken hook-section text; "
                "cannot safely regenerate only the hook."
            )
        remainder = narration[len(script.hook.strip()):].lstrip()
        updated_narration = (
            f"{new_hook.strip()} {remainder}".rstrip()
            if remainder
            else new_hook.strip()
        )
        sections = list(script.sections)
        sections[hook_section_index] = section.model_copy(
            update={"narration": " " * leading + updated_narration}
        )
        updated_script = script.model_copy(
            update={
                "hook": new_hook.strip(),
                "sections": sections,
            }
        )
        word_count = cls._calculate_word_count(updated_script)
        return updated_script.model_copy(
            update={
                "total_word_count": word_count,
                "total_estimated_seconds": cls._calculate_duration_seconds(
                    word_count,
                    words_per_minute,
                ),
            }
        )

    # ---------------------------------------------------------
    # System prompt
    # ---------------------------------------------------------

    @staticmethod
    def _system_prompt(config: ProductionConfig | None = None) -> str:
        """Return the Script Engine system prompt."""

        config = config or ProductionConfig()
        profile = get_script_profile(config.script_profile)
        ten_second_hook_words = ScriptEngine._ten_second_hook_word_target(
            config.words_per_minute
        )
        target_words = round(
            config.target_duration_seconds
            * config.words_per_minute
            / 60
        )
        maximum_words = round(
            config.maximum_acceptable_duration_seconds
            * config.words_per_minute
            / 60
        )

        return (
            "You are the Script Engine for Ritzz, "
            "an English-language educational YouTube channel.\n\n"

            "Your job is to transform approved research "
            "and an approved video outline into a complete "
            "engaging narration script.\n\n"

            f"The script is intended for an approximately {config.target_duration_seconds // 60}-minute YouTube video.\n\n"

            f"Aim for about {target_words} spoken words and do not exceed {maximum_words} words unless the approved research cannot be explained accurately within that length.\n\n"

            f"The first spoken words of the first hook section must be a compelling hook of about {ten_second_hook_words} words (roughly 10 seconds). Start with a vivid question, surprising contrast, or specific curiosity gap that is supported by the research. Build interest without giving away the full answer. Avoid greetings, channel introductions, generic setup, and unsupported or exaggerated claims. The Script.hook field must match this opening text; the voice reads the section narration, so do not repeat the hook later.\n\n"

            "The final narration MUST contain at least "
            f"{config.minimum_word_count} words of actual spoken narration.\n\n"

            "Use approximately "
            f"{config.words_per_minute} spoken words per minute "
            "as the pacing reference.\n\n"

            "Write natural spoken English suitable for "
            "professional YouTube narration and text-to-speech.\n\n"

            "Use careful standard punctuation to guide calm spoken delivery: "
            "commas for natural clause pauses, periods when a thought is complete, "
            "and question marks for genuine questions. Break paragraphs at meaningful "
            "story transitions. Avoid run-on sentences, sentence fragments, and "
            "repeated ellipses or exclamation marks. Do not put spoken delivery or "
            "stage directions in the narration.\n\n"

            "The writing should sound like a skilled human "
            "YouTube narrator rather than an academic paper.\n\n"

            "Use curiosity, pacing, transitions, explanations "
            "and storytelling.\n\n"

            f"ACTIVE SCRIPT PROFILE: {profile.profile_id}\n"
            f"{profile.description}\n"
            f"{profile.instructions()}\n\n"

            "Create useful structured narrative metadata: a hook plan with the "
            "central question, open loop, stakes, and any supported modern connection; "
            "one narrative movement per outline section with its purpose, question, "
            "evidence source IDs, reveal, next question/problem, and visual opportunity; "
            "and a final payoff that resolves or reframes the opening mystery. "
            "Keep the metadata consistent with the spoken narration and approved sources.\n\n"

            "Fully develop every section of the outline.\n\n"

            "Do not produce a short summary.\n\n"

            "Do not compress multiple ideas into a few sentences "
            "just to move quickly through the outline.\n\n"

            "Each section should contain enough narration to "
            "reasonably fill its allocated duration.\n\n"

            "Do not invent factual claims.\n\n"

            "Use ONLY information supported by the supplied "
            "research.\n\n"

            "Do not introduce unsupported dates, names, events, "
            "statistics or explanations.\n\n"

            "If the research describes something as uncertain, "
            "unproven, disputed or a theory, preserve that "
            "level of uncertainty in the narration.\n\n"

            "Follow the supplied outline structure exactly.\n\n"

            "Preserve the research source IDs associated with "
            "each outline section.\n\n"

            "Source IDs are production metadata and should not "
            "normally be spoken aloud.\n\n"

            "The narration should feel like one continuous "
            "YouTube story with natural transitions between "
            "sections.\n\n"

            "Do not include stage directions, camera directions, "
            "visual instructions or production notes inside "
            "the narration."
        )

    # ---------------------------------------------------------
    # First-generation user prompt
    # ---------------------------------------------------------

    @classmethod
    def _build_user_prompt(
        cls,
        research: Research,
        outline: Outline,
        config: ProductionConfig | None = None,
    ) -> str:
        """Build the initial generation prompt."""

        config = config or ProductionConfig()
        profile = get_script_profile(config.script_profile)
        ten_second_hook_words = cls._ten_second_hook_word_target(
            config.words_per_minute
        )
        target_script_words = round(
            config.target_duration_seconds
            * config.words_per_minute
            / 60
        )
        maximum_words = round(
            config.maximum_acceptable_duration_seconds
            * config.words_per_minute
            / 60
        )
        section_targets = []

        for section in outline.sections:
            section_target_words = round(
                section.estimated_seconds
                * config.words_per_minute
                / 60
            )

            section_targets.append(
                f"- {section.section_id}: "
                f"{section.title} — "
                f"{section.estimated_seconds} seconds, "
                f"approximately {section_target_words} words"
            )

        section_target_text = "\n".join(
            section_targets
        )

        return (
            "Create the final narration script using ONLY "
            "the approved research and outline below.\n\n"

            "=================================================\n"
            "SCRIPT LENGTH REQUIREMENTS\n"
            "=================================================\n\n"

            f"TARGET: approximately {target_script_words} spoken words ({config.target_duration_seconds} seconds).\n"
            f"HARD UPPER LIMIT: {maximum_words} words ({config.maximum_acceptable_duration_seconds} seconds).\n"
            f"The narration must meet the configured minimum of {config.minimum_word_count} words.\n\n"

            f"OPENING HOOK: The first spoken words of the first hook section must be a compelling, fact-grounded hook of about {ten_second_hook_words} spoken words (roughly 10 seconds). Use a specific curiosity gap, surprising contrast, or question; do not give away the full answer. No greeting, channel introduction, generic setup, or unsupported/exaggerated claim. The Script.hook field must match this opening text exactly; narration speaks it once, so do not repeat the hook later.\n\n"

            "Use approximately "
            f"{config.words_per_minute} spoken words per minute "
            "as the pacing reference.\n\n"

            f"APPLY SCRIPT PROFILE {profile.profile_id}:\n"
            f"{profile.instructions()}\n\n"

            "After the narration, populate the Script artifact's hook_plan, "
            "narrative_arc (exactly one movement per section), viewer_connection, "
            "myth_or_assumption when supported, major_reveals, uncertainties, "
            "visual_opportunities, and final_payoff. Narrative evidence IDs must "
            "come from that section's approved research source IDs. Do not create "
            "extra spoken sections for this metadata.\n\n"

            "Punctuate every narration section for natural text-to-speech: use commas "
            "for brief clause pauses, periods for completed thoughts, and question "
            "marks for real questions. Avoid run-on sentences, fragments, and excess "
            "ellipses or exclamation marks.\n\n"

            "Do not intentionally write a short script.\n\n"

            "Fully develop every section rather than merely "
            "mentioning its key points.\n\n"

            "Approximate word targets for each section:\n\n"

            f"{section_target_text}\n\n"

            "These are approximate targets. Natural storytelling "
            "and factual accuracy are more important than exact "
            "section word counts.\n\n"

            "If a section needs additional words to explain "
            "its idea clearly, expand it naturally.\n\n"

            "Do NOT add unsupported information merely to "
            "increase the word count.\n\n"

            "=================================================\n"
            "APPROVED RESEARCH\n"
            "=================================================\n\n"

            f"{research.model_dump_json(indent=2)}\n\n"

            "=================================================\n"
            "APPROVED OUTLINE\n"
            "=================================================\n\n"

            f"{outline.model_dump_json(indent=2)}"
        )

    @classmethod
    def _build_contraction_prompt(
        cls,
        research: Research,
        outline: Outline,
        current_word_count: int,
        config: ProductionConfig,
    ) -> str:
        profile = get_script_profile(config.script_profile)
        ten_second_hook_words = cls._ten_second_hook_word_target(
            config.words_per_minute
        )
        maximum_words = round(
            config.maximum_acceptable_duration_seconds
            * config.words_per_minute
            / 60
        )
        return (
            "The previous script exceeded the configured video duration.\n\n"
            f"It contained {current_word_count} words. Rewrite the COMPLETE script "
            f"to contain approximately {config.minimum_word_count} words and no more "
            f"than {maximum_words} words. Keep every outline section, preserve source "
            "IDs, and retain all important supported facts. Remove repetition, "
            "redundant transitions, and nonessential detail; do not invent facts.\n\n"
            f"Preserve a compelling, fact-grounded opening hook of about {ten_second_hook_words} words at the beginning of the first hook section. Keep Script.hook exactly matched to those first spoken words; do not repeat the hook later.\n\n"
            f"Maintain the {profile.profile_id} profile and its structured hook plan, "
            "section movements, evidence links, uncertainties, visual opportunities, "
            "and final payoff.\n\n"
            "Use only the approved research and follow the approved outline.\n\n"
            f"Retain the {config.script_profile} narrative arc and metadata; do not "
            "remove supported questions, reveals, evidence links, or the final payoff.\n\n"
            "APPROVED RESEARCH:\n"
            f"{research.model_dump_json(indent=2)}\n\n"
            "APPROVED OUTLINE:\n"
            f"{outline.model_dump_json(indent=2)}"
        )

    # ---------------------------------------------------------
    # Expansion prompt
    # ---------------------------------------------------------

    @classmethod
    def _build_expansion_prompt(
        cls,
        research: Research,
        outline: Outline,
        current_word_count: int,
        config: ProductionConfig | None = None,
    ) -> str:
        """Build a prompt for expanding an undersized script."""

        config = config or ProductionConfig()
        profile = get_script_profile(config.script_profile)
        ten_second_hook_words = cls._ten_second_hook_word_target(
            config.words_per_minute
        )
        required_words = config.minimum_word_count

        additional_words = (
            required_words
            - current_word_count
        )

        additional_words = max(additional_words, 0)

        requested_additional_words = (
            additional_words + 100
        )

        return (
            "The previous generated script was too short.\n\n"

            f"The previous script contained "
            f"{current_word_count} words.\n\n"

            f"The final script MUST contain at least "
            f"{required_words} words.\n\n"

            f"Add approximately "
            f"{requested_additional_words} "
            "additional words while maintaining natural "
            "YouTube narration.\n\n"

            "IMPORTANT:\n"
            "Generate the COMPLETE script again. "
            "Do not return only the additional paragraphs.\n\n"

            f"Preserve the compelling, fact-grounded opening hook of about {ten_second_hook_words} words at the beginning of the first hook section. Keep Script.hook exactly matched to those first spoken words; do not repeat the hook later.\n\n"

            "Fully preserve all existing sections.\n\n"

            "Expand the script naturally by developing:\n"
            "- evidence-led explanations and concrete human experiences\n"
            "- consequences that create a meaningful next question\n"
            "- context and transitions that strengthen the profile's narrative arc\n"
            "- examples already supported by the research\n"
            "- historical detail already present in the research\n"
            "- myth-versus-fact explanations\n"
            "- storytelling and narrative flow\n\n"

            "Do NOT pad the script with repetition.\n\n"

            "Do NOT repeat the same point using different words "
            "just to increase length.\n\n"

            "Do NOT introduce unsupported facts.\n\n"

            "Use ONLY the approved research below.\n\n"

            "Maintain the exact outline section structure.\n\n"

            "Maintain the research source IDs associated with "
            "each section.\n\n"

            f"Keep applying the {profile.profile_id} profile and preserve/populate "
            "the structured hook plan, one narrative movement per outline section, "
            "uncertainties, visual opportunities, and opening payoff metadata.\n\n"

            "Punctuate every narration section for natural text-to-speech: use commas "
            "for brief clause pauses, periods for completed thoughts, and question "
            "marks for real questions. Avoid run-on sentences, fragments, and excess "
            "ellipses or exclamation marks.\n\n"

            "The result must contain at least "
            f"{required_words} words of actual narration.\n\n"

            "=================================================\n"
            "APPROVED RESEARCH\n"
            "=================================================\n\n"

            f"{research.model_dump_json(indent=2)}\n\n"

            "=================================================\n"
            "APPROVED OUTLINE\n"
            "=================================================\n\n"

            f"{outline.model_dump_json(indent=2)}"
        )

    # ---------------------------------------------------------
    # Research loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_research(
        research_file: Path,
    ) -> Research:
        """Load and validate research JSON."""

        if not research_file.exists():
            raise FileNotFoundError(
                f"Research file not found: "
                f"{research_file}"
            )

        data = json.loads(
            research_file.read_text(
                encoding="utf-8"
            )
        )

        return Research.model_validate(
            data
        )

    # ---------------------------------------------------------
    # Outline loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_outline(
        outline_file: Path,
    ) -> Outline:
        """Load and validate outline JSON."""

        if not outline_file.exists():
            raise FileNotFoundError(
                f"Outline file not found: "
                f"{outline_file}"
            )

        data = json.loads(
            outline_file.read_text(
                encoding="utf-8"
            )
        )

        return Outline.model_validate(
            data
        )

    # ---------------------------------------------------------
    # Script saving
    # ---------------------------------------------------------

    @staticmethod
    def _save_script(
        script_file: Path,
        script: Script,
    ) -> None:
        """Save the generated script."""

        script_file.write_text(
            script.model_dump_json(
                indent=4
            ),
            encoding="utf-8",
        )

    # ---------------------------------------------------------
    # Script loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_script(
        script_file: Path,
    ) -> Script:
        """Load a cached script."""

        data = json.loads(
            script_file.read_text(
                encoding="utf-8"
            )
        )

        return Script.model_validate(
            data
        )

    # ---------------------------------------------------------
    # Word counting
    # ---------------------------------------------------------

    @classmethod
    def _ten_second_hook_word_target(cls, words_per_minute: int) -> int:
        """Scale the default spoken hook length to the configured narration pace."""

        return min(
            38,
            max(
                13,
                round(
                    words_per_minute
                    * cls.TEN_SECOND_HOOK_WORDS
                    / cls.WORDS_PER_MINUTE
                ),
            ),
        )

    @staticmethod
    def _count_words(
        text: str,
    ) -> int:
        """Count spoken words."""

        return len(
            re.findall(
                r"\b[\w’'-]+\b",
                text,
            )
        )

    @classmethod
    def _calculate_word_count(
        cls,
        script: Script,
    ) -> int:
        """Calculate total narration word count."""

        narration = " ".join(
            section.narration
            for section in script.sections
        )

        return cls._count_words(
            narration
        )

    # ---------------------------------------------------------
    # Duration calculation
    # ---------------------------------------------------------

    @classmethod
    def _calculate_duration_seconds(
        cls,
        word_count: int,
        words_per_minute: int | None = None,
    ) -> int:
        """Calculate narration duration from word count."""

        seconds = (
            word_count
            / (words_per_minute or cls.WORDS_PER_MINUTE)
            * 60
        )

        return round(seconds)

    # ---------------------------------------------------------
    # Script validation
    # ---------------------------------------------------------

    @classmethod
    def _validate_script(
        cls,
        script: Script,
        research: Research,
        outline: Outline,
        minimum_word_count: int | None = None,
        minimum_duration_seconds: int | None = None,
        words_per_minute: int | None = None,
        maximum_duration_seconds: int | None = None,
    ) -> None:
        """Validate the generated script."""

        required_word_count = (
            minimum_word_count
            if minimum_word_count is not None
            else cls.MINIMUM_WORD_COUNT
        )
        required_duration_seconds = (
            minimum_duration_seconds
            if minimum_duration_seconds is not None
            else cls.MINIMUM_DURATION_SECONDS
        )
        used_words_per_minute = words_per_minute or cls.WORDS_PER_MINUTE
        research_source_ids = {source.id for source in research.sources}

        # -------------------------------------------------
        # Topic validation
        # -------------------------------------------------

        if script.topic != research.topic:
            raise ValueError(
                "Script topic does not match "
                "research topic."
            )

        if script.topic != outline.topic:
            raise ValueError(
                "Script topic does not match "
                "outline topic."
            )

        # -------------------------------------------------
        # Section validation
        # -------------------------------------------------

        if not script.sections:
            raise ValueError(
                "Script must contain at least one section."
            )

        if len(script.sections) != len(
            outline.sections
        ):
            raise ValueError(
                "Script section count does not match "
                "outline section count."
            )

        # -------------------------------------------------
        # Section IDs
        # -------------------------------------------------

        outline_ids = [
            section.section_id
            for section in outline.sections
        ]

        script_ids = [
            section.section_id
            for section in script.sections
        ]

        if script_ids != outline_ids:
            raise ValueError(
                "Script section IDs do not match "
                "the outline."
            )

        invalid_sources = {
            source_id
            for section in script.sections
            for source_id in section.research_sources
            if source_id not in research_source_ids
        }
        if invalid_sources:
            raise ValueError(
                "Script sections cite unknown research source IDs: "
                + ", ".join(sorted(invalid_sources))
            )
        outline_sources_by_section = {
            section.section_id: set(section.research_sources)
            for section in outline.sections
        }
        mismatched_sources = [
            section.section_id
            for section in script.sections
            if set(section.research_sources)
            != outline_sources_by_section[section.section_id]
        ]
        if mismatched_sources:
            raise ValueError(
                "Script sections did not preserve outline research source IDs: "
                + ", ".join(mismatched_sources)
            )

        # -------------------------------------------------
        # Narration validation
        # -------------------------------------------------

        for section in script.sections:
            if not section.narration.strip():
                raise ValueError(
                    f"Section {section.section_id} "
                    "contains no narration."
                )

        if script.script_profile:
            hook_section = next(
                (
                    section
                    for section in script.sections
                    if section.section_type == "hook"
                ),
                script.sections[0],
            )
            hook_words = cls._count_words(script.hook)
            minimum_hook_words = cls._ten_second_hook_word_target(
                used_words_per_minute
            )
            if not minimum_hook_words <= hook_words <= 38:
                raise ValueError(
                    f"Profiled script hook has {hook_words} words; expected "
                    f"{minimum_hook_words}–38 for a roughly 10-second opening."
                )
            if not hook_section.narration.lstrip().casefold().startswith(
                script.hook.strip().casefold()
            ):
                raise ValueError(
                    "Script.hook does not match the first spoken hook-section text."
                )

        # -------------------------------------------------
        # Word count
        # -------------------------------------------------

        calculated_words = (
            cls._calculate_word_count(
                script
            )
        )

        if calculated_words != (
            script.total_word_count
        ):
            raise ValueError(
                "Script word count mismatch: "
                f"calculated {calculated_words}, "
                f"but script reports "
                f"{script.total_word_count}."
            )

        # -------------------------------------------------
        # Minimum word count
        # -------------------------------------------------

        if calculated_words < required_word_count:
            raise ValueError(
                "Script is too short: "
                f"{calculated_words} words generated, "
                f"but at least "
                f"{required_word_count} words "
                "are required."
            )

        # -------------------------------------------------
        # Duration
        # -------------------------------------------------

        calculated_duration = (
            cls._calculate_duration_seconds(
                calculated_words,
                used_words_per_minute,
            )
        )

        if calculated_duration != (
            script.total_estimated_seconds
        ):
            raise ValueError(
                "Script duration mismatch: "
                f"calculated {calculated_duration}s, "
                f"but script reports "
                f"{script.total_estimated_seconds}s."
            )

        # -------------------------------------------------
        # Minimum duration
        # -------------------------------------------------

        if calculated_duration < required_duration_seconds:
            raise ValueError(
                "Script is too short: "
                f"calculated duration is "
                f"{calculated_duration}s, "
                f"but at least "
                f"{required_duration_seconds}s "
                "is required."
            )
        if (
            maximum_duration_seconds is not None
            and calculated_duration > maximum_duration_seconds
        ):
            raise ValueError(
                "Script is too long: calculated duration is "
                f"{calculated_duration}s, but maximum acceptable duration is "
                f"{maximum_duration_seconds}s."
            )
