#!/bin/bash
# the thesis PC's share of this round (resumable); results in report/results2/kernel_eval_more.csv
cd "$(dirname "$0")/../../tools/ml2"
export KERNEL_EVAL_OUT=kernel_eval_more.csv KERNEL_EVAL_LANES=/tmp/xv6more
PY=${PY:-python3}
$PY -u kernel_eval.py --lanes 6 --fracs 0.05 --only "lzw-r30-s4$,graph-bfs2000-s2$,btree-scan-s3$,btree-scan-s5$,kv-F-s5$,kv-F-s3$,kv-F-s4$,sort-n60000-s3$,sort-n60000-s2$" --splits test,heldout --nonml fifo,clock,aging,lfu,arck,s3fifo,lhd --models global --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.05 --accesses 50000 --only "pat-switch-s1$,pat-scanhotlo-s5$,pat-zipf060-s5$,pat-zipf080-s5$,pat-phaseshort-s5$" --splits test,heldout --nonml fifo,clock,aging,lfu,arck,s3fifo,lhd --models global --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.2 --only "lzw-r30-s1$,lzw-r30-s3$,lzw-r30-s2$,lzw-r30-s5$,lzw-r30-s4$,graph-bfs2000-s2$,btree-scan-s3$,btree-scan-s5$,kv-F-s5$,kv-F-s3$,sort-n60000-s3$,sort-n60000-s2$" --splits test,heldout --nonml fifo,clock,aging,lfu,arck,s3fifo,lhd --models global --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.2 --accesses 50000 --only "pat-switch-s1$,pat-scanhotlo-s5$,pat-zipf060-s5$,pat-zipf080-s5$,pat-zipf120-s1$,pat-phaseshort-s5$" --splits test,heldout --nonml fifo,clock,aging,lfu,arck,s3fifo,lhd --models global --timeout 40000
