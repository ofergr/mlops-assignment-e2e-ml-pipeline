from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = PROJECT_ROOT / "runs"
DEFAULT_MODEL = "nebius/moonshotai/Kimi-K2.6"
DEFAULT_EXPERIMENT = "coding-agent-evals"
DEFAULT_DATASET_BY_SUBSET = {
    "verified": "princeton-nlp/SWE-bench_Verified",
    "lite": "princeton-nlp/SWE-bench_Lite",
}


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot complete successfully."""


@dataclass(frozen=True)
class RunLayout:
    run_dir: Path
    config_path: Path
    agent_dir: Path
    trajectories_dir: Path
    preds_path: Path
    eval_dir: Path
    eval_logs_dir: Path
    eval_reports_dir: Path
    metrics_path: Path
    manifest_path: Path


def build_run_config(params: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {**params, **(overrides or {})}
    split = str(merged.get("split", "test"))
    subset = str(merged.get("subset", "verified"))
    workers = int(merged.get("workers", 1))
    model = str(merged.get("model", DEFAULT_MODEL))
    task_slice = _normalize_optional_string(merged.get("task_slice"))
    run_id = _normalize_optional_string(merged.get("run_id")) or _default_run_id()
    cost_limit = _normalize_optional_string(merged.get("cost_limit"))
    agent_config_path = _normalize_optional_string(merged.get("agent_config_path"))
    mlflow_tracking_uri = _normalize_optional_string(
        merged.get("mlflow_tracking_uri") or os.getenv("MLFLOW_TRACKING_URI")
    )
    mlflow_experiment = str(
        merged.get("mlflow_experiment") or os.getenv("MLFLOW_EXPERIMENT_NAME") or DEFAULT_EXPERIMENT
    )
    use_sample = _coerce_bool(merged.get("use_sample", False))

    config = {
        "run_id": run_id,
        "split": split,
        "subset": subset,
        "workers": workers,
        "eval_max_workers": int(merged.get("eval_max_workers", workers)),
        "model": model,
        "task_slice": task_slice,
        "cost_limit": cost_limit,
        "agent_config_path": agent_config_path,
        "dataset_name": str(merged.get("dataset_name") or infer_dataset_name(subset)),
        "mlflow_tracking_uri": mlflow_tracking_uri,
        "mlflow_experiment": mlflow_experiment,
        "artifact_root": str(RUNS_ROOT),
        "use_sample": use_sample,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }

    if config["workers"] < 1 or config["eval_max_workers"] < 1:
        raise PipelineError("workers and eval_max_workers must be >= 1")

    return config


def prepare_run_dir(run_config: dict[str, Any]) -> RunLayout:
    run_dir = RUNS_ROOT / run_config["run_id"]
    agent_dir = run_dir / "run-agent"
    trajectories_dir = agent_dir / "trajectories"
    eval_dir = run_dir / "run-eval"
    eval_logs_dir = eval_dir / "logs"
    eval_reports_dir = eval_dir / "reports"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    eval_logs_dir.mkdir(parents=True, exist_ok=True)
    eval_reports_dir.mkdir(parents=True, exist_ok=True)

    layout = RunLayout(
        run_dir=run_dir,
        config_path=run_dir / "config.json",
        agent_dir=agent_dir,
        trajectories_dir=trajectories_dir,
        preds_path=agent_dir / "preds.json",
        eval_dir=eval_dir,
        eval_logs_dir=eval_logs_dir,
        eval_reports_dir=eval_reports_dir,
        metrics_path=run_dir / "metrics.json",
        manifest_path=run_dir / "manifest.json",
    )
    write_json(layout.config_path, run_config)
    return layout


def run_agent_batch(run_config: dict[str, Any], layout: RunLayout) -> dict[str, Any]:
    if run_config.get("use_sample"):
        return _materialize_sample_agent_run(layout)

    command = [
        _resolve_executable("mini-extra"),
        "swebench",
        "--subset",
        run_config["subset"],
        "--split",
        run_config["split"],
        "--model",
        run_config["model"],
        "--workers",
        str(run_config["workers"]),
        "-o",
        "trajectories",
    ]

    if run_config.get("task_slice"):
        command.extend(["--slice", run_config["task_slice"]])
    if run_config.get("cost_limit"):
        command.extend(["--cost-limit", str(run_config["cost_limit"])])
    if run_config.get("agent_config_path"):
        command.extend(["--config", run_config["agent_config_path"]])

    log_path = layout.agent_dir / "run-agent.log"
    _run_command(
        command,
        cwd=layout.agent_dir,
        env={"MSWEA_COST_TRACKING": "ignore_errors"},
        log_path=log_path,
    )

    source_preds_path = layout.trajectories_dir / "preds.json"
    if not source_preds_path.exists():
        raise PipelineError(f"mini-swe-agent did not produce predictions at {source_preds_path}")

    shutil.copy2(source_preds_path, layout.preds_path)
    return {
        "predictions_path": str(layout.preds_path),
        "trajectories_dir": str(layout.trajectories_dir),
        "agent_log_path": str(log_path),
        "used_sample": False,
    }


def run_swebench_eval(run_config: dict[str, Any], preds_path: Path, layout: RunLayout) -> dict[str, Any]:
    if run_config.get("use_sample"):
        return _materialize_sample_eval_run(run_config, layout)

    command = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        run_config["dataset_name"],
        "--predictions_path",
        str(preds_path),
        "--max_workers",
        str(run_config["eval_max_workers"]),
        "--run_id",
        run_config["run_id"],
    ]

    log_path = layout.eval_dir / "run-eval.log"
    _run_command(command, cwd=layout.run_dir, env=None, log_path=log_path)

    generated_logs_dir = layout.run_dir / "logs"
    if generated_logs_dir.exists():
        _replace_dir(generated_logs_dir, layout.eval_logs_dir)

    summary_paths = [
        path
        for path in layout.run_dir.glob("*.json")
        if path.name not in {layout.config_path.name, layout.metrics_path.name, layout.manifest_path.name}
    ]
    summary_destinations: list[str] = []
    for summary_path in summary_paths:
        destination = layout.eval_reports_dir / summary_path.name
        shutil.move(str(summary_path), destination)
        summary_destinations.append(str(destination))

    return {
        "eval_log_path": str(log_path),
        "eval_logs_dir": str(layout.eval_logs_dir),
        "report_paths": summary_destinations,
        "used_sample": False,
    }


def collect_metrics(run_config: dict[str, Any], layout: RunLayout) -> dict[str, Any]:
    summary = _load_summary_metrics(layout.eval_reports_dir)
    per_instance_reports = list(layout.eval_logs_dir.glob("run_evaluation/**/*.json"))
    report_paths = [path for path in per_instance_reports if path.name == "report.json"]
    report_payloads = [_load_json(path) for path in report_paths]
    report_entries: dict[str, Any] = {}
    for payload in report_payloads:
        report_entries.update(payload)

    resolved_ids = sorted(
        [instance_id for instance_id, report in report_entries.items() if bool(report.get("resolved"))]
    )
    unresolved_ids = sorted(
        [instance_id for instance_id, report in report_entries.items() if not bool(report.get("resolved"))]
    )
    patch_apply_failures = sorted(
        [
            instance_id
            for instance_id, report in report_entries.items()
            if not bool(report.get("patch_successfully_applied", False))
        ]
    )

    total_api_calls = 0
    total_instance_cost = 0.0
    trajectory_count = 0
    for trajectory_path in layout.trajectories_dir.glob("*/*.traj.json"):
        payload = _load_json(trajectory_path)
        model_stats = payload.get("info", {}).get("model_stats", {})
        total_api_calls += int(model_stats.get("api_calls", 0) or 0)
        total_instance_cost += float(model_stats.get("instance_cost", 0.0) or 0.0)
        trajectory_count += 1

    metrics = {
        "run_id": run_config["run_id"],
        "resolved_instances": int(summary.get("resolved_instances", len(resolved_ids))),
        "unresolved_instances": int(summary.get("unresolved_instances", len(unresolved_ids))),
        "submitted_instances": int(summary.get("submitted_instances", len(report_entries))),
        "completed_instances": int(summary.get("completed_instances", len(report_entries))),
        "total_instances": int(summary.get("total_instances", len(report_entries))),
        "error_instances": int(summary.get("error_instances", 0)),
        "empty_patch_instances": int(summary.get("empty_patch_instances", 0)),
        "trajectory_count": trajectory_count,
        "evaluation_report_count": len(report_entries),
        "patch_apply_failures": len(patch_apply_failures),
        "total_api_calls": total_api_calls,
        "total_instance_cost": round(total_instance_cost, 6),
        "resolution_rate": round(_safe_divide(len(resolved_ids), max(len(report_entries), 1)), 4),
        "resolved_ids": resolved_ids,
        "unresolved_ids": unresolved_ids,
        "patch_apply_failure_ids": patch_apply_failures,
    }
    write_json(layout.metrics_path, metrics)
    return metrics


def build_manifest(
    run_config: dict[str, Any],
    layout: RunLayout,
    metrics: dict[str, Any],
    agent_result: dict[str, Any],
    eval_result: dict[str, Any],
) -> dict[str, Any]:
    manifest = {
        "run_id": run_config["run_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "config": {
            "path": _relative_to_root(layout.config_path),
            "values": run_config,
        },
        "artifacts": {
            "run_dir": _relative_to_root(layout.run_dir),
            "predictions_path": _relative_to_root(layout.preds_path),
            "trajectories_dir": _relative_to_root(layout.trajectories_dir),
            "eval_logs_dir": _relative_to_root(layout.eval_logs_dir),
            "eval_reports_dir": _relative_to_root(layout.eval_reports_dir),
            "metrics_path": _relative_to_root(layout.metrics_path),
        },
        "stage_outputs": {
            "run_agent": agent_result,
            "run_eval": eval_result,
        },
        "summary": {
            "submitted_instances": metrics["submitted_instances"],
            "resolved_instances": metrics["resolved_instances"],
            "resolution_rate": metrics["resolution_rate"],
            "total_api_calls": metrics["total_api_calls"],
            "total_instance_cost": metrics["total_instance_cost"],
        },
        "storage": {
            "local_artifact_uri": layout.run_dir.resolve().as_uri(),
            "remote_artifact_uri": None,
        },
    }
    write_json(layout.manifest_path, manifest)
    return manifest


def log_mlflow_run(run_config: dict[str, Any], metrics: dict[str, Any], layout: RunLayout) -> dict[str, Any]:
    tracking_uri = run_config.get("mlflow_tracking_uri") or (PROJECT_ROOT / "mlruns").resolve().as_uri()
    if tracking_uri.startswith("file:"):
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    try:
        import mlflow
    except ImportError as exc:
        return {
            "status": "skipped",
            "reason": f"mlflow import failed: {exc}",
            "tracking_uri": tracking_uri,
        }

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(run_config["mlflow_experiment"])

    with mlflow.start_run(run_name=run_config["run_id"]) as run:
        flattened_params = _flatten_for_mlflow(run_config)
        metric_values = {
            key: value
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        mlflow.log_params(flattened_params)
        mlflow.log_metrics(metric_values)
        mlflow.set_tags(
            {
                "run_id": run_config["run_id"],
                "subset": run_config["subset"],
                "split": run_config["split"],
                "model": run_config["model"],
            }
        )
        mlflow.log_artifacts(str(layout.run_dir), artifact_path="run-artifacts")
        return {
            "status": "logged",
            "tracking_uri": tracking_uri,
            "experiment": run_config["mlflow_experiment"],
            "mlflow_run_id": run.info.run_id,
        }


def infer_dataset_name(subset: str) -> str:
    return DEFAULT_DATASET_BY_SUBSET.get(subset, "princeton-nlp/SWE-bench_Verified")


def summarize_and_log(run_config: dict[str, Any], layout: RunLayout, agent_result: dict[str, Any], eval_result: dict[str, Any]) -> dict[str, Any]:
    metrics = collect_metrics(run_config, layout)
    manifest = build_manifest(run_config, layout, metrics, agent_result, eval_result)
    mlflow_status = log_mlflow_run(run_config, metrics, layout)
    result = {
        "run_id": run_config["run_id"],
        "run_dir": str(layout.run_dir),
        "metrics": metrics,
        "manifest_path": str(layout.manifest_path),
        "mlflow": mlflow_status,
        "manifest": manifest,
    }
    write_json(layout.run_dir / "summary.json", result)
    return result


def _materialize_sample_agent_run(layout: RunLayout) -> dict[str, Any]:
    sample_trajectories_dir = PROJECT_ROOT / "sample" / "trajectories"
    _replace_dir(sample_trajectories_dir, layout.trajectories_dir)
    source_preds_path = layout.trajectories_dir / "preds.json"
    shutil.copy2(source_preds_path, layout.preds_path)
    sample_log = layout.trajectories_dir / "minisweagent.log"
    return {
        "predictions_path": str(layout.preds_path),
        "trajectories_dir": str(layout.trajectories_dir),
        "agent_log_path": str(sample_log),
        "used_sample": True,
    }


def _materialize_sample_eval_run(run_config: dict[str, Any], layout: RunLayout) -> dict[str, Any]:
    sample_summary_candidates = sorted((PROJECT_ROOT / "sample").glob("*.json"))
    if not sample_summary_candidates:
        raise PipelineError("sample summary JSON is missing")

    sample_logs_dir = PROJECT_ROOT / "sample" / "logs"
    _replace_dir(sample_logs_dir, layout.eval_logs_dir)

    report_destinations = []
    for sample_summary_path in sample_summary_candidates:
        destination = layout.eval_reports_dir / sample_summary_path.name
        shutil.copy2(sample_summary_path, destination)
        report_destinations.append(str(destination))

    return {
        "eval_log_path": None,
        "eval_logs_dir": str(layout.eval_logs_dir),
        "report_paths": report_destinations,
        "used_sample": True,
        "run_id": run_config["run_id"],
    }


def _run_command(command: list[str], cwd: Path, env: dict[str, str] | None, log_path: Path) -> None:
    combined_env = {**os.environ, **(env or {})}
    process = subprocess.run(
        command,
        cwd=cwd,
        env=combined_env,
        text=True,
        capture_output=True,
        check=False,
    )
    log_path.write_text(process.stdout + ("\n" if process.stdout and process.stderr else "") + process.stderr)
    if process.returncode != 0:
        raise PipelineError(
            f"Command failed with exit code {process.returncode}: {' '.join(command)}. See {log_path}"
        )


def _resolve_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable:
        return executable
    local_candidate = PROJECT_ROOT / ".venv" / "bin" / name
    if local_candidate.exists():
        return str(local_candidate)
    raise PipelineError(f"Could not find executable '{name}'. Install project dependencies first.")


def _replace_dir(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _load_summary_metrics(eval_reports_dir: Path) -> dict[str, Any]:
    summary_paths = sorted(eval_reports_dir.glob("*.json"))
    for summary_path in summary_paths:
        payload = _load_json(summary_path)
        if isinstance(payload, dict) and "resolved_instances" in payload:
            return payload
    return {}


def _load_json(path: Path) -> Any:
    with path.open() as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _flatten_for_mlflow(payload: dict[str, Any]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            flattened[key] = str(value)
        else:
            flattened[key] = json.dumps(value, sort_keys=True)
    return flattened


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _git_commit() -> str | None:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        return None
    return process.stdout.strip()


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
