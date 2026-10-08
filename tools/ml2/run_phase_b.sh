#!/bin/bash
# Everything after the 10% sweep, in dependency order.
cd "$(dirname "$0")"
PY=~/.venvs/xv6ml/bin/python
set -e
step() { echo "=== $* ($(date +%H:%M:%S))"; "$@" 2>&1 | grep --line-buffered -v -i warn; }
[ -n "$SKIP_DONE" ] || step $PY -u extras.py matmul_train --jobs 6
[ -n "$SKIP_DONE" ] || step $PY -u final.py select --jobs 6
[ -n "$SKIP_DONE" ] || step $PY -u final.py test --jobs 6
step $PY -u eval_nn.py --jobs 6
step $PY -u extras.py protect --jobs 6
step $PY -u extras.py quant --jobs 6
step $PY -u extras.py dagger --jobs 6
step $PY -u analyze.py
echo "=== PHASE-B-DONE ($(date +%H:%M:%S))"
