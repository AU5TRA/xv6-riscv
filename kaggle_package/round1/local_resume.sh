#!/bin/bash
# restart the local jobs on this machine's share only (finished runs are skipped)
cd /home/gawwy/Thesis/xv6-riscv/tools/ml2 || exit 1
PY=~/.venvs/xv6ml/bin/python
LOG=${LOG:-/tmp}
KERNEL_EVAL_OUT=kernel_eval_w16e.csv KERNEL_EVAL_LANES=/tmp/xv6E nohup $PY -u kernel_eval.py --lanes 3 --fracs 0.05,0.2 --only "bloom-k3-s1,chase-tree-s1,heap-churn-s1,spmv-rand-s1,btree-scan-s1,join-uni-s1,join-zipf-s1,join-r4-s1,kv-Avsize-s5,kv-A-s5,kv-B-s5,kv-T17-s1,kv-T18-s1,kv-T35-s1" --splits test,heldout --nonml fifo,clock,aging,lfu --models global,own > $LOG/local_standard.log 2>&1 &
KERNEL_EVAL_OUT=kernel_eval_w16f.csv KERNEL_EVAL_LANES=/tmp/xv6F nohup $PY -u kernel_eval.py --lanes 3 --fracs 0.05,0.2 --only "sort-n40000-s3" --splits test,heldout --models cnn-kv,attention-graph,mlp-kv,ranktrees-graph,trees-kv > $LOG/local_nets.log 2>&1 &
