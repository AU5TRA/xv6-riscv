# ML page-replacement training — detailed technical record

**Written for**: whoever next touches the ML side of this project (AU5TRA,
a supervisor, or future-me) and needs to understand exactly what data was
used, how it was prepared, what was fed into each model, and how every
number in `report/ML_TESTING_REPORT.md` was actually produced — not just
the headline results, but the pipeline behind them.

This file previously held a merge-handoff note about the paging/swap
kernel work (`kernel/vmpage.c` etc.) from an earlier point in the project.
That content is gone — this is a full replacement, not an addendum. If you
need the old merge-handoff content, it's in git history (`git log -p --
AUSTRA_HANDOFF.md`).

All of the work below runs **entirely on the host**, in Python
(NumPy/PyTorch), never inside xv6 — the kernel has no floating point
(deliberately), so nothing here executes in the emulated machine. What
*could* eventually run inside xv6 is a separate, harder question (fixed
-point inference) touched on at the end.

---

## 1. Where the training data comes from

Every experiment trains and evaluates against **real reference streams
captured from real runs of the native workload suite inside xv6** — not
synthetic/randomly-generated sequences. The capture mechanism
(`user/vmbench.h`'s `vmbench_trace_ref()`, documented in
`docs/workloads.md`) prints one `T <vpn>` line per real page reference
from each workload's own dominant page-accessor function, giving a
**full reference stream** (every touch, not just faults — a page that
stays resident and gets re-touched without faulting is still recorded,
which the ground-truth calculation below needs).

Seven workload/variant configurations exist, each backed by one large
`.trace` file (the reference stream) plus several small `.log` files
(headers only, one per resident-limit percentage the workload was run
at):

| workload | trace file | references |
|---|---|---|
| `btreebench` | `traces/btreebench/btreebench.trace` | 223,649 |
| `kvbench` | `traces/kvbench/kvbench.trace` | 160,256 |
| `sortbench` | `traces/sortbench/sortbench.trace` | 1,854,621 |
| `graphbench` | `traces/graphbench/graphbench.trace` | 2,703,968 |
| `lzwbench` | `traces/lzwbench/lzwbench.trace` | 12,295,734 |
| `matmulbench-naive` | `traces/matmulbench/matmulbench-naive.trace` | 1,778,688 |
| `matmulbench-blocked` | `traces/matmulbench/matmulbench-blocked.trace` | 1,999,872 |

`tools/trace_decode.py`'s `decode_split(header_path, refs_path)` reads a
`.log` file's `TRACEHDR ...` line (key=value fields: `workload`, `seed`,
`resident_limit`, `arena_cache_budget`, `policy`, `arena_start_vpn`,
`arena_pages`) and pairs it with the `.trace` file's `T <vpn>` lines,
returning `(header_dict, list_of_vpns)`. Every ML script does exactly
this to load data — nothing reads raw log text itself.

**One nuance worth being explicit about**: `vpn` values are *absolute*
virtual page numbers (`arena_start_vpn` + offset within the workload's
arena), not 0-indexed. This matters for anything that sizes an array or
embedding table by page number (see Experiment 5's bug, below) —
`arena_pages` in the header is a *count*, not a safe upper bound on the
actual vpn values you'll see.

## 2. Train/held-out split: same stream, two capacities

**This is not a train/test split across independent runs.** For each
workload, the exact same captured reference stream is replayed through
the simulator twice, at two different `resident_limit` capacities read
from two different `.log` headers:

- a **tighter** capacity, used to fit every model (e.g.
  `graph-p15-c200.log`, capacity 204 — "p15" names roughly the resident
  -limit percentage of the workload's own footprint at collection time)
- a **looser** capacity, used only for evaluation, never seen during
  training (e.g. `graph-p20-c267.log`, capacity 271)

So every number reported as "held-out" in this project checks
generalization **across memory pressure on the same access pattern**,
not generalization to an unseen workload run. This was a deliberate,
cheap way to get *a* held-out check without needing to capture and store
two separate multi-million-reference traces per workload. Whether a
model trained on one workload's stream transfers to a *different*
workload's stream, or to a re-run with a different random seed, was
never tested — see `report/ML_TESTING_REPORT.md`'s "what this does and
doesn't show" section.

Per-workload train/held-out capacities used throughout (Experiments 3-5):

| workload | train capacity | held-out capacity |
|---|---|---|
| btreebench | 270 | 359 |
| kvbench | 82 | 109 |
| sortbench | 16 | 20 |
| graphbench | 204 | 271 |
| lzwbench | 28 | 30 |
| matmulbench-naive | 8 | 12 |
| matmulbench-blocked | 8 | 12 |

Training itself never uses the full stream either: every experiment
subsamples to a fixed budget, `TRAIN_SUBSAMPLE = 300_000` examples
(`np.random.default_rng(0).choice(len(train_refs), size=min(300_000,
len(train_refs)), replace=False)` — seeded, so reproducible), even when
the underlying stream has many millions of references (lzwbench: 12.3M).
**Evaluation always runs on the full stream** — fault/eviction counts are
path-dependent (an early wrong eviction changes the resident set for
everything after it), so you can't subsample the simulation itself, only
the training set.

## 3. Ground truth: Belady's own next-reuse-distance

Every learned model (Experiments 1, 2, 3, 5 — Experiment 4's hand-written
policies need no labels at all) is trained to predict the same quantity:
**the true forward distance, in reference-stream positions, to a page's
own next touch** — exactly the quantity Belady's optimal algorithm
(`tools/sim.py`'s `belady_faults_evictions()`) uses internally to decide
who to evict (evict whoever's own next use is furthest away, or never
happens again).

Computed by a single backward scan over the *already-recorded* trace
(never real lookahead at serving time — this is only for building
training labels, and the eviction simulator at evaluation time only ever
uses the model's own prediction, never the true label):

```python
next_pos = {}
y = np.zeros(n, dtype=np.float32)
for i in range(n - 1, -1, -1):
    vpn = refs[i]
    dist = next_pos.get(vpn, NEVER_AGAIN_CAP) - i if vpn in next_pos \
        else NEVER_AGAIN_CAP
    y[i] = min(dist, 50_000)
    next_pos[vpn] = i
