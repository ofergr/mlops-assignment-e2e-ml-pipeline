from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mlops_assignment_e2e_ml_pipeline.pipeline import (  # noqa: E402
    build_run_config,
    prepare_run_dir,
    run_agent_batch,
    run_swebench_eval,
    summarize_and_log,
)


@dag(
    dag_id="evaluate-agent",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    params={
        "split": "test",
        "subset": "verified",
        "workers": 1,
        "model": "nebius/moonshotai/Kimi-K2.6",
        "task_slice": "0:3",
        "run_id": "",
        "cost_limit": "0",
        "agent_config_path": "",
        "mlflow_tracking_uri": "",
        "mlflow_experiment": "coding-agent-evals",
        "eval_max_workers": 1,
        "use_sample": False,
    },
)
def evaluate_agent():
    @task
    def prepare_run() -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        overrides = dict(dag_run.conf or {}) if dag_run else {}
        run_config = build_run_config(dict(context["params"]), overrides)
        layout = prepare_run_dir(run_config)
        return {
            "run_config": run_config,
            "run_dir": str(layout.run_dir),
        }

    @task
    def run_agent(prepared: dict) -> dict:
        run_config = prepared["run_config"]
        layout = prepare_run_dir(run_config)
        return run_agent_batch(run_config, layout)

    @task
    def run_eval(prepared: dict, agent_result: dict) -> dict:
        run_config = prepared["run_config"]
        layout = prepare_run_dir(run_config)
        return run_swebench_eval(run_config, Path(agent_result["predictions_path"]), layout)

    @task
    def summarize(prepared: dict, agent_result: dict, eval_result: dict) -> dict:
        run_config = prepared["run_config"]
        layout = prepare_run_dir(run_config)
        return summarize_and_log(run_config, layout, agent_result, eval_result)

    prepared = prepare_run()
    agent_result = run_agent(prepared)
    eval_result = run_eval(prepared, agent_result)
    summarize(prepared, agent_result, eval_result)


evaluate_agent()
