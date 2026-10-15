#!/bin/bash
# round 9 notebook 6's share, run on the thesis PC instead (Kaggle allows 5 sessions at once); results in report/results2/kernel_eval_sizes.csv
cd "$(dirname "$0")/../../tools/ml2"
export KERNEL_EVAL_OUT=kernel_eval_sizes.csv KERNEL_EVAL_LANES=/tmp/xv6sizes
PY=${PY:-python3}
$PY -u kernel_eval.py --lanes 6 --fracs 0.05 --only "chase-list-s1$,btree-lookup-s5$,btree-scan-s5$,kv-T24-s1$" --splits test,heldout --models cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.2 --only "lzw-r20-s5$,bloom-k3-s1$,btree-mixedwal-s5$,kv-T4-s1$,sort-n60000-s2$" --splits test,heldout --models cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
$PY -u kernel_eval.py --lanes 6 --fracs 0.2 --accesses 50000 --only "pat-scanhot-s5$,pat-scanhotlo-s5$,app-hashjoin-s1$" --splits test,heldout --models cnn-all,mlp-all,attention-all,trees-all,ranktrees-all --timeout 40000
