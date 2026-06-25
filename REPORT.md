# Report

## Architecture

The repository now includes an offline-first pipeline implementation centered around
`dags/evaluate_agent.py` and `src/mlops_assignment_e2e_ml_pipeline/pipeline.py`.

The DAG implements four explicit stages:

1. `prepare_run`
2. `run_agent`
3. `run_eval`
4. `summarize`

Each run writes a durable artifact tree under `runs/<run-id>/`:

```text
runs/<run-id>/
  config.json
  manifest.json
  metrics.json
  summary.json
  run-agent/
    preds.json
    run-agent.log
    trajectories/
  run-eval/
    run-eval.log
    logs/
    reports/
```

`config.json` records the exact inputs. `metrics.json` contains the parsed evaluation
results and aggregate trajectory stats. `manifest.json` points to the important files
and captures the local artifact URI plus the current git commit if available.

## DAG Parameters

The DAG is configurable through Airflow params or `dag_run.conf`.

Required:

- `split`
- `subset`
- `workers`

Useful optional params:

- `model`
- `task_slice`
- `run_id`
- `cost_limit`
- `agent_config_path`
- `mlflow_tracking_uri`
- `mlflow_experiment`
- `eval_max_workers`
- `use_sample`

`use_sample=true` is an offline smoke-test mode that materializes the provided sample
artifacts into a run folder without calling Nebius, mini-swe-agent, or SWE-bench.

## Local Setup

Create and activate the environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -e .
```

If you want local MLflow tracking without a remote server, set:

```bash
export MLFLOW_TRACKING_URI="file://$(pwd)/mlruns"
```

## How To Trigger The DAG

Standalone Airflow:

```bash
bash run-airflow-standalone.sh
```

Then trigger `evaluate-agent` with params such as:

```json
{
  "split": "test",
  "subset": "verified",
  "workers": 1,
  "model": "nebius/moonshotai/Kimi-K2.6",
  "task_slice": "0:3",
  "run_id": "offline-sample",
  "use_sample": true
}
```

For a real run, switch `use_sample` to `false`, provide `NEBIUS_API_KEY`, and make sure
the runtime has Docker plus the required upstream tooling installed.

## Offline Work Completed

- Added a proper `src/` Python package so the project can be installed locally.
- Added an offline-first Airflow DAG for the full `run-agent -> run-eval -> summarize` flow.
- Added durable run-folder creation, metrics extraction, manifest generation, and MLflow logging.
- Added a sample-backed smoke-test mode for local validation before Nebius deployment.

## Nebius / VM Work Remaining

- Install Docker, Airflow runtime tooling, and the project dependencies on the VM.
- Add `NEBIUS_API_KEY` to `.env`.
- Run a real `mini-swe-agent` batch against Nebius-backed inference.
- Run SWE-bench evaluation in the target environment.
- Optionally add object storage upload and a `docker-compose` deployment for Airflow + MLflow.
