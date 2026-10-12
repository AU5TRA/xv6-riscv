<!-- classical_test -->
**Classical policies, test streams — faults / Clock (geo-mean over 5/10/20%)**

| workload | FIFO | Aging | decayed LFU | LRU | exact LFU | old SD | Belady |
|---|---|---|---|---|---|---|---|
| btree | 1.126 | 1.118 | 1.125 | 0.994 | 0.943 | 1.040 | 0.550 |
| graph | 1.418 | 1.286 | 1.399 | 0.990 | ≥3.000 | 1.319 | 0.456 |
| kv | 1.163 | 1.097 | 1.151 | 0.986 | 1.190 | 1.124 | 0.571 |
| lzw | 1.071 | 1.056 | 1.069 | 0.997 | 1.133 | 1.070 | 0.466 |
| sort | 1.030 | 1.011 | 1.011 | 1.012 | ≥2.919 | 1.030 | 0.830 |

*Clock = 1; below 1 is better. ≥: some runs stopped at 3× Clock (lower bound).*

<!-- classical_heldout -->
**Classical policies, heldout streams — faults / Clock (geo-mean over 5/10/20%)**

| workload | FIFO | Aging | decayed LFU | LRU | exact LFU | old SD | Belady |
|---|---|---|---|---|---|---|---|
| btree | 1.066 | 1.060 | 1.066 | 0.997 | 0.871 | 1.049 | 0.615 |
| graph | 1.326 | 1.315 | 1.325 | 0.992 | 1.623 | 1.301 | 0.482 |
| kv | 1.166 | 1.121 | 1.161 | 0.982 | 1.001 | 1.123 | 0.577 |
| lzw | 1.210 | 1.172 | 1.207 | 0.981 | ≥1.543 | 1.207 | 0.409 |
| matmul | 1.077 | 0.931 | 0.931 | 0.879 | ≥3.000 | 1.077 | 0.617 |
| sort | 1.000 | 0.999 | 0.998 | 0.999 | ≥3.000 | 1.000 | 0.896 |

*Clock = 1; below 1 is better. ≥: some runs stopped at 3× Clock (lower bound).*

<!-- headline_workload_test -->
**Validation-selected linear model per tier (per-workload model), test — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|
| btree | 0.994 | 0.862 (+32%) | 0.835 (+38%) | 0.835 (+38%) | 0.847 (+35%) | 0.550 |
| graph | 0.990 | 0.855 (+22%) | 0.872 (+21%) | 0.847 (+26%) | 0.856 (+22%) | 0.456 |
| kv | 0.986 | 0.910 (+21%) | 0.917 (+19%) | 0.904 (+23%) | 0.937 (+15%) | 0.571 |
| lzw | 0.997 | 0.957 (+7%) | 1.000 (+3%) | 0.821 (+32%) | 1.125 (-21%) | 0.466 |
| sort | 1.012 | 1.011 (+12%) | 1.011 (+11%) | 0.983 (+30%) | 0.947 (+30%) | 0.830 |

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- headline_workload_heldout -->
**Validation-selected linear model per tier (per-workload model), heldout — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|
| btree | 0.997 | 0.861 (+38%) | 0.875 (+34%) | 0.875 (+34%) | 0.864 (+37%) | 0.615 |
| graph | 0.992 | 0.786 (+31%) | 0.803 (+29%) | 0.798 (+30%) | 0.767 (+34%) | 0.482 |
| kv | 0.982 | 0.890 (+27%) | 0.916 (+20%) | 0.902 (+24%) | 0.921 (+19%) | 0.577 |
| lzw | 0.981 | 0.943 (+8%) | 1.179 (-31%) | 0.813 (+32%) | 1.435 (-83%) | 0.409 |
| matmul | 0.879 | 0.823 (+26%) | 0.789 (+39%) | 0.671 (+76%) | 0.751 (+44%) | 0.617 |
| sort | 0.999 | 0.999 (+4%) | 0.999 (+4%) | 0.933 (+51%) | 1.001 (+0%) | 0.896 |

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- headline_global_test -->
**Validation-selected linear model per tier (one global model), test — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|
| btree | 0.994 | 0.908 (+21%) | 0.905 (+21%) | 0.840 (+37%) | 0.941 (+14%) | 0.550 |
| graph | 0.990 | 0.878 (+19%) | 0.876 (+21%) | 0.890 (+8%) | 0.970 (+3%) | 0.456 |
| kv | 0.986 | 0.924 (+18%) | 0.933 (+15%) | 0.900 (+24%) | 1.066 (-15%) | 0.571 |
| lzw | 0.997 | 0.988 (+0%) | 0.907 (+15%) | 0.905 (+17%) | 0.897 (+19%) | 0.466 |
| sort | 1.012 | 1.008 (+13%) | 1.019 (+6%) | 0.973 (+15%) | 0.946 (+25%) | 0.830 |

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- headline_global_heldout -->
**Validation-selected linear model per tier (one global model), heldout — faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)**

| workload | LRU | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel | Belady |
|---|---|---|---|---|---|---|
| btree | 0.997 | 0.930 (+19%) | 0.939 (+16%) | 0.876 (+34%) | 0.876 (+34%) | 0.615 |
| graph | 0.992 | 0.867 (+21%) | 0.903 (+14%) | 0.790 (+29%) | 0.822 (+20%) | 0.482 |
| kv | 0.982 | 0.908 (+22%) | 0.930 (+17%) | 0.891 (+27%) | 1.008 (-1%) | 0.577 |
| lzw | 0.981 | 0.949 (+6%) | 0.856 (+22%) | 0.945 (+10%) | 0.963 (+8%) | 0.409 |
| matmul | 0.879 | 0.867 (+19%) | 0.814 (+27%) | 0.911 (-48%) | 0.794 (+35%) | 0.617 |
| sort | 0.999 | 0.998 (+5%) | 0.999 (+4%) | 0.948 (+37%) | 0.939 (+45%) | 0.896 |

*Feature subset and probation chosen on validation only (matmul: its training streams).*

<!-- bycap_KpKp -->
**By capacity: the selected kernel+refault (K∪K+) model (per-workload) — faults / Clock**

