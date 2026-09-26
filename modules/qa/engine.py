import json
from pathlib import Path

from modules.qa.models import ProjectQAReport, QAStageResult


QA_DIRECTORY = "qa"
QA_REPORT_FILENAME = "qa_report.json"


def qa_report_path(project_directory: str | Path) -> Path:
    return Path(project_directory) / QA_DIRECTORY / QA_REPORT_FILENAME


def load_project_qa(project_directory: str | Path) -> ProjectQAReport:
    path = qa_report_path(project_directory)
    if not path.exists():
        return ProjectQAReport()
    return ProjectQAReport.model_validate_json(path.read_text(encoding="utf-8"))


def record_stage_qa(
    project_directory: str | Path,
    result: QAStageResult,
) -> ProjectQAReport:
    report = load_project_qa(project_directory)
    report.add_result(result)
    path = qa_report_path(project_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report