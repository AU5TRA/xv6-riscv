<!-- classical_test -->
**Classical policies, test streams — faults / Clock (geo-mean over 5/10/20%)**

| workload | FIFO | Aging | decayed LFU | LRU | exact LFU | old SD | Belady |
|---|---|---|---|---|---|---|---|
| btree | 1.126 | 1.118 | 1.125 | 0.994 | 0.943 | 1.040 | 0.550 |
| graph | 1.418 | 1.286 | 1.399 | 0.990 | ≥3.000 | 1.319 | 0.456 |
| kv | 1.163 | 1.097 | 1.151 | 0.986 | 1.190 | 1.124 | 0.571 |
| sort | 1.030 | 1.011 | 1.011 | 1.012 | ≥2.919 | 1.030 | 0.830 |

*Clock = 1; below 1 is better. ≥: some runs stopped at 3× Clock (lower bound).*

<!-- classical_heldout -->
**Classical policies, heldout streams — faults / Clock (geo-mean over 5/10/20%)**

| workload | FIFO | Aging | decayed LFU | LRU | exact LFU | old SD | Belady |
|---|---|---|---|---|---|---|---|
| btree | 1.066 | 1.060 | 1.066 | 0.997 | 0.871 | 1.049 | 0.615 |
| graph | 1.326 | 1.315 | 1.325 | 0.992 | 1.623 | 1.301 | 0.482 |
| kv | 1.166 | 1.121 | 1.161 | 0.982 | 1.001 | 1.123 | 0.577 |
| matmul | 1.077 | 0.931 | 0.931 | 0.879 | ≥3.000 | 1.077 | 0.617 |
| sort | 1.000 | 0.999 | 0.998 | 0.999 | ≥3.000 | 1.000 | 0.896 |

*Clock = 1; below 1 is better. ≥: some runs stopped at 3× Clock (lower bound).*

<!-- headline_workload_test -->
**Validation-selected linear model per tier (per-workload model), test — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- headline_workload_heldout -->
**Validation-selected linear model per tier (per-workload model), heldout — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- headline_global_test -->
**Validation-selected linear model per tier (one global model), test — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- headline_global_heldout -->
**Validation-selected linear model per tier (one global model), heldout — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- bycap_KpKp -->
**By capacity: the selected kernel+refault (K∪K+) model (per-workload) — faults / Clock**

| workload | split | 5% | 10% | 20% | Belady 5% | Belady 10% | Belady 20% |
|---|---|---|---|---|---|---|---|

<!-- bycap_F -->
**By capacity: the selected oracle (F) model (per-workload) — faults / Clock**

| workload | split | 5% | 10% | 20% | Belady 5% | Belady 10% | Belady 20% |
|---|---|---|---|---|---|---|---|

<!-- chosen -->
**Models chosen on validation: feature subset (probation, in scans)**

| scope | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel |
|---|---|---|---|---|
| btree | — | — | — | — |
| graph | — | — | — | — |
| kv | — | — | — | — |
| matmul | — | — | — | — |
| sort | — | — | — | — |
| global | — | — | — | — |

<!-- writebacks -->
**Page writes (disk writebacks) relative to Clock, geo-mean over 5/10/20%**

| workload | split | LRU | kernel+refault | oracle | Belady |
|---|---|---|---|---|---|

*Below 1: fewer writes than Clock. Belady minimises faults, not writes.*

<!-- fsubsets_workload_test -->
**All 15 full-stream (F) subsets, linear, per-workload models, test, 10% — faults / Clock**

| features | btree | graph | kv | matmul | sort |
|---|---|---|---|---|---|
| rec | 0.999 | 0.976 | 0.986 | — | 0.954 |
| freq | 0.915 | ≥3.000 | 1.076 | — | 1.204 |
| sd | 0.999 | 0.976 | 0.986 | — | 0.954 |
| wr | 0.854 | ≥2.823 | ≥1.786 | — | 1.245 |
| rec+freq | 0.864 | 0.625 | 0.914 | — | 0.954 |
| rec+sd | 0.999 | 0.976 | 0.987 | — | 0.954 |
| rec+wr | 0.882 | 0.626 | 0.987 | — | 0.954 |
| freq+sd | 0.869 | ≥1.720 | 0.921 | — | 0.954 |
| freq+wr | 0.865 | ≥2.491 | 1.076 | — | 1.211 |
| sd+wr | 0.878 | ≥1.449 | 0.991 | — | 0.954 |
| rec+freq+sd | 0.888 | 0.636 | 0.912 | — | 0.954 |
| rec+freq+wr | 0.833 | 0.628 | 0.914 | — | 0.954 |
| rec+sd+wr | 0.873 | 0.656 | 0.991 | — | 0.954 |
| freq+sd+wr | 0.835 | ≥1.254 | 0.922 | — | 0.954 |
| rec+freq+sd+wr | 0.847 | 0.652 | 0.911 | — | 0.954 |