| workload | split | 5% | 10% | 20% | Belady 5% | Belady 10% | Belady 20% |
|---|---|---|---|---|---|---|---|
| btree | test | 0.815 | 0.797 | 0.896 | 0.608 | 0.550 | 0.498 |
| btree | heldout | 0.876 | 0.866 | 0.883 | 0.686 | 0.627 | 0.541 |
| graph | test | 0.983 | 0.627 | 0.986 | 0.412 | 0.337 | 0.682 |
| graph | heldout | 0.932 | 0.560 | 0.976 | 0.477 | 0.377 | 0.623 |
| kv | test | 0.866 | 0.890 | 0.959 | 0.629 | 0.573 | 0.516 |
| kv | heldout | 0.839 | 0.904 | 0.969 | 0.617 | 0.588 | 0.530 |
| lzw | test | 0.898 | 0.856 | 0.719 | 0.619 | 0.490 | 0.333 |
| lzw | heldout | 0.872 | 0.830 | 0.744 | 0.561 | 0.425 | 0.288 |
| matmul | heldout | 0.500 | 0.913 | 0.661 | 0.500 | 0.839 | 0.560 |
| sort | test | 1.099 | 0.950 | 0.912 | 0.758 | 0.897 | 0.842 |
| sort | heldout | 0.994 | 0.951 | 0.859 | 0.959 | 0.918 | 0.818 |

<!-- bycap_F -->
**By capacity: the selected oracle (F) model (per-workload) — faults / Clock**

| workload | split | 5% | 10% | 20% | Belady 5% | Belady 10% | Belady 20% |
|---|---|---|---|---|---|---|---|
| btree | test | 0.832 | 0.834 | 0.922 | 0.608 | 0.550 | 0.498 |
| btree | heldout | 0.856 | 0.849 | 0.880 | 0.686 | 0.627 | 0.541 |
| graph | test | 1.007 | 0.623 | 0.998 | 0.412 | 0.337 | 0.682 |
| graph | heldout | 0.938 | 0.528 | 0.981 | 0.477 | 0.377 | 0.623 |
| kv | test | 0.871 | 0.910 | 0.952 | 0.629 | 0.573 | 0.516 |
| kv | heldout | 0.835 | 0.906 | 0.933 | 0.617 | 0.588 | 0.530 |
| lzw | test | 0.985 | 0.983 | 0.905 | 0.619 | 0.490 | 0.333 |
| lzw | heldout | 0.989 | 0.985 | 0.862 | 0.561 | 0.425 | 0.288 |
| matmul | heldout | 0.516 | 1.001 | 1.078 | 0.500 | 0.839 | 0.560 |
| sort | test | 1.085 | 0.954 | 1.000 | 0.758 | 0.897 | 0.842 |
| sort | heldout | 0.994 | 1.000 | 1.001 | 0.959 | 0.918 | 0.818 |

<!-- chosen -->
**Models chosen on validation: feature subset (probation, in scans)**

| scope | oracle (F) | kernel (K) | kernel+refault (K∪K+) | oracle+kernel |
|---|---|---|---|---|
| bloom | — | — | — | — |
| btree | rec + freq + wr (0) | idle + age + dirty (0) | idle + age + dirty (0) | rec + ref + aging + sfreq + idle + age + dirty (1) |
| chase | — | — | — | — |
| graph | rec + freq (4) | sfreq + idle + dirty (4) | sfreq + idle + dirty + rdist (4) | rec + ref + aging + sfreq + idle + age + dirty (4) |
| heap | — | — | — | — |
| join | — | — | — | — |
| kv | rec + freq + sd + wr (2) | ref + aging + idle + age (4) | ref + aging + idle + dirty + refaults + rdist (1) | freq + wr + ref + aging + sfreq + idle + age + dirty (2) |
| lzw | rec + wr (4) | ref + idle + age (4) | ref + aging + idle + dirty + rdist (1) | wr + ref + aging + sfreq + idle + age + dirty (4) |
| matmul | rec + wr (0) | ref + aging + idle + dirty (0) | aging + idle + dirty + refaults + rdist (0) | sd + ref + aging + sfreq + idle + age + dirty (0) |
| pat | — | — | — | — |
| sort | rec + freq + sd (2) | aging (0) | ref + dirty + refaults + rdist (4) | rec + sd + ref + aging + sfreq + idle + age + dirty + refaults + rdist (2) |
| spmv | — | — | — | — |
| global | rec + freq + sd (0) | ref + aging + sfreq + idle (0) | idle + age + dirty + refaults + rdist (4) | freq + ref + aging + sfreq + idle + age + dirty (0) |

<!-- writebacks -->
**Page writes (disk writebacks) relative to Clock, geo-mean over 5/10/20%**

| workload | split | LRU | kernel+refault | oracle | Belady |
|---|---|---|---|---|---|
| btree | test | 0.997 | 0.981 | 0.932 | 0.707 |
| btree | heldout | 0.997 | 0.965 | 0.962 | 0.646 |
| graph | test | 0.938 | 0.418 | 0.578 | 0.257 |
| graph | heldout | 0.727 | 0.334 | 0.616 | 0.297 |
| kv | test | 0.975 | 0.821 | 0.856 | 0.690 |
| kv | heldout | 0.982 | 0.902 | 0.890 | 0.574 |
| lzw | test | 0.989 | 0.742 | 1.478 | 0.617 |
| lzw | heldout | 0.983 | 0.738 | 1.440 | 0.543 |
| matmul | heldout | 1.008 | 0.659 | 1.008 | 0.863 |
| sort | test | 1.016 | 0.987 | 1.015 | 0.868 |
| sort | heldout | 1.000 | 0.935 | 1.000 | 0.932 |

*Below 1: fewer writes than Clock. Belady minimises faults, not writes.*

<!-- fsubsets_workload_test -->
**All 15 full-stream (F) subsets, linear, per-workload models, test, 10% — faults / Clock**

| features | bloom | btree | chase | graph | heap | join | kv | lzw | matmul | pat | sort | spmv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rec | — | 0.999 | — | 0.976 | — | — | 0.986 | 1.007 | — | — | 0.954 | — |
| freq | — | 0.915 | — | ≥3.000 | — | — | 1.076 | 0.991 | — | — | 1.204 | — |
| sd | — | 0.999 | — | 0.976 | — | — | 0.986 | 1.007 | — | — | 0.954 | — |
| wr | — | 0.854 | — | ≥2.823 | — | — | ≥1.786 | 1.520 | — | — | 1.245 | — |
| rec+freq | — | 0.864 | — | 0.625 | — | — | 0.913 | 0.990 | — | — | 0.954 | — |
| rec+sd | — | 0.999 | — | 0.976 | — | — | 0.987 | 1.007 | — | — | 0.954 | — |
| rec+wr | — | 0.882 | — | 0.626 | — | — | 0.987 | 0.985 | — | — | 0.954 | — |
| freq+sd | — | 0.869 | — | ≥1.719 | — | — | 0.921 | 0.984 | — | — | 0.954 | — |
| freq+wr | — | 0.866 | — | ≥2.490 | — | — | 1.076 | 1.540 | — | — | 1.211 | — |
| sd+wr | — | 0.878 | — | ≥1.449 | — | — | 0.991 | 0.979 | — | — | 0.954 | — |
| rec+freq+sd | — | 0.888 | — | 0.636 | — | — | 0.912 | 0.991 | — | — | 0.954 | — |
| rec+freq+wr | — | 0.834 | — | 0.629 | — | — | 0.914 | 0.993 | — | — | 0.954 | — |
| rec+sd+wr | — | 0.873 | — | 0.656 | — | — | 0.991 | 0.986 | — | — | 0.954 | — |
| freq+sd+wr | — | 0.837 | — | ≥1.254 | — | — | 0.921 | 0.985 | — | — | 0.954 | — |
| rec+freq+sd+wr | — | 0.848 | — | 0.651 | — | — | 0.910 | 0.995 | — | — | 0.954 | — |