```

Two transforms applied to every label, everywhere:

- **Capped at 50,000** — pages touched once and never again would
  otherwise get an astronomically large label (`NEVER_AGAIN_CAP = 1 <<
  20`) that would dominate an MSE loss. Capping just says "far enough
  away to be a safe eviction," which is all eviction ranking needs.
- **`log1p`-transformed** for training stability (large-magnitude
  regression targets are hard on plain MSE). This is a **monotonic**
  transform, so `argmax(log1p(x)) == argmax(x)` — it changes nothing
  about which candidate a trained model would actually pick to evict, it
  just makes the loss surface nicer to optimize.

## 4. Feature engineering (Experiment 2's causal features)

Every non-architecture-only feature computed in `tools/ml_feature_experiments.py`
is computed **causally** — using only information available at reference
`i`, never anything from the future — because that's the actual
constraint a real eviction policy would face:

```python
for i, vpn in enumerate(refs):
    if vpn not in last_pos:
        distinct_seen += 1
    recency[i]           = i - last_pos.get(vpn, i)
    stack_distance[i]    = distinct_seen - last_distinct_at.get(vpn, distinct_seen)
    global_frequency[i]  = freq.get(vpn, 0)
    vpn_identity[i]       = vpn / max(arena_pages, 1)
    position[i]           = i / n

    last_pos[vpn] = i
    freq[vpn] = freq.get(vpn, 0) + 1
    last_distinct_at[vpn] = distinct_seen
