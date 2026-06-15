MSWEA_COST_TRACKING='ignore_errors' mini-extra swebench-single \
    --subset verified \
    --split test \
    --model nebius/Qwen/Qwen3-30B-A3B-Instruct-2507 \
    --yolo \
    --cost-limit 0 \
    -i sympy__sympy-15599 \
    -o trajectory.json
