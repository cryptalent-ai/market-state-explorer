"""Baseline captured from main 2e9728d before visual implementation.

Source hashes freeze mathematics AND source orchestration. Numeric JSON baseline
uses 15 decimals, hence 1e-13 tolerance for cross-platform float serialization.
Presentation before/after comparisons are exact (no tolerance).
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import zlib

import numpy as np
import pandas as pd
import pytest

from src.config import ModelConfig
from src.data_io import prepare_market_data
from src.features import build_derived_features
from src.state_views import compute_recent_state_summary, compute_region_occupancy, compute_state_rarity, prepare_state_frame
from src.validation import calculate_forward_outcomes, non_overlapping_indices
from tests.conftest import fixed_market_frame

ROOT = Path(__file__).parents[1]
BASELINE = json.loads((ROOT / "tests/fixtures/v121_baseline.json").read_text("utf-8"))
VALUES = json.loads(zlib.decompress(base64.b64decode(BASELINE["zlib_base64"])))


@pytest.mark.parametrize("path,expected", BASELINE["source_sha256"].items())
def test_frozen_model_and_source_files(path, expected):
    assert hashlib.sha256((ROOT/path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected


def assert_baseline(actual, baseline):
    expected = pd.DataFrame(baseline["data"], columns=baseline["columns"], index=baseline["index"])
    for column in expected:
        if pd.api.types.is_numeric_dtype(actual[column]):
            np.testing.assert_allclose(actual[column].astype(float), pd.to_numeric(expected[column], errors="coerce"), rtol=1e-13, atol=1e-13, equal_nan=True)
        else:
            assert actual[column].astype(object).where(actual[column].notna(), None).tolist() == expected[column].tolist()


def test_v121_derived_feature_baseline(derived):
    assert_baseline(derived[VALUES["features"]["columns"]], VALUES["features"])


@pytest.mark.parametrize("horizon", [5, 10, 20])
def test_v121_forward_outcomes_baseline(derived, horizon):
    assert_baseline(calculate_forward_outcomes(derived, horizon), VALUES["outcomes"][str(horizon)])


def test_visual_transforms_preserve_features_and_forward_outcomes_exactly(derived):
    original = derived.copy(deep=True)
    outcomes = calculate_forward_outcomes(derived, 20)
    prepare_state_frame(derived)
    compute_region_occupancy(derived)
    compute_state_rarity(derived)
    compute_recent_state_summary(derived)
    pd.testing.assert_frame_equal(derived, original, check_exact=True)
    pd.testing.assert_frame_equal(outcomes, calculate_forward_outcomes(derived, 20), check_exact=True)


def test_no_lookahead_feature_prefix_is_exact():
    raw = fixed_market_frame()
    prefix = build_derived_features(prepare_market_data(raw.iloc[:320]).frame)
    changed_future = raw.copy()
    changed_future.loc[320:, "volume"] *= 10000
    changed_future.loc[320:, "delta"] *= -100
    changed_future.loc[320:, "oi"] *= 3
    full = build_derived_features(prepare_market_data(changed_future).frame)
    pd.testing.assert_frame_equal(prefix, full.iloc[:320], check_exact=True)


def test_no_lookahead_visual_prefix(derived):
    as_of = derived.timestamp.iloc[380]
    prefix = derived[derived.timestamp.le(as_of)].copy()
    original = compute_recent_state_summary(prefix)
    changed = derived.copy()
    changed.loc[381:, "effort_score"] = 100000
    assert original == compute_recent_state_summary(changed[changed.timestamp.le(as_of)])


def test_normalization_reference_excludes_current_value():
    from src.normalization import _rolling_reference
    values = pd.Series([1., 2., 5., 3., 4., 6.])
    changed = values.copy()
    changed.iloc[-1] = 9999
    median, scale = _rolling_reference(values, window=5, min_periods=5)
    altered_median, altered_scale = _rolling_reference(changed, window=5, min_periods=5)
    assert median.iloc[-1] == 3
    pd.testing.assert_series_equal(median, altered_median, check_exact=True)
    pd.testing.assert_series_equal(scale, altered_scale, check_exact=True)


def test_forward_outcomes_never_cross_segments(derived):
    frame = derived.copy()
    frame.loc[210:, "segment_id"] = 1
    outcome = calculate_forward_outcomes(frame, 5)
    assert outcome.loc[205:209].isna().all().all()
    assert outcome.tail(5).isna().all().all()
    selected = non_overlapping_indices(frame, frame.index, 5)
    for _, group in frame.loc[selected].groupby("segment_id"):
        assert all(np.diff(group.index) > 5)


def test_upload_pipeline_unchanged(derived):
    from src.web_app import calculate_uploaded
    config = ModelConfig()
    uploaded, quality = calculate_uploaded(fixed_market_frame().to_csv(index=False).encode(), config)
    pd.testing.assert_frame_equal(uploaded, derived, check_exact=False, rtol=1e-13, atol=1e-13)
    assert quality.usable_state_rows > 0
