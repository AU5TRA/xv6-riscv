"""numpy forward (the simulator callback) == the trained torch network, for every architecture."""
import numpy as np
import torch
import extra_core as Z
import extra_nn as N

d = Z.load("val", "sort", hist=True)
for arch, _ in N.GRID:
    net, norm, cols, v = N.train("sort", arch, "FK" if arch != "agecnn" else "K", epochs=2)
    spec = N.export(net, norm, cols, arch)
    fn = N.make_fn(spec)
    (X, H, Y, W, Mk), _ = N.sets(d, cols, arch, norm)
    net.eval()
    with torch.no_grad():
        P = net(X[:40].to(N.DEV), H[:40].to(N.DEV), Mk[:40].to(N.DEV)).cpu().numpy()
    g = d["group"]; worst = 0.0
    for i, gid in enumerate(np.unique(g)[:40]):
        m = g == gid
        if m.sum() > N.MAXC:
            continue
        # candidate order inside the set is the stable sort order used by sets()
        out = fn(d["feat"][m], d["hist"][m])
        worst = max(worst, float(np.abs(out - P[i][:m.sum()]).max()))
    print(f"{arch:8s} val mse {v:.3f}  max |numpy - torch| {worst:.2e}")
    assert worst < 2e-3, arch
print("extra nn checks passed")