```

- **`recency`** — reference-count gap since this page's own last touch.
- **`stack_distance`** — the theoretically correct LRU distance: *distinct
  pages* touched since this page's last touch (not raw elapsed time).
- **`global_frequency`** — total times this page has been touched so far
  in the run.
- **`vpn_identity`** — the page number itself, normalized to `[0,1]` by
  dividing by `arena_pages` — tests whether some pages are just
  intrinsically hot regardless of access history (e.g. hub vertices).
- **`position`** — how far into the run this reference is (`i/n`) — tests
  whether different phases of a workload (e.g. graphbench's BFS phase vs.
  its PageRank phase) have distinguishable access signatures.
- **`all_combined`** — all five stacked as a 5-column feature matrix.

Feature sets are tried both **before** training anything (raw Pearson
correlation against the log-label — a free, no-training-required sanity
check) and after (actual simulated fault counts) — the two can and do
disagree (see `position`'s finding below), which is itself one of the
report's findings.

## 5. Experiment 0 — the original prototype (superseded)

`tools/ml_policy_prototype.py`: closed-form linear regression
(`np.linalg.lstsq`) on 3 hand-picked scalars (`recency`, `frequency`,
`prev_interval`), trained/evaluated on graphbench only. Chosen
deliberately as the simplest possible model — a linear model is trivially
portable to fixed-point kernel arithmetic, which matters if this were
ever deployed inside xv6. Result: lost to every classical policy. This
result is what motivated Experiments 1 and 2 (is it the model, or the
features?).

## 6. Experiment 1 — does model architecture matter?

Script: `tools/ml_arch_experiments.py`. Graphbench only (generalized to
all 7 workloads later, in Experiment 3).

**Input representation** (shared across all 7 architectures, for a fair
comparison): each page's own last **K=8** inter-access intervals
(zero-padded, oldest first, if the page has fewer than 8 prior touches).
Built once by `build_dataset(refs)`, which maintains a per-page rolling
history dict during a single forward pass, then a backward pass for
labels (same Belady label computation as above).

**Seven architectures, all mapping `(batch, K) -> (batch,)`**:

1. `Linear8` — `nn.Linear(K, 1)`, no nonlinearity, on the full 8-window
   (isolates "does more raw history help" without any capacity increase).
2. `MLP` — `Linear(K,32) -> ReLU -> Linear(32,32) -> ReLU -> Linear(32,1)`.
3. `RecurrentModel("rnn")` — `nn.RNN(input_size=1, hidden_size=16,
   batch_first=True)`, final hidden state through a linear head.
4. `RecurrentModel("lstm")` — same shape, `nn.LSTM` (note: LSTM returns
   `(h_n, c_n)`, only `h_n` used — a subtlety fixed before the first run,
   `hn = h[0] if isinstance(h, tuple) else h`).
5. `RecurrentModel("gru")` — same shape, `nn.GRU`.
6. `CNN1D` — two `Conv1d(kernel_size=3, padding=1)` layers (16 channels)
   over the length-8 sequence, flattened into a linear head.
7. `TinyAttention` — each of the 8 scalar intervals embedded up to
   `d_model=16` via a linear layer, plus a **learned** positional
   embedding (`nn.Parameter(torch.zeros(K, d_model))`), through one
   `nn.MultiheadAttention(d_model=16, heads=2, batch_first=True)` block,
   flattened into a linear head.

**Training**: Adam, `lr=1e-3`, MSE loss, batch size 4096, 6 epochs, on
the 300,000-example subsample; `torch.manual_seed(0)` before constructing
each model, for reproducibility.

**Diagnostic run first** (cheap, no training): raw correlation between
each of the 8 interval-history positions and the label —
`-0.014, +0.132, -0.014, -0.014, -0.014, -0.014, -0.014, -0.014` for
`k=1..8`. Only the 2nd-most-recent interval shows any correlation at all,
and it's weak. This diagnostic ran *before* any model was trained, and
already predicted the outcome.

**Result**: all seven architectures land within ~0.2% of each other and
of the classical policies' own tight cluster (143,107–143,345 train
faults), nowhere near Belady's 87,042. Conclusion: **the feature
representation was the bottleneck, not model capacity** — going from a
3-scalar linear model to an 8-step attention model changed essentially
nothing, because a page's *own* access-timing history structurally
cannot encode graphbench's real driver (graph topology: is this page a
hub vertex, what BFS frontier is it in).

## 7. Experiment 2 — does the feature set matter?

Script: `tools/ml_feature_experiments.py`. Graphbench only (again,
generalized in Experiment 3).

**Six feature sets** (Section 4 above) × **two model types**:

```python
class Linear(nn.Module):        # nn.Linear(n_in, 1)
class MLP(nn.Module):           # Linear(n_in,32)->ReLU->Linear(32,32)->ReLU->Linear(32,1)
```

Same training hyperparameters as Experiment 1 (Adam, lr=1e-3, batch
4096, 6 epochs, 300K subsample, seed 0).

**Diagnostic correlations** (2,703,968 examples): `recency -0.0139`,
`stack_distance -0.0069`, `global_frequency -0.2138`, `vpn_identity
+0.0000`, `position -0.2178`.

**Headline result**: `global_frequency` + plain **linear** regression —
138,343 train-faults / 128,996 held-out-faults — the first approach to
genuinely beat every classical policy (best classical, Clock: 143,231 /
134,760). A ~3.4–4.3% reduction, holding up (even improving slightly) on
held-out capacity, so not an overfit to the training capacity.

**Three findings that mattered methodologically** (full detail in
`report/ML_TESTING_REPORT.md`):

1. The MLP on `global_frequency` alone is *worse* than the linear model
   on the same one feature (147,622 vs. 138,343) — more capacity
   actively hurt (likely overfitting a nonlinearity onto what's
   fundamentally a monotonic relationship).
2. `position` correlates almost as strongly as `global_frequency`
   (-0.218 vs. -0.214) but does nothing for the actual policy (142,879,
   barely off the classical cluster) — because `position` is a function
   only of the *current reference index*, so it's identical across every
   candidate compared at a single eviction decision. Correlation with
   the label in aggregate is not sufficient; a feature has to vary
   *across candidates being compared*, which is the only thing an
   eviction decision can actually use.
3. `all_combined` is worse than `global_frequency` alone for both model
   types (147,079 linear / 141,147 MLP) — adding weak/non-differentiating
   features diluted the one genuinely useful signal.

## 8. Experiment 3 — generalizing across all 7 workloads

Script: `tools/ml_comprehensive.py`. Reruns every architecture from
Experiment 1 (7) and every feature-set/model combo from Experiment 2 (12)
— 19 learned configurations per workload — on **all seven**
workload/variant configurations, plus the classical baselines
(`fifo`/`clock`/`aging`/`lru`/`lfu`/`stackdist`/`belady`) recomputed fresh
per workload. **133 trained models total** (19 × 7), ~76 minutes wall
time on CPU. Every trained model's weights (`torch.save(state_dict)`) and
a metadata sidecar (workload, feature set/architecture, capacities,
resulting fault counts) are saved under `report/models/` (266 files) —
any single number in the report can be traced back to an actual
reloadable model.

**Result**: a learned model beat the best classical policy on 5 of 7
configurations (up to −18% on lzwbench, −15% on sortbench), but **no
single feature set won everywhere** — `all_combined` won on
btreebench/kvbench/sortbench, `global_frequency` alone on graphbench,
`stack_distance` on lzwbench.

**The catastrophic-failure investigation** (triggered by the project
instruction "if you keep getting negative results, do a comprehensive
study to find out why"): scanning every held-out result for >5x worse
than the worst classical policy turned up a sharp pattern concentrated
entirely in `sortbench` (10 of 12 feature configs, up to 721x worse) and
both `matmulbench` variants (up to 6,171x worse) — never in
btreebench/kvbench/graphbench/lzwbench. Root-caused by inspecting
`sortbench`'s `vpn_identity`-only model directly: `vpn_identity` is a
**static** per-page value, so the model's predicted eviction priority for
a given page never changes across the whole run. Sortbench's small,
rigidly-cyclic access pattern (fixed merge-sort passes over ~12-16 pages)
means a static wrong preference evicts the *same* soon-to-be-needed page
on every single pass, and with such a small working set, that one bad
decision compounds across the whole run instead of averaging out the way
it would on a larger, more varied workload like graphbench's.

## 9. Experiment 4 — do hand-written (non-learned) heuristics capture the same gain?

Script: `tools/handwritten_policy_sweep.py`. No training, no PyTorch
dependency at all — added two plain counter-based policies directly to
`tools/sim.py` (mirroring the existing `Fifo`/`Clock`/`Aging`/`Lru`
classes):

```python
class Lfu:
    """Evict the resident page with the lowest total access count."""
    def access(self, vpn):
        self.freq[vpn] = self.freq.get(vpn, 0) + 1
        ...
        victim = min(self.resident, key=lambda p: self.freq[p])