<!-- fsubsets_workload_heldout -->
**All 15 full-stream (F) subsets, linear, per-workload models, heldout, 10% — faults / Clock**

| features | bloom | btree | chase | graph | heap | join | kv | lzw | matmul | pat | sort | spmv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rec | — | 0.995 | — | 0.999 | — | — | 0.983 | 1.003 | 0.999 | — | 1.000 | — |
| freq | — | 0.857 | — | 0.724 | — | — | 1.012 | 1.026 | 1.564 | — | 1.288 | — |
| sd | — | 0.995 | — | 0.999 | — | — | 0.983 | 1.003 | 0.999 | — | 1.000 | — |
| wr | — | 0.937 | — | 2.466 | — | — | 1.088 | 2.016 | 1.408 | — | 1.224 | — |
| rec+freq | — | 0.863 | — | 0.528 | — | — | 0.907 | 0.983 | 0.999 | — | 1.000 | — |
| rec+sd | — | 0.995 | — | 0.999 | — | — | 0.982 | 1.002 | 0.999 | — | 1.000 | — |
| rec+wr | — | 0.930 | — | 0.618 | — | — | 0.979 | 0.990 | 0.999 | — | 1.000 | — |
| freq+sd | — | 0.864 | — | 0.503 | — | — | 0.912 | 0.978 | 0.999 | — | 1.000 | — |
| freq+wr | — | 0.833 | — | 1.752 | — | — | 1.012 | 2.035 | 1.569 | — | 1.303 | — |
| sd+wr | — | 0.930 | — | 0.796 | — | — | 0.979 | 0.988 | 0.999 | — | 1.000 | — |
| rec+freq+sd | — | 0.865 | — | 0.521 | — | — | 0.906 | 0.983 | 0.999 | — | 1.000 | — |
| rec+freq+wr | — | 0.849 | — | 0.499 | — | — | 0.907 | 1.000 | 0.999 | — | 1.000 | — |
| rec+sd+wr | — | 0.930 | — | 0.621 | — | — | 0.979 | 0.991 | 0.999 | — | 1.000 | — |
| freq+sd+wr | — | 0.849 | — | 0.479 | — | — | 0.913 | 1.001 | 0.999 | — | 1.000 | — |
| rec+freq+sd+wr | — | 0.848 | — | 0.490 | — | — | 0.906 | 1.003 | 0.999 | — | 1.000 | — |

<!-- fsubsets_global_test -->
**All 15 full-stream (F) subsets, linear, global models, test, 10% — faults / Clock**

| features | bloom | btree | chase | graph | heap | join | kv | lzw | matmul | pat | sort | spmv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rec | — | 0.999 | — | 0.976 | — | — | 0.986 | 1.007 | — | — | 0.954 | — |
| freq | — | 0.915 | — | ≥3.000 | — | — | 1.076 | 0.991 | — | — | 1.204 | — |
| sd | — | 0.999 | — | 0.976 | — | — | 0.986 | 1.007 | — | — | 0.954 | — |
| wr | — | 0.854 | — | ≥3.000 | — | — | 2.216 | 1.520 | — | — | 1.245 | — |
| rec+freq | — | 0.928 | — | 0.750 | — | — | 0.937 | 0.992 | — | — | 0.954 | — |
| rec+sd | — | 0.999 | — | 0.977 | — | — | 0.986 | 1.007 | — | — | 0.954 | — |
| rec+wr | — | 0.983 | — | 1.030 | — | — | 0.988 | 1.008 | — | — | 0.954 | — |
| freq+sd | — | 0.885 | — | 0.919 | — | — | 0.916 | 0.982 | — | — | 0.954 | — |
| freq+wr | — | 0.891 | — | ≥3.000 | — | — | 1.083 | 0.994 | — | — | 1.213 | — |
| sd+wr | — | 0.948 | — | ≥2.808 | — | — | 0.999 | 1.009 | — | — | 0.954 | — |
| rec+freq+sd | — | 0.896 | — | 0.696 | — | — | 0.922 | 0.991 | — | — | 0.954 | — |
| rec+freq+wr | — | 0.935 | — | 0.733 | — | — | 0.937 | 0.993 | — | — | 0.954 | — |
| rec+sd+wr | — | 0.979 | — | 1.036 | — | — | 0.989 | 1.008 | — | — | 0.954 | — |
| freq+sd+wr | — | 0.874 | — | 0.994 | — | — | 0.918 | 0.981 | — | — | 0.954 | — |
| rec+freq+sd+wr | — | 0.905 | — | 0.678 | — | — | 0.922 | 0.992 | — | — | 0.954 | — |

<!-- fsubsets_global_heldout -->
**All 15 full-stream (F) subsets, linear, global models, heldout, 10% — faults / Clock**

