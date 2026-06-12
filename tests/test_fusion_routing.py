"""Tests de la matemática de ruteo conformal (Fase 3) — la pieza novedosa.

No tocan modelos ni datos: validan las garantías estadísticas en aislamiento.
"""
import numpy as np

from eval.fusion_routing import (
    clopper_pearson_upper,
    conformal_threshold,
    project_prevalence,
)


def test_cp_upper_bounds_in_unit_interval():
    for k, n in [(0, 10), (3, 10), (10, 10), (0, 1)]:
        u = clopper_pearson_upper(k, n, 0.05)
        assert 0.0 <= u <= 1.0


def test_cp_upper_is_one_when_all_positive():
    assert clopper_pearson_upper(5, 5, 0.05) == 1.0


def test_cp_upper_decreases_with_more_evidence():
    # 0 éxitos en 100 da una cota más estrecha que 0 en 10
    assert clopper_pearson_upper(0, 100, 0.05) < clopper_pearson_upper(0, 10, 0.05)


def test_cp_upper_above_point_estimate():
    # La cota superior siempre excede la proporción puntual
    k, n = 2, 50
    assert clopper_pearson_upper(k, n, 0.05) > k / n


def test_conformal_threshold_controls_fraud_escape():
    # Fraude con scores altos, limpios con scores bajos: el umbral debe dejar
    # escapar como mucho una fracción alpha del fraude (cota CP).
    rng = np.random.default_rng(0)
    y = np.array([0] * 200 + [1] * 200)
    scores = np.concatenate([rng.uniform(0, 0.4, 200), rng.uniform(0.6, 1.0, 200)])
    t = conformal_threshold(scores, y, alpha=0.05, delta=0.05)
    # fracción real de fraude que escapa (score<=t) no debe exceder alpha por mucho
    escape = (scores[y == 1] <= t).mean()
    assert escape <= 0.05 + 1e-9


def test_conformal_threshold_separable_allows_coverage():
    # Separable Y con suficiente fraude en calib para que la cota CP certifique:
    # con n=100 tampered y 0 escapes, CP_upper(0,100,.05)~3% <= alpha=10%.
    y = np.array([0] * 100 + [1] * 100)
    scores = np.concatenate([np.full(100, 0.1), np.full(100, 0.9)])
    t = conformal_threshold(scores, y, alpha=0.10, delta=0.05)
    assert np.isfinite(t)
    assert 0.1 <= t < 0.9  # aprueba limpios, no fraude


def test_conformal_needs_enough_calibration_samples():
    # Garantía estricta + pocas muestras de fraude => no certifica (conservador).
    # Es el motivo de que un calib pequeño rutee todo a revisión manual.
    y = np.array([0] * 30 + [1] * 30)
    scores = np.concatenate([np.full(30, 0.1), np.full(30, 0.9)])
    t = conformal_threshold(scores, y, alpha=0.02, delta=0.05)
    assert not np.isfinite(t)  # ningún umbral puede prometer <=2% con n=30


def test_project_prevalence_monotonic_in_base_rate():
    # A mayor prevalencia, mayor fuga para las mismas tasas por-clase
    _, leak_low = project_prevalence(clean_approve_rate=0.9, tamper_approve_rate=0.1, prevalence=0.02)
    _, leak_high = project_prevalence(clean_approve_rate=0.9, tamper_approve_rate=0.1, prevalence=0.50)
    assert leak_high > leak_low


def test_project_prevalence_zero_tamper_escape_zero_leak():
    cov, leak = project_prevalence(clean_approve_rate=0.8, tamper_approve_rate=0.0, prevalence=0.05)
    assert leak == 0.0
    assert cov > 0
