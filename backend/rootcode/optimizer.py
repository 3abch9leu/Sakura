"""
ROOTOptimizer - NSGA-II search for Pareto-optimal tiles (pymoo).

Decision variables theta: channel width per pocket, cooling-branch width, daily water,
screen porosity, aperture size, number of stacked screen layers.
Objectives: minimise water, heat gain and plant deficit.
Constraints: keep daylight/view (effective porosity) and stay within the household water budget.

The three designs shown to the user are picked from the real Pareto front, never invented.
"""
import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import ElementwiseProblem
from pymoo.optimize import minimize
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM

from . import config as C
from .evaluate import evaluate
from .tile import bounds, decode, n_vars, baseline


class RootProblem(ElementwiseProblem):
    def __init__(self, ctx):
        self.ctx = ctx
        xl, xu = bounds(len(ctx.plants))
        super().__init__(n_var=n_vars(len(ctx.plants)), n_obj=3, n_ieq_constr=4, xl=xl, xu=xu)

    def _evaluate(self, x, out, *args, **kwargs):
        r = evaluate(decode(x, self.ctx.plants), self.ctx)
        o = r["objectives"]
        out["F"] = [o["water_l_day"], o["heat_kwh_day"], o["plant_deficit"]]
        out["G"] = [
            C.MIN_EFFECTIVE_POROSITY - r["panel"]["effective_porosity"],
            o["water_l_day"] - self.ctx.water_available_l_day,
            C.MIN_DRAIN_MIN - r["hydraulics"]["drain_time_min"],
            (r["hydraulics"]["reynolds_max"] - C.MAX_REYNOLDS) / 100.0,
        ]


def optimize(ctx, pop_size=120, n_gen=150, seed=1, verbose=False):
    res = minimize(
        RootProblem(ctx),
        NSGA2(pop_size=pop_size, crossover=SBX(prob=0.9, eta=15), mutation=PM(eta=20),
              eliminate_duplicates=True),
        ("n_gen", n_gen), seed=seed, verbose=verbose,
    )
    if res.X is None:
        raise RuntimeError("No feasible design: raise the water budget or relax the porosity limit.")
    X = np.atleast_2d(res.X)
    F = np.atleast_2d(res.F)
    return X, F


def pick_three(X, F):
    """Water Saver, Shade Maximizer and Balanced, all among plant-safe designs (deficit <= limit)."""
    safe = F[:, 2] <= C.DEFICIT_LIMIT
    idx = np.where(safe)[0] if safe.any() else np.argsort(F[:, 2])[: max(3, len(F) // 5)]
    Fs = F[idx]
    lo, hi = Fs.min(0), Fs.max(0)
    Fn = (Fs - lo) / np.where(hi - lo > 0, hi - lo, 1)
    ws, sm = int(np.argmin(Fs[:, 0])), int(np.argmin(Fs[:, 1]))
    dist = np.linalg.norm(Fn, axis=1)
    if len(Fs) > 2:                     # keep the balanced pick distinct from the two extremes
        dist[[ws, sm]] = np.inf
    picks = {
        "water_saver": idx[ws],
        "shade_maximizer": idx[sm],
        "balanced": idx[int(np.argmin(dist))],
    }
    return {k: int(v) for k, v in picks.items()}, bool(safe.any())


def run(ctx, **kw):
    """Full pipeline: optimise, pick three designs, compare with a conventional tile."""
    X, F = optimize(ctx, **kw)
    picks, plant_safe = pick_three(X, F)
    designs = {}
    for name, i in picks.items():
        d = decode(X[i], ctx.plants)
        designs[name] = {"design": d, "result": evaluate(d, ctx)}
    # fair baseline: conventional tile with the SAME daily water as the balanced design
    base = baseline(ctx.plants, designs["balanced"]["design"].water_l_day)
    designs["baseline"] = {"design": base, "result": evaluate(base, ctx)}
    return {"X": X, "F": F, "designs": designs, "plant_safe_found": plant_safe}