<!-- fsubsets_workload_heldout -->
**All 15 full-stream (F) subsets, linear, per-workload models, heldout, 10% — faults / Clock**

| features | btree | graph | kv | matmul | sort |
|---|---|---|---|---|---|
| rec | 0.995 | 0.999 | 0.983 | 0.999 | 1.000 |
| freq | 0.857 | 0.724 | 1.012 | 1.564 | 1.288 |
| sd | 0.995 | 0.999 | 0.983 | 0.999 | 1.000 |
| wr | 0.937 | 2.466 | 1.088 | 1.408 | 1.224 |
| rec+freq | 0.863 | 0.528 | 0.907 | 0.999 | 1.000 |
| rec+sd | 0.995 | 0.999 | 0.982 | 0.999 | 1.000 |
| rec+wr | 0.929 | 0.619 | 0.979 | 0.999 | 1.000 |
| freq+sd | 0.864 | 0.503 | 0.913 | 0.999 | 1.000 |
| freq+wr | 0.833 | 1.750 | 1.012 | 1.569 | 1.303 |
| sd+wr | 0.930 | 0.799 | 0.979 | 0.999 | 1.000 |
| rec+freq+sd | 0.865 | 0.519 | 0.906 | 0.999 | 1.000 |
| rec+freq+wr | 0.848 | 0.499 | 0.907 | 0.999 | 1.000 |
| rec+sd+wr | 0.930 | 0.620 | 0.979 | 0.999 | 1.000 |
| freq+sd+wr | 0.849 | 0.479 | 0.913 | 0.999 | 1.000 |
| rec+freq+sd+wr | 0.848 | 0.489 | 0.906 | 0.999 | 1.000 |

<!-- fsubsets_global_test -->
**All 15 full-stream (F) subsets, linear, global models, test, 10% — faults / Clock**

| features | btree | graph | kv | matmul | sort |
|---|---|---|---|---|---|
| rec | 0.999 | 0.976 | 0.986 | — | 0.954 |
| freq | 0.915 | ≥3.000 | 1.076 | — | 1.204 |
| sd | 0.999 | 0.976 | 0.986 | — | 0.954 |
| wr | 0.854 | ≥3.000 | 2.216 | — | 1.245 |
| rec+freq | 0.930 | 0.758 | 0.939 | — | 0.954 |
| rec+sd | 0.999 | 0.976 | 0.986 | — | 0.954 |
| rec+wr | 0.992 | 0.994 | 0.986 | — | 0.954 |
| freq+sd | 0.906 | 0.784 | 0.923 | — | 0.954 |
| freq+wr | 0.887 | ≥3.000 | 1.084 | — | 1.213 |
| sd+wr | 0.989 | 1.449 | 0.986 | — | 0.954 |
| rec+freq+sd | 0.887 | 0.676 | 0.919 | — | 0.954 |
| rec+freq+wr | 0.936 | 0.742 | 0.938 | — | 0.954 |
| rec+sd+wr | 0.987 | 1.010 | 0.987 | — | 0.954 |
| freq+sd+wr | 0.904 | 0.787 | 0.923 | — | 0.954 |
| rec+freq+sd+wr | 0.886 | 0.679 | 0.919 | — | 0.954 |

<!-- fsubsets_global_heldout -->
**All 15 full-stream (F) subsets, linear, global models, heldout, 10% — faults / Clock**

