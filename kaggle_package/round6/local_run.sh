#!/bin/bash
# the thesis PC's share of this round (resumable); results in report/results2/kernel_eval_models.csv
cd "$(dirname "$0")/../../tools/ml2"
export KERNEL_EVAL_OUT=kernel_eval_models.csv KERNEL_EVAL_LANES=/tmp/xv6models
PY=${PY:-python3}
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --accesses 50000 --only "pat-loop-s5$,pat-uniform-s5$,app-bloom-s1$,app-chase-s1$,app-hashjoin-s1$,pat-phase-s5$,app-spmv-s1$" --splits test,heldout --models cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --only "kv-T17-s1$" --splits test,heldout --models global@16 --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --only "kv-T24-s1$,kv-T4-s1$" --splits test,heldout --models global@16,cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --only "heap-small-s1$,join-zipf-s1$,btree-mixed-s5$,kv-A-s5$,spmv-band-s1$,matmul-blocked128-s1$,sort-n40000-s3$" --splits test,heldout --models global@32,global@16 --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --only "lzw-r30-s2$,lzw-r30-s5$,lzw-r20-s5$,lzw-r30-s4$,bloom-k3-s1$,graph-bfs2000-s1$,chase-n256-s1$,heap-churn-s1$,graph-both2000x1-s5$,heap-mixed-s1$,graph-pr2000x2-s3$,graph-both1000x3-s3$,btree-scan-s4$,btree-scan-s1$,btree-scan-s3$,btree-scan-s5$,join-uni-s1$,btree-insert-s5$,btree-mixedwal-s5$,kv-Avsize-s5$,kv-F-s5$,kv-F-s3$,kv-F-s2$,kv-F-s4$,kv-D-s5$,kv-B-s5$,sort-n60000-s1$,sort-n60000-s2$" --splits test,heldout --models global@32,global@16,cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --accesses 50000 --only "pat-scanhotlo-s5$,pat-zipf060-s5$,pat-phaseshort-s5$" --splits test,heldout --models global@32,global@16,cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