| features | bloom | btree | chase | graph | heap | join | kv | lzw | matmul | pat | sort | spmv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rec | — | 0.995 | — | 0.999 | — | — | 0.983 | 1.003 | 0.999 | — | 1.000 | — |
| freq | — | 0.857 | — | 0.724 | — | — | 1.012 | 1.026 | 1.564 | — | 1.288 | — |
| sd | — | 0.995 | — | 0.999 | — | — | 0.983 | 1.003 | 0.999 | — | 1.000 | — |
| wr | — | 0.937 | — | ≥3.000 | — | — | 1.964 | 2.016 | 1.408 | — | 1.224 | — |
| rec+freq | — | 0.958 | — | 0.793 | — | — | 0.938 | 0.984 | 0.999 | — | 1.000 | — |
| rec+sd | — | 0.995 | — | 0.999 | — | — | 0.982 | 1.003 | 0.999 | — | 1.000 | — |
| rec+wr | — | 0.988 | — | 1.038 | — | — | 0.985 | 1.002 | 0.999 | — | 1.000 | — |
| freq+sd | — | 0.933 | — | 0.599 | — | — | 0.913 | 0.979 | 1.069 | — | 1.000 | — |
| freq+wr | — | 0.844 | — | 0.742 | — | — | 1.012 | 1.030 | 1.563 | — | 1.294 | — |
| sd+wr | — | 0.974 | — | 1.233 | — | — | 0.993 | 1.001 | 0.999 | — | 1.000 | — |
| rec+freq+sd | — | 0.934 | — | 0.710 | — | — | 0.921 | 0.987 | 0.999 | — | 1.000 | — |
| rec+freq+wr | — | 0.960 | — | 0.777 | — | — | 0.938 | 0.983 | 0.999 | — | 1.000 | — |
| rec+sd+wr | — | 0.986 | — | 1.045 | — | — | 0.985 | 1.001 | 0.999 | — | 1.000 | — |
| freq+sd+wr | — | 0.927 | — | 0.626 | — | — | 0.913 | 0.978 | 1.087 | — | 1.000 | — |
| rec+freq+sd+wr | — | 0.939 | — | 0.689 | — | — | 0.921 | 0.987 | 0.999 | — | 1.000 | — |

<!-- kksubsets_workload_test -->
**The 255 kernel-observable (K ∪ K+) subsets, per-workload models, test, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.797 | 0.820 | 0.938 | 1.780 | 148/255 | 0 |
| graph | 0.631 | 0.690 | 0.988 | 3.000 | 129/255 | 98 |
| kv | 0.889 | 0.908 | 1.011 | 1.776 | 123/255 | 0 |
| lzw | 0.857 | 1.009 | 1.102 | 1.349 | 24/255 | 0 |
| sort | 0.945 | 0.967 | 1.045 | 1.157 | 72/255 | 0 |

<!-- kksubsets_workload_heldout -->
**The 255 kernel-observable (K ∪ K+) subsets, per-workload models, heldout, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.838 | 0.847 | 0.891 | 1.376 | 180/255 | 0 |
| graph | 0.486 | 0.495 | 0.690 | 1.823 | 176/255 | 8 |
| kv | 0.900 | 0.926 | 0.991 | 1.439 | 132/255 | 0 |
| lzw | 0.835 | 1.036 | 1.217 | 1.598 | 8/255 | 0 |
| matmul | 0.969 | 0.974 | 1.067 | 1.496 | 97/255 | 0 |
| sort | 0.950 | 0.997 | 1.007 | 1.176 | 30/255 | 0 |

<!-- kksubsets_global_test -->
**The 255 kernel-observable (K ∪ K+) subsets, global models, test, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.799 | 0.818 | 0.911 | 1.326 | 185/255 | 0 |
| graph | 0.629 | 0.721 | 2.256 | 3.000 | 77/255 | 119 |
| kv | 0.880 | 0.936 | 1.065 | 1.574 | 81/255 | 0 |
| lzw | 0.862 | 0.902 | 1.024 | 1.412 | 90/255 | 0 |
| sort | 0.942 | 0.948 | 0.965 | 1.068 | 208/255 | 0 |

<!-- kksubsets_global_heldout -->
**The 255 kernel-observable (K ∪ K+) subsets, global models, heldout, 10% — distribution of faults / Clock**

| workload | best | 10th pct | median | 90th pct | beat Clock | ≥3× Clock |
|---|---|---|---|---|---|---|
| btree | 0.839 | 0.852 | 0.911 | 1.068 | 199/255 | 0 |
| graph | 0.485 | 0.498 | 1.055 | 3.000 | 120/255 | 34 |
| kv | 0.893 | 0.947 | 1.047 | 1.394 | 89/255 | 0 |
| lzw | 0.843 | 0.913 | 1.071 | 1.589 | 81/255 | 0 |
| matmul | 0.971 | 0.971 | 1.001 | 1.332 | 112/255 | 0 |
| sort | 0.944 | 0.947 | 0.981 | 1.142 | 151/255 | 0 |

<!-- marginal -->
**Median change in faults from adding one kernel feature to a subset that lacks it (per-workload models, test; matmul: held-out; over all such subset pairs)**

| feature | bloom | btree | chase | graph | heap | join | kv | lzw | matmul | pat | sort | spmv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ref | — | -0.2% | — | +0.0% | — | — | -0.2% | +0.0% | +0.0% | — | -0.9% | — |
| aging | — | -1.6% | — | +0.0% | — | — | -1.7% | +0.0% | -0.4% | — | -2.8% | — |
| sfreq | — | -9.4% | — | +2.8% | — | — | +2.7% | +0.9% | +2.4% | — | +6.7% | — |
| idle | — | -29.8% | — | -70.8% | — | — | -19.3% | -0.9% | -20.9% | — | +0.1% | — |
| age | — | -1.0% | — | +0.0% | — | — | -1.9% | +0.8% | +0.2% | — | +1.6% | — |
| dirty | — | -2.0% | — | -3.0% | — | — | +0.3% | +1.7% | +0.0% | — | -0.1% | — |
| refaults | — | -5.5% | — | +0.0% | — | — | -2.6% | +0.4% | +0.0% | — | -5.0% | — |
| rdist | — | +0.7% | — | +0.0% | — | — | +1.0% | +0.8% | +0.0% | — | +0.4% | — |

<!-- nn_workload_test -->
**Neural and ranking-loss scorers (per-workload models), test, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|
| btree | 0.797 | 0.798 | 0.800 | 0.786 | 1.014 | 1.006 | 0.792 | 0.784 | ≥2.456 |
| graph | 0.627 | 0.627 | 0.643 | 0.622 | ≥1.699 | 0.669 | 0.641 | 0.632 | ≥3.000 |
| kv | 0.890 | 0.899 | 0.976 | 0.852 | 0.887 | 0.943 | 0.835 | 0.854 | 0.847 |
| lzw | 0.856 | 1.385 | 0.939 | 0.882 | 0.903 | 1.097 | 0.878 | 0.870 | 1.672 |
| sort | 0.950 | 0.955 | 1.016 | 0.965 | 1.192 | 1.234 | 0.939 | 0.957 | 1.103 |

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- nn_workload_heldout -->
**Neural and ranking-loss scorers (per-workload models), heldout, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|
| btree | 0.866 | 0.864 | 0.833 | 0.884 | 0.932 | 0.928 | 0.832 | 0.831 | 1.483 |
| graph | 0.560 | 0.473 | 0.625 | 0.495 | 1.109 | 0.491 | 0.480 | 0.484 | ≥3.000 |
| kv | 0.904 | 0.906 | 0.960 | 0.850 | 0.858 | 0.934 | 0.868 | 0.982 | 0.817 |
| lzw | 0.830 | 1.665 | 1.009 | 0.871 | 0.941 | 1.212 | 0.883 | 0.864 | 2.264 |
| matmul | 0.913 | 0.999 | ≥1.680 | 0.966 | 0.923 | 1.496 | 0.964 | 0.969 | ≥1.792 |
| sort | 0.951 | 1.001 | 1.044 | 0.998 | 1.244 | 1.268 | 0.977 | 1.000 | 1.171 |

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- nn_global_test -->
**Neural and ranking-loss scorers (global models), test, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|
| btree | 0.809 | 0.829 | 0.804 | 0.798 | 0.889 | 0.801 | 0.800 | 0.796 | 2.223 |
| graph | 0.676 | 0.615 | 0.777 | 0.635 | 0.896 | 1.049 | 0.786 | 0.596 | ≥3.000 |
| kv | 0.885 | 0.938 | 1.028 | 0.950 | 1.009 | 1.175 | 0.899 | 0.895 | 1.011 |
| lzw | 0.929 | 0.962 | 0.927 | 0.921 | 0.911 | 0.888 | 0.897 | 0.864 | 1.385 |
| sort | 0.983 | 0.945 | 0.999 | 1.048 | 1.127 | 1.221 | 0.919 | 0.956 | 0.973 |

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- nn_global_heldout -->
**Neural and ranking-loss scorers (global models), heldout, 10% — faults / Clock**

