#!/bin/bash
# The thesis PC's queue (2026-10-15), one job after another. Log: /tmp/pcqueue.log
cd /home/gawwy/Thesis/xv6-riscv
say() { echo "$(date +%F' '%H:%M) $*"; }
say "waiting for the cost grid (job 1) to finish"
until grep -q "^done" /tmp/cg2.log; do sleep 60; done
say "job 2: exact instruction counts on one stream per workload (QEMU counting mode) -> report/results2/kernel_eval_icount.csv"
cd tools/ml2
export QEMU_ICOUNT=1 KERNEL_EVAL_OUT=kernel_eval_icount.csv KERNEL_EVAL_LANES=/tmp/xv6icount
python3 -u kernel_eval.py --lanes 6 --fracs 0.1 --only "bloom-k3-s1$,btree-mixed-s5$,chase-n256-s1$,graph-both1000x3-s3$,heap-mixed-s1$,join-r4-s1$,kv-B-s5$,kv-T35-s1$,lzw-r30-s4$,matmul-blocked128-s1$,sort-n20000-s3$,spmv-band-s1$" --splits test,heldout --nonml fifo,clock,aging,lfu,s3fifo,arck,lhd,lecar --models global,global@64,global@32,global@16,global@8,global@4 --timeout 40000
python3 -u kernel_eval.py --lanes 6 --fracs 0.1 --accesses 50000 --only "app-hashjoin-s1$,pat-phase-s5$" --splits test,heldout --nonml fifo,clock,aging,lfu,s3fifo,arck,lhd,lecar --models global,global@64,global@32,global@16,global@8,global@4 --timeout 40000
python3 -u kernel_eval.py --lanes 6 --fracs 0.1 --only "btree-mixed-s5$,join-r4-s1$,kv-B-s5$,kv-T35-s1$,matmul-blocked128-s1$,sort-n20000-s3$,spmv-band-s1$" --splits test,heldout --models trees-all,ranktrees-all,attention-all,cnn-all,mlp-all --timeout 40000
python3 -u kernel_eval.py --lanes 6 --fracs 0.1 --accesses 50000 --only "app-hashjoin-s1\$,pat-phase-s5\$" --splits test,heldout --models trees-all,ranktrees-all,attention-all,cnn-all,mlp-all --timeout 40000
unset QEMU_ICOUNT
cd ../..
say "job 4: round 9, this PC's share"; bash kaggle_package/round9/local_run.sh
say "job 4b: round 9, notebook 6's share (Kaggle allows 5 sessions)"; bash kaggle_package/round9/local_run_notebook6.sh
say "job 3: paper handoff B1, 32-sample at 5% and 20%"; bash kaggle_package/b1_local_run.sh
say "queue done (round 8's PC share needs the sampling patch applied by Claude first)"