class StackDistance:
    """Evict the resident page with the largest current stack distance
    (distinct pages touched since its last access)."""
    def access(self, vpn):
        ...
        victim = max(self.resident,
                     key=lambda p: self.distinct_seen - self.last_distinct_at[p])
```

Run across all 7 workloads via `tools/sim.py`'s `run_policy()`.

**Two findings**: (1) hand-written `lfu`, zero training, beats every
classical policy *and* every learned model tried on lzwbench (37,705 vs.
Clock's 49,731 held-out faults, −24.2%) — the single best result in the
whole project, and free to actually implement. (2) The same catastrophic
failures from Experiment 3 reappear here with **no learning involved at
all** (`lfu` up to ~14,600x worse than the best classical policy on
matmulbench-naive) — proving those failures are a property of
frequency/distance-based eviction on those specific access patterns, not
a training/generalization artifact.

This result directly motivated implementing `Lfu` as a real
`kernel/vmpage.c` eviction policy (`VM_POLICY_LFU`) — see that work
separately; not part of the Python-side pipeline documented here.

## 10. Experiment 5 — cross-page context (the expensive one)

Script: `tools/ml_embedding_experiment.py`. Every feature tried in
Experiments 1-4 only ever looked at a single page's own history in
isolation — nothing could represent "these pages tend to be touched
together." This experiment gives the model genuine cross-page
information:

```python
class GlobalContextModel(nn.Module):
    def __init__(self, vocab_size, embed_dim=16, hidden=16):
        self.embed = nn.Embedding(vocab_size + 1, embed_dim)
        self.gru = nn.GRU(embed_dim, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden + embed_dim, hidden),
                                   nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, ctx, target):
        ctx_emb = self.embed(ctx)       # (batch, W=16, embed_dim) -- last 16
                                          # GLOBALLY referenced pages, not the
                                          # candidate's own history
        _, h = self.gru(ctx_emb)
        tgt_emb = self.embed(target)     # the specific candidate's own embedding
        combined = torch.cat([h[-1], tgt_emb], dim=-1)
        return self.head(combined).squeeze(-1)
