from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mlops_assignment_e2e_ml_pipeline.pipeline import (
    build_agent_stage_result,
    build_eval_stage_result,
    prepare_run_dir,
    run_agent_batch,
    run_swebench_eval,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Container entrypoint for pipeline stages")
    parser.add_argument("--workspace", default="/workspace", help="Mounted project root inside the container")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_agent_parser = subparsers.add_parser("run-agent")
    run_agent_parser.add_argument("--run-id", required=True)

    run_eval_parser = subparsers.add_parser("run-eval")
    run_eval_parser.add_argument("--run-id", required=True)

    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    os.environ["PIPELINE_PROJECT_ROOT"] = str(workspace)

    config_path = workspace / "runs" / args.run_id / "config.json"
    run_config = json.loads(config_path.read_text())
    layout = prepare_run_dir(run_config)

    if args.command == "run-agent":
        run_agent_batch(run_config, layout)
        return

    if args.command == "run-eval":
        run_swebench_eval(run_config, layout.preds_path, layout)
        return

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