| workload | linear K∪K+ (sel.) | MLP F | rank-MLP F | MLP K∪K+ | rank-MLP K∪K+ | rank-linear K∪K+ | MLP all | GRU (F) | embedding (F) |
|---|---|---|---|---|---|---|---|---|---|
| btree | 0.868 | 0.867 | 0.866 | 0.867 | 0.885 | 0.856 | 0.830 | 0.846 | 1.218 |
| graph | 0.506 | 0.467 | 0.564 | 0.659 | 0.574 | 0.914 | 0.461 | 0.449 | 2.927 |
| kv | 0.897 | 1.046 | 1.157 | 0.992 | 1.004 | 0.994 | 0.907 | 1.133 | 0.955 |
| lzw | 0.942 | 0.977 | 1.010 | 0.931 | 0.965 | 0.949 | 0.896 | 0.832 | 1.884 |
| matmul | 1.338 | 0.999 | 1.355 | 0.906 | 1.201 | 1.430 | 0.936 | 0.969 | 1.628 |
| sort | 0.971 | 0.985 | 1.064 | 1.371 | 1.142 | 1.345 | 0.956 | 1.005 | ≥3.000 |

*Probation (0 or 2 scans) chosen per model on validation.*

<!-- protect -->
**Probation ablation (per-workload linear models, validation streams, 10%; matmul: its training streams) — faults / Clock**

| workload | features | 0 | 1 | 2 | 4 |
|---|---|---|---|---|---|
| btree | F | 0.854 | 0.854 | 0.853 | 0.853 |
| btree | K | 0.822 | 0.821 | 0.821 | 0.822 |
| btree | K∪K+ | 0.838 | 0.839 | 0.839 | 0.840 |
| btree | all | 1.011 | 1.014 | 1.008 | 1.012 |
| graph | F | 0.806 | 0.669 | 0.643 | 0.625 |
| graph | K | 0.797 | 0.733 | 0.706 | 0.672 |
| graph | K∪K+ | ≥1.094 | ≥1.091 | 1.030 | 0.993 |
| graph | all | 0.817 | 0.626 | 0.617 | 0.612 |
| kv | F | 0.913 | 0.913 | 0.912 | 0.912 |
| kv | K | 0.956 | 0.955 | 0.955 | 0.955 |
| kv | K∪K+ | 0.975 | 0.958 | 0.959 | 0.959 |
| kv | all | 0.991 | 0.979 | 0.978 | 0.979 |
| lzw | F | 0.992 | 0.993 | 0.992 | 0.990 |
| lzw | K | 1.191 | 1.138 | 1.103 | 1.058 |
| lzw | K∪K+ | 1.194 | 1.151 | 1.108 | 1.058 |
| lzw | all | 1.244 | 1.227 | 1.187 | 1.139 |
| matmul | F | 0.739 | 0.861 | 0.939 | 0.845 |
| matmul | K | 0.639 | 0.835 | 0.975 | 0.704 |
| matmul | K∪K+ | 0.626 | 0.829 | 0.973 | 0.840 |
| matmul | all | ≥0.905 | 0.927 | 0.879 | 0.774 |
| sort | F | 0.960 | 0.960 | 0.960 | 0.965 |
| sort | K | 1.055 | 1.055 | 1.055 | 1.014 |
| sort | K∪K+ | 1.040 | 1.040 | 1.040 | 1.008 |
| sort | all | 0.964 | 0.964 | 0.962 | 0.969 |

<!-- v1v2 -->
**Effect of the two fixes on the same linear models (per-workload, 10%) — faults / Clock; v1: uniform candidate sampling, no probation; v2: recency-stratified sampling + probation 2**

| workload | split | features | v1 | v2 |
|---|---|---|---|---|
| btree | heldout | F | 0.853 | 0.849 |
| btree | heldout | K | 0.849 | 0.850 |
| btree | heldout | K∪K+ | 0.847 | 0.846 |
| btree | heldout | all | 0.899 | 0.876 |
| graph | val | F | ≥1.258 | 0.705 |
| graph | val | K | ≥1.273 | 0.811 |
| graph | val | K∪K+ | ≥1.334 | 1.390 |
| graph | val | all | ≥1.257 | 0.656 |
| graph | test | F | ≥1.255 | 0.718 |
| graph | test | K | ≥1.268 | 0.809 |
| graph | test | K∪K+ | ≥1.330 | 1.422 |
| graph | test | all | ≥1.254 | 0.665 |
| kv | val | F | 0.964 | 0.960 |
| kv | val | K | 0.986 | 1.001 |
| kv | val | K∪K+ | 0.994 | 0.994 |
| kv | val | all | 1.020 | 1.040 |
| kv | test | F | 0.959 | 0.956 |
| kv | test | K | 0.987 | 1.003 |
| kv | test | K∪K+ | 0.997 | 0.987 |
| kv | test | all | 1.030 | 1.040 |
| matmul | heldout | F | 1.001 | 0.999 |
| matmul | heldout | K | 0.971 | 1.108 |
| matmul | heldout | K∪K+ | 0.927 | 1.108 |
| matmul | heldout | all | 0.891 | 1.010 |
| sort | val | F | 0.960 | 0.960 |
| sort | val | K | 1.055 | 1.055 |
| sort | val | K∪K+ | 1.036 | 1.043 |
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
| graph | val | 110/300 | 114/300 |
| graph | test | 110/300 | 113/300 |
| kv | val | 55/300 | 55/300 |
| kv | test | 55/300 | 52/300 |
| matmul | heldout | 76/300 | 0/300 |
| sort | val | 18/300 | 0/300 |
| sort | test | 17/300 | 0/300 |
| sort | heldout | 17/300 | 0/300 |

