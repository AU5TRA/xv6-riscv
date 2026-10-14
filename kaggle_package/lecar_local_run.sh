#!/bin/bash
# R4: LeCaR (kernel form) and, in the same build, Clock again, at 10% memory on the 74 streams.
# Results: report/results2/kernel_eval_lecar.csv (merged into kernel_eval_all.csv) and kernel_eval_lecar_clock.csv (Clock rerun, same build, NOT merged).
D="$(cd "$(dirname "$0")" && pwd)"; cd "$D/../tools/ml2"
PY=${PY:-python3}
OTHER=$(cat "$D/lecar_streams_full.txt"); PATAPP=$(cat "$D/lecar_streams_short.txt")
for pol in lecar clock; do
  if [ $pol = lecar ]; then out=kernel_eval_lecar.csv; else out=kernel_eval_lecar_clock.csv; fi
  export KERNEL_EVAL_OUT=$out KERNEL_EVAL_LANES=/tmp/xv6lecar
  $PY -u kernel_eval.py --lanes 6 --fracs 0.1 --only "$OTHER" --splits test,heldout --nonml $pol --timeout 40000
  $PY -u kernel_eval.py --lanes 6 --fracs 0.1 --accesses 50000 --only "$PATAPP" --splits test,heldout --nonml $pol --timeout 40000
done
