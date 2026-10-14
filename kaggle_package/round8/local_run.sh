#!/bin/bash
# the thesis PC's share of this round (resumable); results in report/results2/kernel_eval_sampling.csv
cd "$(dirname "$0")/../../tools/ml2"
export KERNEL_EVAL_OUT=kernel_eval_sampling.csv KERNEL_EVAL_LANES=/tmp/xv6sampling
PY=${PY:-python3}
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --only "lzw-r30-s3$,lzw-r30-s2$,lzw-r30-s5$,lzw-r20-s5$,lzw-r30-s4$,heap-small-s1$,graph-bfs2000-s1$,graph-bfs2000-s2$,graph-bfs2000-s3$,heap-churn-s1$,graph-both2000x1-s5$,graph-pr2000x2-s3$,graph-both1000x3-s3$,matmul-naive128-s1$,btree-scan-s2$,btree-scan-s4$,btree-scan-s1$,btree-scan-s3$,join-uni-s1$,btree-lookup-s5$,join-zipf-s1$,btree-insert-s5$,btree-mixedwal-s5$,join-r4-s1$,btree-mixed-s5$,kv-Arehash-s5$,kv-F-s1$,kv-F-s5$,kv-F-s2$,kv-A-s5$,kv-D-s5$,spmv-band-s1$,kv-T24-s1$,kv-T17-s1$,kv-T18-s1$,matmul-blocked128-s1$,kv-T35-s1$,sort-n60000-s1$,sort-n60000-s2$,sort-n20000-s3$" --splits test,heldout --models global@32,global@32n,global@32s,global@16,global@16n,global@16s --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.1 --accesses 50000 --only "pat-loop-s5$,pat-uniform-s5$,pat-switch-s1$,pat-scanhotlo-s5$,app-chase-s1$,pat-zipf060-s5$,pat-zipf080-s5$,pat-zipf120-s1$,pat-zipf099-s5$,pat-phaseshort-s5$,app-hashjoin-s1$,pat-phase-s5$,app-spmv-s1$" --splits test,heldout --models global@32,global@32n,global@32s,global@16,global@16n,global@16s --timeout 40000
