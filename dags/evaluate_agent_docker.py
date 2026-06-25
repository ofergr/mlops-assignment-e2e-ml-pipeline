from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

try:
    from airflow.providers.docker.operators.docker import DockerOperator
    from docker.types import Mount
except ImportError:  # pragma: no cover - parse-time fallback for environments without the provider
    DockerOperator = None
    Mount = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mlops_assignment_e2e_ml_pipeline.pipeline import (  # noqa: E402
    build_agent_stage_result,
    build_eval_stage_result,
    build_run_config,
    prepare_run_dir,
    summarize_and_log,
)


def _docker_image() -> str:
    return os.getenv("PIPELINE_DOCKER_IMAGE", "mlops-assignment-e2e-ml-pipeline:local")


def _host_project_root() -> str:
    return os.getenv("HOST_PROJECT_ROOT", str(PROJECT_ROOT))


@dag(
    dag_id="evaluate-agent-docker",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    params={
        "split": "test",
        "subset": "verified",
        "workers": 1,
        "model": "nebius/moonshotai/Kimi-K2.6",
        "task_slice": "0:1",
        "run_id": "",
        "cost_limit": "",
        "agent_config_path": "",
        "mlflow_tracking_uri": "",
        "mlflow_experiment": "coding-agent-evals",
        "eval_max_workers": 1,
        "use_sample": False,
    },
)
def evaluate_agent_docker():
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
    def summarize(prepared: dict) -> dict:
        run_config = prepared["run_config"]
        layout = prepare_run_dir(run_config)
        agent_result = build_agent_stage_result(layout, used_sample=bool(run_config.get("use_sample")))
        eval_result = build_eval_stage_result(layout, run_config, used_sample=bool(run_config.get("use_sample")))
        return summarize_and_log(run_config, layout, agent_result, eval_result)

    prepared = prepare_run()

    if DockerOperator is None or Mount is None:
        raise RuntimeError(
            "evaluate-agent-docker requires apache-airflow-providers-docker and docker SDK to be installed."
        )

    mounts = [
        Mount(source=_host_project_root(), target="/workspace", type="bind"),
        Mount(source="/var/run/docker.sock", target="/var/run/docker.sock", type="bind"),
    ]

    common_environment = {
        "PIPELINE_PROJECT_ROOT": "/workspace",
        "NEBIUS_API_KEY": os.getenv("NEBIUS_API_KEY", ""),
        "HF_TOKEN": os.getenv("HF_TOKEN", ""),
    }

    run_agent = DockerOperator(
        task_id="run_agent",
        image=_docker_image(),
        command=(
            "python -m mlops_assignment_e2e_ml_pipeline.container_entrypoint "
            "run-agent --workspace /workspace "
            "--run-id '{{ ti.xcom_pull(task_ids=\"prepare_run\")[\"run_config\"][\"run_id\"] }}'"
        ),
        mounts=mounts,
        mount_tmp_dir=False,
        working_dir="/workspace",
        environment=common_environment,
        auto_remove="success",
        tty=False,
    )

    run_eval = DockerOperator(
        task_id="run_eval",
        image=_docker_image(),
        command=(
            "python -m mlops_assignment_e2e_ml_pipeline.container_entrypoint "
            "run-eval --workspace /workspace "
            "--run-id '{{ ti.xcom_pull(task_ids=\"prepare_run\")[\"run_config\"][\"run_id\"] }}'"
        ),
        mounts=mounts,
        mount_tmp_dir=False,
        working_dir="/workspace",
        environment=common_environment,
        auto_remove="success",
        tty=False,
    )

    summarize_task = summarize(prepared)
    prepared >> run_agent >> run_eval >> summarize_task


evaluate_agent_docker()