| features | btree | graph | kv | matmul | sort |
|---|---|---|---|---|---|
| rec | 0.995 | 0.999 | 0.983 | 0.999 | 1.000 |
| freq | 0.857 | 0.724 | 1.012 | 1.564 | 1.288 |
| sd | 0.995 | 0.999 | 0.983 | 0.999 | 1.000 |
| wr | 0.937 | ≥3.000 | 1.964 | 1.408 | 1.224 |
| rec+freq | 0.959 | 0.800 | 0.940 | 0.999 | 1.000 |
| rec+sd | 0.995 | 0.999 | 0.983 | 0.999 | 1.000 |
| rec+wr | 0.992 | 1.013 | 0.983 | 0.999 | 1.000 |
| freq+sd | 0.948 | 0.666 | 0.923 | 1.025 | 1.000 |
| freq+wr | 0.842 | 0.745 | 1.012 | 1.563 | 1.298 |
| sd+wr | 0.991 | 1.035 | 0.984 | 0.999 | 1.000 |
| rec+freq+sd | 0.926 | 0.680 | 0.916 | 0.999 | 1.000 |
| rec+freq+wr | 0.962 | 0.787 | 0.939 | 0.999 | 1.000 |
| rec+sd+wr | 0.990 | 1.025 | 0.984 | 0.999 | 1.000 |
| freq+sd+wr | 0.947 | 0.670 | 0.923 | 1.027 | 1.000 |
| rec+freq+sd+wr | 0.925 | 0.683 | 0.916 | 0.999 | 1.000 |

<!-- kksubsets_workload_test -->
**The 255 kernel-observable (K ∪ K+) subsets, per-workload models, test, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.797 | 0.820 | 0.932 | 1.772 | 152/255 | 0 |
| graph | 0.628 | 0.681 | 1.004 | 3.000 | 126/255 | 98 |
| kv | 0.888 | 0.907 | 1.012 | 1.759 | 122/255 | 0 |
| sort | 0.945 | 0.967 | 1.046 | 1.157 | 71/255 | 0 |

<!-- kksubsets_workload_heldout -->
**The 255 kernel-observable (K ∪ K+) subsets, per-workload models, heldout, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.838 | 0.847 | 0.888 | 1.371 | 180/255 | 0 |
| graph | 0.485 | 0.497 | 0.684 | 1.837 | 176/255 | 8 |
| kv | 0.900 | 0.926 | 0.990 | 1.443 | 132/255 | 0 |
| matmul | 0.969 | 0.975 | 1.067 | 1.496 | 94/255 | 0 |
| sort | 0.950 | 0.998 | 1.007 | 1.174 | 28/255 | 0 |

<!-- kksubsets_global_test -->
**The 255 kernel-observable (K ∪ K+) subsets, global models, test, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.800 | 0.826 | 0.932 | 1.735 | 162/255 | 0 |
| graph | 0.620 | 0.729 | 2.883 | 3.000 | 80/255 | 126 |
| kv | 0.885 | 0.936 | 1.078 | 1.721 | 81/255 | 0 |
| sort | 0.940 | 0.948 | 0.965 | 1.032 | 214/255 | 0 |

<!-- kksubsets_global_heldout -->
**The 255 kernel-observable (K ∪ K+) subsets, global models, heldout, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.841 | 0.854 | 0.925 | 1.337 | 179/255 | 0 |
| graph | 0.488 | 0.500 | 1.012 | 3.000 | 125/255 | 30 |
| kv | 0.893 | 0.941 | 1.060 | 1.625 | 80/255 | 0 |
| matmul | 0.971 | 0.974 | 1.001 | 1.336 | 107/255 | 0 |
| sort | 0.944 | 0.947 | 0.978 | 1.145 | 160/255 | 0 |

<!-- marginal -->
**Median change in faults from adding one kernel feature to a subset that lacks it (per-workload models, test; matmul: held-out; over all such subset pairs)**

| feature | btree | graph | kv | matmul | sort |
|---|---|---|---|---|---|
| ref | -0.1% | +0.0% | -0.2% | +0.0% | -0.9% |
| aging | -1.6% | +0.0% | -1.7% | -0.5% | -2.5% |
| sfreq | -8.9% | +2.7% | +3.4% | +2.4% | +6.9% |
| idle | -29.2% | -70.8% | -19.5% | -21.8% | +0.0% |
| age | -1.1% | +0.0% | -2.0% | +0.4% | +1.6% |
| dirty | -2.2% | -3.4% | +0.4% | +0.0% | -0.1% |
| refaults | -5.4% | +0.0% | -2.6% | +0.0% | -5.0% |
| rdist | +0.6% | +0.0% | +1.0% | +0.0% | +0.4% |

