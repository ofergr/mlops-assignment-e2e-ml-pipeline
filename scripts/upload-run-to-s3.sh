#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <run-id>" >&2
  exit 2
fi

run_id="$1"
run_dir="runs/${run_id}"

if [[ ! -d "${run_dir}" ]]; then
  echo "Run directory not found: ${run_dir}" >&2
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "AWS CLI is required as the S3-compatible client. This can upload to Nebius Object Storage." >&2
  exit 1
fi

: "${S3_BUCKET:?Set S3_BUCKET}"
: "${S3_ENDPOINT_URL:?Set S3_ENDPOINT_URL for the Nebius Object Storage S3-compatible endpoint}"
: "${S3_PREFIX:=mlops-assignment-runs}"

destination="s3://${S3_BUCKET}/${S3_PREFIX}/${run_id}/"

aws s3 sync "${run_dir}/" "${destination}" \
  --endpoint-url "${S3_ENDPOINT_URL}" \
  --only-show-errors

echo "${destination}"
