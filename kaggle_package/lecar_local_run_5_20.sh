#!/bin/bash
# R4, rest: LeCaR (kernel form) at 5% and 20% memory on the 74 streams, on the thesis PC (instead of Kaggle round 7).
# Results are appended to report/results2/kernel_eval_lecar.csv (resumable).
D="$(cd "$(dirname "$0")" && pwd)"; cd "$D/../tools/ml2"
PY=${PY:-python3}
OTHER=$(cat "$D/lecar_streams_full.txt"); PATAPP=$(cat "$D/lecar_streams_short.txt")
export KERNEL_EVAL_OUT=kernel_eval_lecar.csv KERNEL_EVAL_LANES=/tmp/xv6lecar
for fr in 0.2 0.05; do
  $PY -u kernel_eval.py --lanes 6 --fracs $fr --only "$OTHER" --splits test,heldout --nonml lecar --timeout 40000
  $PY -u kernel_eval.py --lanes 6 --fracs $fr --accesses 50000 --only "$PATAPP" --splits test,heldout --nonml lecar --timeout 40000
done
