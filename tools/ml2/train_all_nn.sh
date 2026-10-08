#!/bin/bash
# Train every neural scorer of the traces2 study (GPU). Sequential: one GPU.
cd "$(dirname "$0")"
PY=~/.venvs/xv6ml/bin/python
FSETS="rec,freq,sd,wr ref,aging,sfreq,idle,age,dirty \
ref,aging,sfreq,idle,age,dirty,refaults,rdist \
rec,freq,sd,wr,ref,aging,sfreq,idle,age,dirty,refaults,rdist"
for scope in btree graph kv matmul sort global; do
  for fs in $FSETS; do
    for kind in mlp rlin rmlp; do
      $PY -u train_nn.py $kind --scope $scope --features $fs 2>&1 | grep --line-buffered -v -i warn
    done
  done
  $PY -u train_nn.py gru --scope $scope 2>&1 | grep --line-buffered -v -i warn
  $PY -u train_nn.py embed --scope $scope 2>&1 | grep --line-buffered -v -i warn
done
echo ALL-NN-DONE
