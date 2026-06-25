# Report

## Architecture

The assignment is implemented as an offline-first Airflow pipeline centered around:

- `dags/evaluate_agent.py`
- `dags/evaluate_agent_docker.py`
- `src/mlops_assignment_e2e_ml_pipeline/pipeline.py`

The DAG contains four explicit stages:

1. `prepare_run`
2. `run_agent`
3. `run_eval`
4. `summarize`

The implementation uses wrapper code in `src/` instead of putting all orchestration
logic directly inside the DAG. That wrapper layer is responsible for:

- building the run configuration from Airflow params
- creating a durable `runs/<run-id>/` folder
- executing `mini-swe-agent`
- executing SWE-bench evaluation
- collecting metrics
- generating a manifest
- logging params and metrics to MLflow

The repository now includes two orchestration paths:

- `evaluate-agent`: the standalone Python/subprocess path that was validated end-to-end
  on the VM
- `evaluate-agent-docker`: a production-style DAG that uses `DockerOperator` for the
  agent and evaluation stages

## Run Artifact Layout

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

Important files:

- `config.json`: exact run inputs
- `run-agent/preds.json`: predictions used by SWE-bench evaluation
- `run-agent/trajectories/`: mini-swe-agent trajectories
- `run-eval/logs/`: evaluation logs
- `run-eval/reports/`: evaluation summary JSON
- `metrics.json`: parsed aggregate metrics for the run
- `manifest.json`: paths, stage outputs, local artifact URI, and git commit

## DAG Parameters

The DAG is configurable via Airflow params or `dag_run.conf`.

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

`use_sample=true` provides an offline smoke-test mode using the provided sample artifacts.

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

Optional local MLflow tracking:

```bash
export MLFLOW_TRACKING_URI="file://$(pwd)/mlruns"
```

`mlruns/` is a local runtime-generated MLflow store. It is created when MLflow logging
is used and is intentionally not committed to git.

## How To Trigger The DAG

Start standalone Airflow:

```bash
bash run-airflow-standalone.sh
```

Then trigger `evaluate-agent` from the Airflow UI with params such as:

```json
{
  "split": "test",
  "subset": "verified",
  "workers": 1,
  "eval_max_workers": 1,
  "model": "nebius/moonshotai/Kimi-K2.6",
  "task_slice": "0:1",
  "run_id": "airflow-real-2",
  "use_sample": false
}
```

For an offline smoke test:

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

For the Docker-backed DAG, build the image first:

```bash
docker build -t mlops-assignment-e2e-ml-pipeline:local .
```

Then trigger `evaluate-agent-docker` with the same parameters and set
`HOST_PROJECT_ROOT` to the absolute host path when using `docker-compose`.

## Completed Runs

### Offline smoke test

The sample-backed offline run succeeded locally and produced a reproducible run folder
without calling Nebius or SWE-bench live services.

### Real VM pipeline run

A real VM-backed pipeline run was executed successfully with:

- dataset: `princeton-nlp/SWE-bench_Verified`
- split: `test`
- task slice: `0:1`
- workers: `1`
- eval workers: `1`
- model: `nebius/moonshotai/Kimi-K2.6`
- run id: `vm-real-pipeline-1`

Result:

- `submitted_instances = 1`
- `completed_instances = 1`
- `resolved_instances = 1`
- `resolution_rate = 1.0`

### Real Airflow DAG run

The Airflow DAG was also executed successfully end-to-end on the VM with:

- run id: `airflow-real-2`
- dataset: `princeton-nlp/SWE-bench_Verified`
- split: `test`
- task slice: `0:1`
- model: `nebius/moonshotai/Kimi-K2.6`

Result from `runs/airflow-real-2/metrics.json`:

- `submitted_instances = 1`
- `completed_instances = 1`
- `resolved_instances = 1`
- `unresolved_instances = 0`
- `resolution_rate = 1.0`

The resulting artifact folder is:

- `runs/airflow-real-2/`

## MLflow Evidence

MLflow logging succeeded during the real VM pipeline run.

- experiment: `coding-agent-evals`
- MLflow run id: `307019d1a49246a4bb261df11cb2ab11`
- tracking URI used during execution on the VM: `file:///home/ofergr/mlops-assignment-e2e-ml-pipeline/mlruns`

The MLflow store was VM-local runtime state and is intentionally excluded from git.

## Screenshots

Saved evidence in the repository:

- `screenshots/airflow_dag.png`: successful Airflow DAG run
- `screenshots/airflow_real_2_metrics.png`: terminal evidence for `runs/airflow-real-2/metrics.json`

## Rerun Instructions

1. Provision a CPU VM with Docker and Python 3.12 tooling.
2. Clone the repository and create `.env` from `.env.example`.
3. Set `NEBIUS_API_KEY` in `.env`.
4. Install dependencies with `uv sync` or `pip install -e .`.
5. Start Airflow with `bash run-airflow-standalone.sh`.
6. Trigger `evaluate-agent` with a small real config such as `task_slice = 0:1`.

To rerun a completed experiment shape, trigger the DAG again with the same parameter
set and either:

- reuse the previous `run_id` only if you intentionally want to write back into the
  same `runs/<run-id>/` folder, or
- provide a new `run_id` to create a fresh reproducible artifact folder while keeping
  the previous run untouched

For example, `airflow-real-2` can be rerun by reusing the same config:

```json
{
  "split": "test",
  "subset": "verified",
  "workers": 1,
  "eval_max_workers": 1,
  "model": "nebius/moonshotai/Kimi-K2.6",
  "task_slice": "0:1",
  "run_id": "airflow-real-2"
}
```

In practice, using a new run id such as `airflow-real-3` is safer for repeatability
because it preserves the original artifact directory for comparison.

## Notes

- This submission implements the minimum working pipeline and also includes
  production-style additions in code:
  - `dags/evaluate_agent_docker.py`
  - `docker-compose.yaml`
- The standalone DAG path (`evaluate-agent`) was validated end-to-end on the VM.
- The Docker-backed DAG and compose deployment were added as the production-style path,
  but were not the primary execution path used for the successful proof run in this session.
- Remote object storage / S3 artifact upload is not implemented.
- MLflow logging is implemented with a local file-backed store for development use.