<!-- quant -->
**Integer-only scoring of the selected linear models (per-workload) — faults / Clock**

| workload | split | tier | float | int, 4-bit | int, 8-bit | int, 12-bit |
|---|---|---|---|---|---|---|
| btree | test | oracle (F) | 0.862 | 0.862 | 0.861 | 0.861 |
| btree | test | kernel (K) | 0.835 | 0.834 | 0.835 | 0.835 |
| btree | test | kernel+refault (K∪K+) | 0.835 | 0.834 | 0.835 | 0.835 |
| btree | test | oracle+kernel | 0.847 | 0.854 | 0.846 | 0.846 |
| btree | heldout | oracle (F) | 0.861 | 0.861 | 0.861 | 0.861 |
| btree | heldout | kernel (K) | 0.875 | 0.873 | 0.875 | 0.875 |
| btree | heldout | kernel+refault (K∪K+) | 0.875 | 0.873 | 0.875 | 0.875 |
| btree | heldout | oracle+kernel | 0.864 | 0.866 | 0.864 | 0.864 |
| graph | test | oracle (F) | 0.855 | 0.856 | 0.855 | 0.855 |
| graph | test | kernel (K) | 0.872 | 0.867 | 0.872 | 0.872 |
| graph | test | kernel+refault (K∪K+) | 0.847 | 0.848 | 0.846 | 0.846 |
| graph | test | oracle+kernel | 0.856 | 0.856 | 0.856 | 0.856 |
| graph | heldout | oracle (F) | 0.786 | 0.786 | 0.786 | 0.786 |
| graph | heldout | kernel (K) | 0.803 | 0.800 | 0.804 | 0.804 |
| graph | heldout | kernel+refault (K∪K+) | 0.798 | 0.812 | 0.799 | 0.799 |
| graph | heldout | oracle+kernel | 0.767 | 0.766 | 0.767 | 0.767 |
| kv | test | oracle (F) | 0.910 | 0.911 | 0.910 | 0.910 |
| kv | test | kernel (K) | 0.917 | 0.917 | 0.917 | 0.917 |
| kv | test | kernel+refault (K∪K+) | 0.904 | 0.904 | 0.904 | 0.904 |
| kv | test | oracle+kernel | 0.937 | 0.930 | 0.937 | 0.937 |
| kv | heldout | oracle (F) | 0.890 | 0.890 | 0.890 | 0.890 |
| kv | heldout | kernel (K) | 0.916 | 0.916 | 0.916 | 0.916 |
| kv | heldout | kernel+refault (K∪K+) | 0.902 | 0.903 | 0.901 | 0.902 |
| kv | heldout | oracle+kernel | 0.921 | 0.915 | 0.921 | 0.922 |
| lzw | test | oracle (F) | 0.957 | 0.950 | 0.957 | 0.957 |
| lzw | test | kernel (K) | 1.000 | 1.002 | 1.005 | 1.000 |
| lzw | test | kernel+refault (K∪K+) | 0.821 | 0.823 | 0.821 | 0.820 |
| lzw | test | oracle+kernel | 1.125 | 1.112 | 1.112 | 1.125 |
| lzw | heldout | oracle (F) | 0.943 | 0.937 | 0.943 | 0.943 |
| lzw | heldout | kernel (K) | 1.179 | 1.200 | 1.186 | 1.174 |
| lzw | heldout | kernel+refault (K∪K+) | 0.813 | 0.810 | 0.813 | 0.813 |
| lzw | heldout | oracle+kernel | 1.435 | 1.436 | 1.439 | 1.436 |
| matmul | heldout | oracle (F) | 0.823 | 0.823 | 0.823 | 0.823 |
| matmul | heldout | kernel (K) | 0.789 | 0.789 | 0.789 | 0.789 |
| matmul | heldout | kernel+refault (K∪K+) | 0.671 | 0.681 | 0.676 | 0.676 |
| matmul | heldout | oracle+kernel | 0.751 | 0.751 | 0.751 | 0.751 |
| sort | test | oracle (F) | 1.011 | 1.011 | 1.011 | 1.011 |
| sort | test | kernel (K) | 1.011 | 1.011 | 1.011 | 1.011 |
| sort | test | kernel+refault (K∪K+) | 0.983 | 0.983 | 0.983 | 0.983 |
| sort | test | oracle+kernel | 0.947 | 0.947 | 0.947 | 0.947 |
| sort | heldout | oracle (F) | 0.999 | 0.999 | 0.999 | 0.999 |
| sort | heldout | kernel (K) | 0.999 | 0.999 | 0.999 | 0.999 |
| sort | heldout | kernel+refault (K∪K+) | 0.933 | 0.932 | 0.933 | 0.933 |
| sort | heldout | oracle+kernel | 1.001 | 1.001 | 1.001 | 1.001 |

*Features in Q8 fixed point; weights with the standardisation folded in, rounded to b fractional bits.*

<!-- dagger -->
**One DAgger round (per-workload linear models) — faults / Clock, geo-mean 5/10/20%**