```

A learned `nn.Embedding` per page (shaped freely during training, unlike
Experiment 2's static `vpn_identity` scalar), fed a window of the last
**W=16** pages referenced *anywhere in the whole process* (not the
candidate's own history), combined with the specific candidate's own
embedding. The global-context half is identical across every candidate
compared at one eviction (same caveat as `position` in Experiment 2), but
each candidate's own embedding still varies, so the model can express
"given what's just happened, how does *this* page look" — real, if
partial, cross-page structure, short of full pairwise attention.

**A real bug hit and fixed while building this**: sizing the embedding
table off the header's `arena_pages` count crashed on lzwbench
(`IndexError: index out of range`) because vpns are absolute
(`arena_start_vpn`-offset), not 0-indexed — `arena_pages` is a count, not
a bound on the actual values. Fixed by sizing the table off the real
observed max vpn in the data (`max(max(train_refs), max(eval_refs)) + 1`)
instead of trusting the metadata field.

**Result: a clean negative finding.** Never beats `global_frequency`
/linear on graphbench (143,017/134,510 vs. 128,996 held-out), never beats
hand-written `lfu` on lzwbench (43,623 vs. 37,705), and is catastrophic
on sortbench and both matmulbench variants (up to 492,119 train faults
vs. classical's ~1,267 on sortbench) — the same small-cyclic-workload
failure mode as everywhere else, because a W=16 context summary averages
away the precise recency tracking those workloads actually need. Given
the extra cost (a GRU forward pass per candidate at every eviction, vs. a
single dot-product for the linear models), this line isn't worth pursuing
further without a fundamentally different way of encoding cross-page
structure (real graph adjacency for graphbench, rather than a
fixed-window proxy for it).

## 11. Training hyperparameters, all in one place

| parameter | value | applies to |
|---|---|---|
| optimizer | Adam | all learned models |
| learning rate | 1e-3 | all |
| loss | MSE, on log1p-transformed labels | all |
| batch size | 4096 | all |
| epochs | 6 | all |
| train subsample | 300,000 examples (seeded, `rng=default_rng(0)`) | all |
| eval set | full reference stream (never subsampled) | all |
| interval-history window K | 8 | Experiment 1 |
| global-context window W | 16 | Experiment 5 |
| embedding dimension | 16 | Experiment 5 |
| label cap | 50,000 (references) | all |
| `NEVER_AGAIN_CAP` (pre-cap sentinel) | 1,048,576 (`1<<20`) | all |
| random seeds | `torch.manual_seed(0)` before each model construction; `np.random.default_rng(0)` for subsampling | all |

## 12. A performance pattern worth knowing if you extend this

Every simulator (`simulate_policy()` in each script) evaluates **one
batched forward pass over all resident candidates per eviction**, never
one candidate at a time — an early attempt at per-candidate NumPy array
construction was too slow at this scale (tens of millions of eviction
decisions across the full sweep). If you add a new model, keep this
shape: collect all current candidates' features into one array/tensor,
one `model(...)` call, `argmax` over the result.

## 13. Where everything lives now

- `tools/ml_policy_prototype.py` — Experiment 0 (superseded).
- `tools/ml_arch_experiments.py` — Experiment 1 (7 architectures).
- `tools/ml_feature_experiments.py` — Experiment 2 (6 feature sets × 2 models).
- `tools/ml_comprehensive.py` — Experiment 3 (both of the above, all 7 workloads).
- `tools/handwritten_policy_sweep.py` — Experiment 4 (hand-written LFU/StackDistance).
- `tools/ml_embedding_experiment.py` — Experiment 5 (cross-page embedding + GRU).
- `tools/sim.py` — the shared host-side simulator (classical policies + Belady + Lfu/StackDistance) every ML script imports and reuses for evaluation.
- `tools/trace_decode.py` — trace-file parsing (`decode_split`).
- `report/ML_TESTING_REPORT.md` — the results narrative (read this for headline numbers and discussion; read this file for methodology and exact code).
- `report/ml_comprehensive_results.csv`, `report/handwritten_results.csv`, `report/embedding_results.csv` — every numeric result, one row per (workload, experiment, model).
- `report/models/` — every trained model's weights (`.pt`) + metadata (`.json`), 133 (Experiment 3) + 7 (Experiment 5) = 140 models.
- `traces/<workload>/` — the underlying `.trace`/`.log` files themselves (gitignored except a few summary files — see `.gitignore` — regenerable via the workload suite in `user/`, documented in `docs/workloads.md`).

## 14. What was never attempted

- Training on one workload's stream and evaluating on a **different**
  workload's stream (cross-workload transfer) — never tried; everything
  here is same-workload, cross-capacity.
- A second random seed / independently-collected run of the same
  workload, to separate "generalizes across memory pressure" from
  "generalizes across genuinely different instances of the same
  workload."
- Fixed-point conversion of any trained model for actual in-kernel
  inference. The simplest candidate (`global_frequency`/linear, a single
  multiply-add) is mathematically just a monotonic rescaling of raw
  frequency, so its eviction *ranking* is identical to the hand-written
  `Lfu` policy already implemented in `kernel/vmpage.c` — meaning there's
  no distinct behavior left to gain from porting that specific model into
  the kernel. A genuinely nonlinear model (e.g. lzwbench's
  `stack_distance`/mlp) would be a real, separate engineering exercise
  (ReLU is fixed-point-friendly; nothing else in that model needs
  transcendental functions) but was judged lower priority than the
  hand-written-LFU kernel work, since simulation already showed
  hand-written LFU beats it on that same workload.
- Real graph-adjacency features for graphbench (as opposed to Experiment
  5's fixed recent-window proxy for cross-page context) — flagged as the
  most promising remaining direction if this line of work continues.
