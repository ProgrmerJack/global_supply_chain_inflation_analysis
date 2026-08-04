"""Numerical invariants for the registered augmented synthetic-control engine."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_simplex_and_augmented_weights_recover_exact_convex_fit():
    from models.augmented_synth import ridge_augmented_weights, simplex_scm_weights

    donors = np.array([[0.0, 1.0], [2.0, 3.0], [4.0, 0.0]])
    truth = np.array([0.25, 0.75, 0.0])
    treated = donors.T @ truth
    scm = simplex_scm_weights(treated, donors)
    augmented = ridge_augmented_weights(treated, donors, scm, 1.0)

    assert np.all(scm >= -1e-12)
    assert scm.sum() == pytest.approx(1.0)
    assert donors.T @ scm == pytest.approx(treated, abs=1e-6)
    assert augmented == pytest.approx(scm, abs=1e-6)
    assert augmented.sum() == pytest.approx(1.0)


def test_ridge_augmentation_improves_outside_hull_fit_and_controls_extrapolation():
    from models.augmented_synth import ridge_augmented_weights, simplex_scm_weights

    donors = np.array([[0.0], [1.0], [2.0]])
    treated = np.array([3.0])
    scm = simplex_scm_weights(treated, donors)
    weak_penalty = ridge_augmented_weights(treated, donors, scm, 0.01)
    strong_penalty = ridge_augmented_weights(treated, donors, scm, 1000.0)

    assert abs(treated[0] - donors.T @ weak_penalty) < abs(treated[0] - donors.T @ scm)
    assert np.linalg.norm(strong_penalty - scm) < np.linalg.norm(weak_penalty - scm)
    assert weak_penalty.sum() == pytest.approx(1.0)


def test_leave_year_out_cv_selects_predictive_penalty_deterministically():
    from models.augmented_synth import select_ridge_penalty_by_year

    donors = np.array([[0.0], [1.0], [2.0]])
    treated = np.array([3.0])
    held_donors = np.array([[0.0, 1.0, 2.0], [0.5, 1.5, 2.5]])
    held_treated = np.array([3.0, 3.5])
    folds = [(treated, donors, held_treated, held_donors)] * 3
    selected, table = select_ridge_penalty_by_year(folds, [0.01, 1.0, 1000.0])

    assert selected == 0.01
    assert table.shape == (3, 2)


def test_placebo_rank_discloses_coarse_minimum_pvalue():
    from models.augmented_synth import exact_placebo_rank_pvalue

    result = exact_placebo_rank_pvalue(4.0, np.array([1.0, 2.0, 5.0, 3.0]))
    assert result["descending_rank"] == 2
    assert result["exact_inclusive_pvalue"] == pytest.approx(0.4)
    assert result["minimum_attainable_pvalue"] == pytest.approx(0.2)


def test_circular_bootstrap_is_reproducible_and_holm_is_monotone():
    from models.augmented_synth import circular_block_bootstrap_mean, holm_adjust

    residuals = np.arange(24, dtype=float) - 11.5
    left = circular_block_bootstrap_mean(residuals, target_length=12, draws=100, seed=7)
    right = circular_block_bootstrap_mean(residuals, target_length=12, draws=100, seed=7)
    assert np.array_equal(left, right)

    adjusted = holm_adjust({"a": 0.01, "b": 0.03, "c": 0.5})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.5})