| workload | split | tier | trained under LRU | after DAgger |
|---|---|---|---|---|
| btree | test | oracle (F) | 0.862 | 0.858 |
| btree | test | kernel (K) | 0.835 | 0.848 |
| btree | test | kernel+refault (K∪K+) | 0.835 | 0.848 |
| btree | test | oracle+kernel | 0.847 | 0.847 |
| btree | heldout | oracle (F) | 0.861 | 0.862 |
| btree | heldout | kernel (K) | 0.875 | 0.904 |
| btree | heldout | kernel+refault (K∪K+) | 0.875 | 0.904 |
| btree | heldout | oracle+kernel | 0.864 | 0.879 |
| graph | test | oracle (F) | 0.855 | 0.854 |
| graph | test | kernel (K) | 0.872 | 0.898 |
| graph | test | kernel+refault (K∪K+) | 0.847 | 0.891 |
| graph | test | oracle+kernel | 0.856 | 0.858 |
| graph | heldout | oracle (F) | 0.786 | 0.790 |
| graph | heldout | kernel (K) | 0.803 | 0.793 |
| graph | heldout | kernel+refault (K∪K+) | 0.798 | 0.803 |
| graph | heldout | oracle+kernel | 0.767 | 0.770 |
| kv | test | oracle (F) | 0.910 | 0.909 |
| kv | test | kernel (K) | 0.917 | 0.919 |
| kv | test | kernel+refault (K∪K+) | 0.904 | 0.904 |
| kv | test | oracle+kernel | 0.937 | 0.915 |
| kv | heldout | oracle (F) | 0.890 | 0.891 |
| kv | heldout | kernel (K) | 0.916 | 0.918 |
| kv | heldout | kernel+refault (K∪K+) | 0.902 | 0.903 |
| kv | heldout | oracle+kernel | 0.921 | 0.896 |
| lzw | test | oracle (F) | 0.957 | 0.930 |
| lzw | test | kernel (K) | 1.000 | 0.982 |
| lzw | test | kernel+refault (K∪K+) | 0.821 | 0.872 |
| lzw | test | oracle+kernel | 1.125 | 0.965 |
| lzw | heldout | oracle (F) | 0.943 | 0.927 |
| lzw | heldout | kernel (K) | 1.179 | 0.927 |
| lzw | heldout | kernel+refault (K∪K+) | 0.813 | 0.852 |
| lzw | heldout | oracle+kernel | 1.435 | 0.941 |
| matmul | heldout | oracle (F) | 0.823 | 0.823 |
| matmul | heldout | kernel (K) | 0.789 | 0.928 |
| matmul | heldout | kernel+refault (K∪K+) | 0.671 | 0.699 |
| matmul | heldout | oracle+kernel | 0.751 | 0.822 |
| sort | test | oracle (F) | 1.011 | 1.011 |
| sort | test | kernel (K) | 1.011 | 1.011 |
| sort | test | kernel+refault (K∪K+) | 0.983 | 0.998 |
| sort | test | oracle+kernel | 0.947 | 1.012 |
| sort | heldout | oracle (F) | 0.999 | 0.999 |
| sort | heldout | kernel (K) | 0.999 | 0.999 |
| sort | heldout | kernel+refault (K∪K+) | 0.933 | 0.951 |
| sort | heldout | oracle+kernel | 1.001 | 1.001 |

<!-- kernel_test -->
**In xv6 itself: faults relative to Clock, test streams, 10% (kernel counters; geo-mean over streams)**

| workload | FIFO | Aging | LFU (decayed) | ML global | ML per-workload | ML per-workload, K only |
|---|---|---|---|---|---|---|
| btree | 1.143 | 1.116 | 1.127 | 0.843 | 0.823 | 0.824 |
| graph | 2.096 | 1.585 | 2.027 | 0.989 | 0.614 | 0.630 |
| kv | 1.284 | 1.107 | 1.175 | 0.875 | 0.871 | 0.908 |
| sort | 1.331 | 0.988 | 0.991 | 0.980 | 0.960 | 0.988 |

*Every policy runs the same workload command with the same resident limit; faults = zero-fill + swap faults.*

<!-- kernel_writes_test -->
**In xv6 itself: page writes relative to Clock, test streams, 10%**

| workload | FIFO | Aging | LFU (decayed) | ML global | ML per-workload | ML per-workload, K only |
|---|---|---|---|---|---|---|
| btree | 1.058 | 1.026 | 1.028 | 0.952 | 1.022 | 1.043 |
| graph | 2.533 | 1.750 | 2.301 | 0.515 | 0.045 | 0.045 |
| kv | 1.992 | 1.462 | 1.645 | 0.737 | 0.682 | 0.715 |
| sort | 1.148 | 0.982 | 0.987 | 0.965 | 0.944 | 0.982 |

<!-- kernel_heldout -->
**In xv6 itself: faults relative to Clock, heldout streams, 10% (kernel counters; geo-mean over streams)**

| workload | FIFO | Aging | LFU (decayed) | ML global | ML per-workload | ML per-workload, K only |
|---|---|---|---|---|---|---|
| btree | 1.087 | 1.063 | 1.073 | 0.893 | 0.854 | 0.893 |
| graph | 1.289 | 1.264 | 1.274 | 0.535 | 0.541 | 0.550 |
| kv | 1.312 | 1.133 | 1.187 | 0.878 | 0.875 | 0.924 |
| matmul | 1.820 | 0.999 | 0.999 | 1.115 | 0.973 | 0.999 |
| sort | 1.190 | 0.998 | 1.006 | 0.977 | 0.933 | 0.998 |

*Every policy runs the same workload command with the same resident limit; faults = zero-fill + swap faults.*

<!-- kernel_writes_heldout -->
**In xv6 itself: page writes relative to Clock, heldout streams, 10%**

| workload | FIFO | Aging | LFU (decayed) | ML global | ML per-workload | ML per-workload, K only |
|---|---|---|---|---|---|---|
| btree | 1.069 | 1.018 | 1.019 | 0.984 | 0.966 | 0.981 |
| graph | 1.375 | 1.323 | 1.332 | 0.395 | 0.138 | 0.130 |
| kv | 1.221 | 1.133 | 1.171 | 0.878 | 0.875 | 0.924 |
| matmul | 13.002 | 0.987 | 0.987 | 3.889 | 0.035 | 0.987 |
| sort | 1.097 | 0.995 | 1.010 | 0.971 | 0.925 | 0.995 |

<!-- kernel_cost -->
**Victim-selection cost in xv6: timer ticks (10 MHz, emulated) and candidates per eviction, mean over all runs**

| policy | ticks / eviction | candidates / eviction |
|---|---|---|
| Clock | 35.3 | 106.0 |
| FIFO | 12.6 | 106.0 |
| Aging | 199.6 | 106.0 |
| LFU (decayed) | 199.4 | 106.0 |
| ML global | 411.0 | 106.0 |
| ML per-workload | 451.7 | 106.0 |
| ML per-workload, K only | 400.6 | 106.0 |

<!-- kernel_vs_sim -->
**Kernel vs simulator: kernel faults / simulated faults for the same stream, frames and policy (median over runs)**

