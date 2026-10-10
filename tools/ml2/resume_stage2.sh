#!/bin/bash
# Resume the 5% / 20% memory runs of stage 2 after a restart. Finished runs are skipped (the result files are
# append-only, one row per finished run), so this can be started any number of times.
#   bash tools/ml2/resume_stage2.sh            # both jobs, 3 lanes each
# Then, when they finish:
#   python3 tools/ml2/cost_grid.py             # cost vs number of candidates (repeatable clock)
cd "$(dirname "$0")" || exit 1
PY=~/.venvs/xv6ml/bin/python
LOG=${LOG:-/tmp}
REPS=$(cat ../../report/results2/stage2_streams.txt)
KERNEL_EVAL_OUT=kernel_eval_w16e.csv KERNEL_EVAL_LANES=/tmp/xv6E nohup $PY -u kernel_eval.py --lanes 3 --fracs 0.05,0.2 \
  --only "$REPS" --splits test,heldout --nonml fifo,clock,aging,lfu --models global,own > $LOG/stage2_standard.log 2>&1 &
KERNEL_EVAL_OUT=kernel_eval_w16f.csv KERNEL_EVAL_LANES=/tmp/xv6F nohup $PY -u kernel_eval.py --lanes 3 --fracs 0.05,0.2 \
  --only btree-mixed-s5,kv-A-s5,kv-T17-s1,sort-n40000-s3,matmul-blocked128-s1,heap-small-s1,join-zipf-s1,spmv-band-s1,chase-tree-s1,bloom-k7-s1 \
  --splits test,heldout --models cnn-kv,attention-graph,mlp-kv,ranktrees-graph,trees-kv > $LOG/stage2_nets.log 2>&1 &
echo "started; logs in $LOG/stage2_*.log"
