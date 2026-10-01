"""Create, resume, and update a pipeline production checkpoint."""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.production_state import ProductionStateStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "initialize",
            "resume",
            "restart",
            "start",
            "complete",
            "fail",
            "issue",
            "intent",
        ),
    )
    parser.add_argument(
        "--state-file",
        default=os.environ.get(
            "RITZZ_PRODUCTION_STATE_FILE", ".pipeline-artifacts/production_state.json"
        ),
    )
    parser.add_argument(
        "--artifact-root",
        default=os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"),
    )
    parser.add_argument(
        "--production-id", default=os.environ.get("RITZZ_PRODUCTION_ID")
    )
    parser.add_argument("--stage")
    parser.add_argument("--artifacts", nargs="*", default=[])
    parser.add_argument("--project-id")
    parser.add_argument("--error")
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument(
        "--run-attempt",
        type=int,
        default=int(os.environ.get("GITHUB_RUN_ATTEMPT", "0")),
    )
    arguments = parser.parse_args()

    store = ProductionStateStore(arguments.state_file, arguments.artifact_root)
    if arguments.action == "initialize":
        if not arguments.production_id:
            parser.error("--production-id is required for initialize.")
        state = store.initialize(arguments.production_id)
    elif arguments.action == "resume":
        if not arguments.production_id:
            parser.error("--production-id is required for resume.")
        state = store.resume(arguments.production_id)
    elif arguments.action == "restart":
        if not arguments.stage:
            parser.error("--stage is required for restart.")
        state = store.restart_from_stage(arguments.stage)
    elif arguments.action == "issue":
        if arguments.issue_number is None:
            parser.error("--issue-number is required for issue.")
        state = store.set_approval_issue(arguments.issue_number)
    elif arguments.action == "intent":
        if not arguments.run_id:
            parser.error("--run-id is required for intent.")
        state = store.set_private_upload_intent(
            arguments.run_id,
            arguments.run_attempt,
        )
    else:
        if not arguments.stage:
            parser.error(f"--stage is required for {arguments.action}.")
        if arguments.action == "start":
            state = store.start_stage(arguments.stage)
        elif arguments.action == "complete":
            state = store.complete_stage(
                arguments.stage,
                arguments.artifacts,
                project_id=arguments.project_id,
            )
        else:
            state = store.fail_stage(
                arguments.stage,
                arguments.error or "Stage failed without an error message.",
                arguments.artifacts,
                project_id=arguments.project_id,
            )
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
