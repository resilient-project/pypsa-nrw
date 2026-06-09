#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

AVAILABLE_CORES="$(nproc)"
AVAILABLE_MEM_MB="$(( $(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo) ))"
DEFAULT_MEM_MB="$(( AVAILABLE_MEM_MB * 9 / 10 ))"
DEFAULT_CORES="$(( AVAILABLE_CORES < 28 ? AVAILABLE_CORES : 28 ))"

BASE_CONFIG="${BASE_CONFIG:-$REPO_ROOT/config/config.nrw.yaml}"
if [[ -x "$REPO_ROOT/.pixi/envs/default/bin/snakemake" ]]; then
    DEFAULT_SNAKEMAKE_BIN="$REPO_ROOT/.pixi/envs/default/bin/snakemake"
else
    DEFAULT_SNAKEMAKE_BIN="snakemake"
fi
SNAKEMAKE_BIN="${SNAKEMAKE_BIN:-$DEFAULT_SNAKEMAKE_BIN}"
CORES="${CORES:-$DEFAULT_CORES}"
SOLVER_THREADS="${SOLVER_THREADS:-$CORES}"
MEM_MB="${MEM_MB:-$DEFAULT_MEM_MB}"
GUROBI_RES="${GUROBI_RES:-1}"
SCHEDULER="${SCHEDULER:-greedy}"
LATENCY_WAIT="${LATENCY_WAIT:-60}"

usage() {
    cat <<'EOF'
Usage:
  ./run_scenarios_sequentially.sh [scenario1 scenario2 ...] [-- extra snakemake args]

Examples:
  ./run_scenarios_sequentially.sh
  ./run_scenarios_sequentially.sh endo-grid___CCS-Exp__offshore-co2
  ./run_scenarios_sequentially.sh oge-grid___Ref___offshore-co2 -- --rerun-triggers mtime

Behavior:
  - If no scenarios are given, the script reads run.name from config/config.nrw.yaml.
  - It then runs Snakemake once per scenario, sequentially.
  - This avoids launching multiple scenario DAGs together and is useful when Gurobi
    should only be used by one scenario run at a time.

Environment overrides:
  BASE_CONFIG, SNAKEMAKE_BIN, CORES, SOLVER_THREADS, MEM_MB, GUROBI_RES, SCHEDULER, LATENCY_WAIT
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ ! -f "$BASE_CONFIG" ]]; then
    echo "Base config not found: $BASE_CONFIG" >&2
    exit 1
fi

SCENARIOS=()
EXTRA_ARGS=()
PARSING_EXTRA=0

for arg in "$@"; do
    if [[ "$arg" == "--" ]]; then
        PARSING_EXTRA=1
        continue
    fi

    if [[ "$PARSING_EXTRA" -eq 1 ]]; then
        EXTRA_ARGS+=("$arg")
    else
        SCENARIOS+=("$arg")
    fi
done

if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
    mapfile -t SCENARIOS < <(
        python3 - "$BASE_CONFIG" <<'PY'
import sys
from pathlib import Path
import yaml

config_path = Path(sys.argv[1])
with config_path.open() as f:
    config = yaml.safe_load(f)

names = config.get("run", {}).get("name", [])
if isinstance(names, str):
    names = [names]

for name in names:
    print(name)
PY
    )
fi

if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
    echo "No scenarios found. Pass scenario names explicitly or set run.name in $BASE_CONFIG" >&2
    exit 1
fi

echo "Base config: $BASE_CONFIG"
echo "Scenarios to run sequentially: ${SCENARIOS[*]}"
echo "Detected machine resources: ${AVAILABLE_CORES} CPU cores, ${AVAILABLE_MEM_MB} MB available memory"
echo "Using Snakemake cores: $CORES"
echo "Using solver threads: $SOLVER_THREADS"
echo "Using global memory resource: $MEM_MB MB"

for scenario in "${SCENARIOS[@]}"; do
    tmp_config="$(mktemp "${TMPDIR:-/tmp}/nrw-scenario-${scenario//[^A-Za-z0-9_-]/_}.XXXXXX.yaml")"

    python3 - "$BASE_CONFIG" "$tmp_config" "$scenario" "$SOLVER_THREADS" <<'PY'
import sys
from pathlib import Path
import yaml

base_config = Path(sys.argv[1])
tmp_config = Path(sys.argv[2])
scenario = sys.argv[3]
solver_threads = int(sys.argv[4])

with base_config.open() as f:
    config = yaml.safe_load(f)

config.setdefault("run", {})
config["run"]["name"] = [scenario]

solving = config.setdefault("solving", {})
solver = solving.setdefault("solver", {})
option_set = solver.get("options", "gurobi-default")
solver_options = solving.setdefault("solver_options", {})
option_cfg = solver_options.setdefault(option_set, {})
if "Threads" in option_cfg:
    option_cfg["Threads"] = solver_threads
else:
    option_cfg["threads"] = solver_threads

with tmp_config.open("w") as f:
    yaml.safe_dump(config, f, sort_keys=False)
PY

    echo
    echo "============================================================"
    echo "Running scenario: $scenario"
    echo "Temporary config: $tmp_config"
    echo "============================================================"

    "$SNAKEMAKE_BIN" \
        --directory "$REPO_ROOT" \
        --configfile "$tmp_config" \
        --cores "$CORES" \
        --resources mem_mb="$MEM_MB" gurobi="$GUROBI_RES" \
        --scheduler "$SCHEDULER" \
        --latency-wait "$LATENCY_WAIT" \
        --rerun-incomplete \
        "${EXTRA_ARGS[@]}"

    rm -f "$tmp_config"
done

echo
echo "All scenario runs finished successfully."
