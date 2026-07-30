"""Deterministic augmented synthetic-control primitives for the At-Berth study.

The implementation follows the ridge-augmented weighting representation in
Ben-Michael, Feller, and Rothstein (2021, JASA, eqs. 17--18): start from
simplex-constrained synthetic-control weights and penalise the augmented
weights' distance from that solution.  This module is outcome-agnostic; study
periods, features and success rules remain in the registered analysis driver.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def standardise_features(treated: np.ndarray, donors: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scale feature columns jointly, leaving constant columns well-defined."""
    treated = np.asarray(treated, dtype=float).reshape(-1)
    donors = np.asarray(donors, dtype=float)
    if donors.ndim != 2 or donors.shape[1] != treated.size:
        raise ValueError("donors must be donor-by-feature and align with treated features")
    if not np.isfinite(treated).all() or not np.isfinite(donors).all():
        raise ValueError("synthetic-control features must be finite")
    combined = np.vstack([treated, donors])
    scale = combined.std(axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    center = combined.mean(axis=0)
    return (treated - center) / scale, (donors - center) / scale, scale


def simplex_scm_weights(treated: np.ndarray, donors: np.ndarray) -> np.ndarray:
    """Minimise pre-feature imbalance over non-negative weights summing to one."""
    treated, donors, _ = standardise_features(treated, donors)
    n_donors = donors.shape[0]
    if n_donors < 2:
        raise ValueError("synthetic control requires at least two donors")

    def objective(weights: np.ndarray) -> float:
        imbalance = treated - donors.T @ weights
        return float(imbalance @ imbalance)

    result = minimize(
        objective,
        np.full(n_donors, 1.0 / n_donors),
        method="SLSQP",
        bounds=[(0.0, 1.0)] * n_donors,
        constraints={"type": "eq", "fun": lambda weights: float(weights.sum() - 1.0)},
        options={"ftol": 1e-12, "maxiter": 10000, "disp": False},
    )
    if not result.success:
        raise RuntimeError(f"simplex SCM optimisation failed: {result.message}")
    weights = np.clip(result.x, 0.0, 1.0)
    weights /= weights.sum()
    return weights


def ridge_augmented_weights(
    treated: np.ndarray,
    donors: np.ndarray,
    scm_weights: np.ndarray,
    ridge_penalty: float,
) -> np.ndarray:
    """Return ridge-ASCM weights, centred so their adjustment sums to zero."""
    if ridge_penalty <= 0 or not np.isfinite(ridge_penalty):
        raise ValueError("ridge_penalty must be finite and positive")
    treated, donors, _ = standardise_features(treated, donors)
    scm = np.asarray(scm_weights, dtype=float).reshape(-1)
    if scm.size != donors.shape[0] or not np.isclose(scm.sum(), 1.0, atol=1e-8):
        raise ValueError("SCM weights must align with donors and sum to one")
    donor_center = donors.mean(axis=0)
    centered_donors = donors - donor_center
    centered_treated = treated - donor_center
    imbalance = centered_treated - centered_donors.T @ scm
    system = centered_donors.T @ centered_donors + ridge_penalty * np.eye(donors.shape[1])
    adjustment = centered_donors @ np.linalg.solve(system, imbalance)
    augmented = scm + adjustment
    # Centering makes this identity exact up to floating point; enforce it so
    # every downstream counterfactual remains an affine combination.
    augmented += (1.0 - augmented.sum()) / augmented.size
    return augmented


def default_ridge_grid(treated: np.ndarray, donors: np.ndarray) -> np.ndarray:
    """Freeze a scale-aware 41-point log grid before cross-validation."""
    treated, donors, _ = standardise_features(treated, donors)
    centered = donors - donors.mean(axis=0)
    singular = np.linalg.svd(centered, compute_uv=False)
    scale = float(singular[0] ** 2) if singular.size and singular[0] > 0 else 1.0
    return scale * np.logspace(-4, 4, 41)


def select_ridge_penalty_by_year(
    folds: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    ridge_grid: Iterable[float],
) -> tuple[float, pd.DataFrame]:
    """Select lambda by leave-one-pre-year-out prediction MSE.

    Each fold is ``(treated_features, donor_features, held_treated_outcome,
    held_donor_outcomes)``. Held outcomes may contain all twelve months; donor
    outcomes are month-by-donor. Ties choose the larger penalty, the more
    conservative (less extrapolative) solution.
    """
    penalties = np.asarray(list(ridge_grid), dtype=float)
    if penalties.size == 0 or (penalties <= 0).any() or not np.isfinite(penalties).all():
        raise ValueError("ridge grid must contain finite positive penalties")
    rows = []
    for penalty in penalties:
        squared_errors = []
        for treated_x, donor_x, held_treated, held_donors in folds:
            held_treated = np.asarray(held_treated, dtype=float).reshape(-1)
            held_donors = np.asarray(held_donors, dtype=float)
            if held_donors.ndim != 2 or held_donors.shape[0] != held_treated.size:
                raise ValueError("held-out donor outcomes must be month-by-donor")
            scm = simplex_scm_weights(treated_x, donor_x)
            augmented = ridge_augmented_weights(treated_x, donor_x, scm, float(penalty))
            if held_donors.shape[1] != augmented.size:
                raise ValueError("held-out donor outcomes do not align with weights")
            error = held_treated - held_donors @ augmented
            if not np.isfinite(error).all():
                raise ValueError("held-out outcomes must be finite")
            squared_errors.extend(np.square(error).tolist())
        rows.append({"ridge_penalty": float(penalty), "cv_mse": float(np.mean(squared_errors))})
    table = pd.DataFrame(rows).sort_values(["cv_mse", "ridge_penalty"], ascending=[True, False], kind="stable")
    selected = float(table.iloc[0].ridge_penalty)
    return selected, table.sort_values("ridge_penalty", kind="stable").reset_index(drop=True)


def rmspe(gaps: np.ndarray) -> float:
    """Root mean squared prediction error for a finite gap vector."""
    gaps = np.asarray(gaps, dtype=float).reshape(-1)
    if gaps.size == 0 or not np.isfinite(gaps).all():
        raise ValueError("RMSPE requires at least one finite gap")
    return float(np.sqrt(np.mean(np.square(gaps))))


def rmspe_ratio(pre_gaps: np.ndarray, post_gaps: np.ndarray) -> float:
    """Post/pre RMSPE ratio, failing on a degenerate exact pre-fit."""
    pre = rmspe(pre_gaps)
    if pre <= 1e-12:
        raise ValueError("post/pre RMSPE is undefined for a zero pre-RMSPE")
    return rmspe(post_gaps) / pre


def exact_placebo_rank_pvalue(treated_ratio: float, placebo_ratios: np.ndarray) -> dict:
    """Return the inclusive finite-sample in-space placebo rank and p-value."""
    placebo = np.asarray(placebo_ratios, dtype=float).reshape(-1)
    if not np.isfinite(treated_ratio) or not np.isfinite(placebo).all():
        raise ValueError("placebo ratios must be finite")
    at_least_as_extreme = int(np.count_nonzero(placebo >= treated_ratio))
    rank = 1 + at_least_as_extreme
    total = 1 + placebo.size
    return {
        "descending_rank": rank,
        "comparison_units_including_treated": total,
        "exact_inclusive_pvalue": rank / total,
        "minimum_attainable_pvalue": 1 / total,
        "fraction_placebos_less_extreme": float(np.mean(placebo < treated_ratio)) if placebo.size else 0.0,
    }


def circular_block_bootstrap_mean(
    residuals: np.ndarray,
    *,
    target_length: int,
    block_length: int = 12,
    draws: int = 10000,
    seed: int = 20250718,
) -> np.ndarray:
    """Bootstrap a mean from circular moving blocks of stable-pre residuals."""
    residuals = np.asarray(residuals, dtype=float).reshape(-1)
    if residuals.size < 2 or not np.isfinite(residuals).all():
        raise ValueError("bootstrap residuals require at least two finite values")
    if target_length <= 0 or block_length <= 0 or draws <= 0:
        raise ValueError("bootstrap lengths and draws must be positive")
    rng = np.random.default_rng(seed)
    blocks_needed = int(np.ceil(target_length / block_length))
    output = np.empty(draws, dtype=float)
    offsets = np.arange(block_length)
    for draw in range(draws):
        starts = rng.integers(0, residuals.size, size=blocks_needed)
        indices = ((starts[:, None] + offsets[None, :]) % residuals.size).reshape(-1)[:target_length]
        output[draw] = residuals[indices].mean()
    return output


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm step-down family-wise adjusted p-values."""
    if not pvalues:
        return {}
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    if any((not np.isfinite(value)) or value < 0 or value > 1 for _, value in ordered):
        raise ValueError("p-values must be finite and in [0, 1]")
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * value))
        adjusted[name] = running
    return adjusted