<!-- nn_workload_test -->
**Neural and ranking-loss scorers (per-workload models), test, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- nn_workload_heldout -->
**Neural and ranking-loss scorers (per-workload models), heldout, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- nn_global_test -->
**Neural and ranking-loss scorers (global models), test, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- nn_global_heldout -->
**Neural and ranking-loss scorers (global models), heldout, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- protect -->
**Probation ablation (per-workload linear models, validation streams, 10%; matmul: its training streams) — faults / Clock**

| workload | features | 0 | 1 | 2 | 4 |
|---|---|---|---|---|---|

<!-- v1v2 -->
**Effect of the two fixes on the same linear models (per-workload, 10%) — faults / Clock; v1: uniform candidate sampling, no probation; v2: recency-stratified sampling + probation 2**

| workload | split | features | v1 | v2 |
|---|---|---|---|---|
| btree | heldout | F | 0.853 | 0.849 |
| btree | heldout | K | 0.849 | 0.851 |
| btree | heldout | K∪K+ | 0.847 | 0.846 |
| btree | heldout | all | 0.899 | 0.877 |
| graph | val | F | ≥1.258 | 0.707 |
| graph | val | K | ≥1.273 | 0.809 |
| graph | val | K∪K+ | ≥1.334 | 1.383 |
| graph | val | all | ≥1.257 | 0.661 |
| graph | test | F | ≥1.255 | 0.720 |
| graph | test | K | ≥1.268 | 0.806 |
| graph | test | K∪K+ | ≥1.330 | 1.463 |
| graph | test | all | ≥1.254 | 0.669 |
| kv | val | F | 0.964 | 0.960 |
| kv | val | K | 0.986 | 1.003 |
| kv | val | K∪K+ | 0.994 | 0.991 |
| kv | val | all | 1.020 | 1.042 |
| kv | test | F | 0.959 | 0.956 |
| kv | test | K | 0.987 | 1.004 |
| kv | test | K∪K+ | 0.997 | 0.986 |
| kv | test | all | 1.030 | 1.042 |
| matmul | heldout | F | 1.001 | 0.999 |
| matmul | heldout | K | 0.971 | 1.108 |
| matmul | heldout | K∪K+ | 0.927 | 1.108 |
| matmul | heldout | all | 0.891 | 1.010 |
| sort | val | F | 0.960 | 0.960 |
| sort | val | K | 1.055 | 1.055 |
| sort | val | K∪K+ | 1.036 | 1.036 |
| sort | val | all | 0.964 | 0.962 |
| sort | test | F | 0.954 | 0.954 |
| sort | test | K | 1.050 | 1.050 |
| sort | test | K∪K+ | 1.026 | 1.030 |
| sort | test | all | 0.957 | 0.957 |
| sort | heldout | F | 1.000 | 1.000 |
| sort | heldout | K | 1.060 | 1.060 |
| sort | heldout | K∪K+ | 1.022 | 1.027 |
| sort | heldout | all | 1.005 | 1.007 |

<!-- catastrophic -->
**Share of the 300 feature sets that are catastrophic (≥3× Clock), per-workload models, 10%**

| workload | split | v1 | v2 |
|---|---|---|---|
| btree | heldout | 0/300 | 0/300 |
| graph | val | 110/300 | 113/300 |
| graph | test | 110/300 | 113/300 |
| kv | val | 55/300 | 56/300 |
| kv | test | 55/300 | 52/300 |
| matmul | heldout | 76/300 | 0/300 |
| sort | val | 18/300 | 0/300 |
| sort | test | 17/300 | 0/300 |
| sort | heldout | 17/300 | 0/300 |

<!-- quant -->
**Integer-only scoring of the selected linear models (per-workload) — faults / Clock**

| workload | split | tier | float | int, 4-bit | int, 8-bit | int, 12-bit |
|---|---|---|---|---|---|---|

*Features in Q8 fixed point; weights with the standardisation folded in, rounded to b fractional bits.*

<!-- dagger -->
**One DAgger round (per-workload linear models) — faults / Clock, geo-mean 5/10/20%**

| workload | split | tier | trained under LRU | after DAgger |
|---|---|---|---|---|