| policy | workload | runs | median | min | max |
|---|---|---|---|---|---|
| aging | btree | 9 | 1.0000 | 1.0000 | 1.0000 |
| aging | graph | 6 | 0.9871 | 0.4531 | 0.9889 |
| aging | kv | 11 | 1.0226 | 1.0098 | 1.0601 |
| aging | matmul | 2 | 1.0002 | 1.0000 | 1.0005 |
| aging | sort | 5 | 1.0074 | 1.0074 | 1.0180 |
| clock | btree | 9 | 0.9996 | 0.9964 | 1.0004 |
| clock | graph | 6 | 0.9777 | 0.4257 | 0.9799 |
| clock | kv | 11 | 1.0235 | 1.0085 | 1.0391 |
| clock | matmul | 2 | 1.0000 | 1.0000 | 1.0000 |
| clock | sort | 5 | 1.0090 | 0.9520 | 1.0142 |
| fifo | btree | 9 | 1.0183 | 1.0097 | 1.0225 |
| fifo | graph | 6 | 0.9982 | 0.8544 | 0.9995 |
| fifo | kv | 11 | 1.1440 | 1.0996 | 1.1490 |
| fifo | matmul | 2 | 1.3607 | 1.3324 | 1.3889 |
| fifo | sort | 5 | 1.2006 | 1.2006 | 1.4114 |
| lfu | btree | 9 | 1.0045 | 1.0023 | 1.0055 |
| lfu | graph | 6 | 0.9871 | 0.8323 | 0.9885 |
| lfu | kv | 11 | 1.0394 | 1.0280 | 1.0834 |
| lfu | matmul | 2 | 1.0002 | 1.0000 | 1.0005 |
| lfu | sort | 5 | 1.0153 | 1.0153 | 1.0181 |
| ml/global | btree | 9 | 1.0001 | 0.9973 | 1.0026 |
| ml/global | graph | 6 | 1.0299 | 1.0150 | 1.2339 |
| ml/global | kv | 11 | 1.0009 | 0.9924 | 1.0209 |
| ml/global | matmul | 2 | 0.8335 | 0.8146 | 0.8524 |
| ml/global | sort | 5 | 1.0000 | 0.9904 | 1.0024 |
| ml/workload | btree | 9 | 1.0006 | 1.0000 | 1.0441 |
| ml/workload | graph | 6 | 0.9442 | 0.3805 | 0.9987 |
| ml/workload | kv | 11 | 0.9938 | 0.9851 | 1.0187 |
| ml/workload | matmul | 2 | 1.0659 | 1.0650 | 1.0668 |
| ml/workload | sort | 5 | 0.9886 | 0.9883 | 0.9984 |
| ml/workload-k | btree | 9 | 1.0019 | 1.0012 | 1.0472 |
| ml/workload-k | graph | 6 | 0.9449 | 0.3670 | 0.9985 |
| ml/workload-k | kv | 11 | 1.0218 | 1.0076 | 1.0288 |
| ml/workload-k | matmul | 2 | 1.0002 | 1.0000 | 1.0005 |
| ml/workload-k | sort | 5 | 1.0074 | 1.0074 | 1.0180 |

<!-- kernel_pred -->
**Kernel measurement vs simulator prediction for the same runs: faults / Clock, 10% (kernel → simulated)**

| workload | split | FIFO | ML global | ML per-workload |
|---|---|---|---|---|
| btree | test | 1.143 → 1.121 | 0.843 → 0.841 | 0.823 → 0.804 |
| btree | heldout | 1.087 → 1.068 | 0.893 → 0.893 | 0.854 → 0.853 |
| graph | test | 2.096 → 1.632 | 0.989 → 0.659 | 0.614 → 0.625 |
| graph | heldout | 1.289 → 1.262 | 0.535 → 0.515 | 0.541 → 0.561 |
| kv | test | 1.284 → 1.159 | 0.875 → 0.891 | 0.871 → 0.889 |
| kv | heldout | 1.312 → 1.174 | 0.878 → 0.901 | 0.875 → 0.905 |
| matmul | heldout | 1.820 → 1.338 | 1.115 → 1.338 | 0.973 → 0.913 |
| sort | test | 1.331 → 0.976 | 0.980 → 0.967 | 0.960 → 0.950 |
| sort | heldout | 1.190 → 1.000 | 0.977 → 0.986 | 0.933 → 0.951 |

<!-- kernel_cliff -->
**The outlier stream graph-pr2000x2-s3: kernel faults at 167 frames vs the simulator at that many frames and a few more**

| policy | kernel | sim +0 | sim +1 | sim +2 | sim +3 | sim +4 |
|---|---|---|---|---|---|---|
| Clock | 23390 | 54948 | 39982 | 23609 | 12041 | 6758 |
| FIFO | 86130 | 100806 | 92613 | 85126 | 78665 | 72553 |
| Aging | 41625 | 91873 | 73061 | 42768 | 13805 | 4742 |
| LFU (decayed) | 84009 | 100942 | 92095 | 84006 | 76674 | 69405 |
| ML global | 65576 | 53145 | 36474 | 20121 | 9525 | 6577 |
| ML per-workload | 18309 | 48118 | 32800 | 16382 | 7436 | 5327 |
| ML per-workload, K only | 19842 | 54067 | 36946 | 17081 | 7351 | 5245 |

*The simulator at +2 frames reproduces every classical policy's kernel count within 3%: the stream sits on a capacity cliff.*

<!-- quant_compact -->
**Integer-only scoring of the selected kernel+refault model (per-workload) — faults / Clock**

| workload | split | float | int, 4-bit | int, 8-bit | int, 12-bit |
|---|---|---|---|---|---|
| btree | test | 0.835 | 0.834 | 0.835 | 0.835 |
| btree | heldout | 0.875 | 0.873 | 0.875 | 0.875 |
| graph | test | 0.847 | 0.848 | 0.846 | 0.846 |
| graph | heldout | 0.798 | 0.812 | 0.799 | 0.799 |
| kv | test | 0.904 | 0.904 | 0.904 | 0.904 |
| kv | heldout | 0.902 | 0.903 | 0.901 | 0.902 |
| lzw | test | 0.821 | 0.823 | 0.821 | 0.820 |
| lzw | heldout | 0.813 | 0.810 | 0.813 | 0.813 |
| matmul | heldout | 0.671 | 0.681 | 0.676 | 0.676 |
| sort | test | 0.983 | 0.983 | 0.983 | 0.983 |
| sort | heldout | 0.933 | 0.932 | 0.933 | 0.933 |

*Features in Q8 fixed point; weights with the standardisation folded in, rounded to b fractional bits.*

<!-- dagger_compact -->
**One DAgger round (per-workload linear models) — faults / Clock, geo-mean 5/10/20%**

| workload | split | trained under LRU | after DAgger |
|---|---|---|---|
| btree | test | 0.835 | 0.848 |
| btree | heldout | 0.875 | 0.904 |
| graph | test | 0.847 | 0.891 |
| graph | heldout | 0.798 | 0.803 |
| kv | test | 0.904 | 0.904 |
| kv | heldout | 0.902 | 0.903 |
| lzw | test | 0.821 | 0.872 |
| lzw | heldout | 0.813 | 0.852 |
| matmul | heldout | 0.671 | 0.699 |
| sort | test | 0.983 | 0.998 |
| sort | heldout | 0.933 | 0.951 |

