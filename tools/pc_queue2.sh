#!/bin/bash
# 2026-10-15 21:20: pause round 9's PC share, run her B1 on all six lanes, then resume round 9. Log: /tmp/pcqueue2.log
cd /home/gawwy/Thesis/xv6-riscv
say() { echo "$(date +%F' '%H:%M) $*"; }
ROOT_PID=211852
descendants() { local p; for p in $(pgrep -P "$1"); do echo "$p"; descendants "$p"; done; }
PIDS="$ROOT_PID $(descendants $ROOT_PID)"
say "pausing round 9 (pids: $PIDS)"
kill -STOP $PIDS
say "B1: global@32 at 5% and 20%, 74 streams"
bash kaggle_package/b1_local_run.sh
say "B1 finished; resuming round 9"
kill -CONT $PIDS
