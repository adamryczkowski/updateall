"""Tests for data preprocessing - Dwarf tests with synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stats.modeling.preprocessing import (
    DataPreprocessor,
    FillStrategy,
    PreprocessingConfig,
    ScalingMethod,
)
from stats.modeling.validation import validate_training_data


class TestDataPreprocessor:
    """Tests for DataPreprocessor using synthetic data."""

    def test_prepare_training_data_basic(self, synthetic_data: pd.DataFrame) -> None:
        """Test basic data preparation with synthetic data."""
        preprocessor = DataPreprocessor()

        target_series, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert target_series is not None
        assert len(target_series) > 0
        assert covariate_series is not None

    def test_outlier_removal(self, data_with_outliers: pd.DataFrame) -> None:
        """Test that outliers are correctly removed."""
        preprocessor = DataPreprocessor(PreprocessingConfig(outlier_threshold=3.0))

        target_series, _ = preprocessor.prepare_training_data(
            data_with_outliers,
            "wall_clock_seconds",
        )

        # Outliers should be removed, so we have fewer samples
        assert len(target_series) < len(data_with_outliers)

    def test_log_transform_reduces_range(self, synthetic_data: pd.DataFrame) -> None:
        """Test that log transformation reduces value range."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=True, scaling_method=ScalingMethod.NONE)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        values = target_series.values()
        # Log of ~60 is ~4.1, so max should be much smaller than original
        assert np.max(values) < 10

    def test_inverse_transform_recovers_scale(self, synthetic_data: pd.DataFrame) -> None:
        """Test that inverse transformation recovers original scale."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=True, scaling_method=ScalingMethod.MINMAX)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        original = preprocessor.inverse_transform_target(target_series)

        # Should be back to original scale (seconds range)
        original_values = original.values()
        assert np.mean(original_values) > 10

    def test_insufficient_data_raises(self, minimal_synthetic_data: pd.DataFrame) -> None:
        """Test that insufficient data raises ValueError."""
        preprocessor = DataPreprocessor(PreprocessingConfig(min_samples=10))

        with pytest.raises(ValueError, match="Insufficient data"):
            preprocessor.prepare_training_data(
                minimal_synthetic_data,
                "wall_clock_seconds",
            )

    def test_derived_features_computed(self, synthetic_data: pd.DataFrame) -> None:
        """Test that derived features are computed correctly."""
        preprocessor = DataPreprocessor()

        _, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Should have time_since_last_run, day_of_week, hour_of_day, is_weekend
        assert covariate_series is not None
        assert covariate_series.n_components >= 4

    def test_handles_noisy_data(self, noisy_synthetic_data: pd.DataFrame) -> None:
        """Test preprocessing handles noisy data gracefully."""
        preprocessor = DataPreprocessor()

        target_series, _ = preprocessor.prepare_training_data(
            noisy_synthetic_data,
            "wall_clock_seconds",
        )

        # Should still produce valid output
        assert target_series is not None
        assert len(target_series) > 0

    def test_missing_target_column_raises(self, synthetic_data: pd.DataFrame) -> None:
        """Test that missing target column raises ValueError."""
        preprocessor = DataPreprocessor()

        with pytest.raises(ValueError, match="Target column"):
            preprocessor.prepare_training_data(
                synthetic_data,
                "nonexistent_column",
            )

    def test_missing_timestamp_column_raises(self) -> None:
        """Test that missing timestamp column raises ValueError."""
        df = pd.DataFrame({"value": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]})
        preprocessor = DataPreprocessor()

        with pytest.raises(ValueError, match="No timestamp column"):
            preprocessor.prepare_training_data(df, "value")

    def test_fill_strategy_forward(self, data_with_missing_values: pd.DataFrame) -> None:
        """Test forward fill strategy for missing values."""
        preprocessor = DataPreprocessor(PreprocessingConfig(fill_strategy=FillStrategy.FORWARD))

        target_series, _ = preprocessor.prepare_training_data(
            data_with_missing_values,
            "wall_clock_seconds",
        )

        # Should have filled missing values
        assert target_series is not None
        assert len(target_series) > 0

    def test_fill_strategy_mean(self, data_with_missing_values: pd.DataFrame) -> None:
        """Test mean fill strategy for missing values."""
        preprocessor = DataPreprocessor(PreprocessingConfig(fill_strategy=FillStrategy.MEAN))

        target_series, _ = preprocessor.prepare_training_data(
            data_with_missing_values,
            "wall_clock_seconds",
        )

        assert target_series is not None
        assert len(target_series) > 0

    def test_scaling_minmax(self, synthetic_data: pd.DataFrame) -> None:
        """Test MinMax scaling produces values in [0, 1] range."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=False, scaling_method=ScalingMethod.MINMAX)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        values = target_series.values()
        # Use np.isclose for floating point comparison to avoid precision issues
        assert np.min(values) >= 0.0 or np.isclose(np.min(values), 0.0)
        assert np.max(values) <= 1.0 or np.isclose(np.max(values), 1.0)

    def test_scaling_standard(self, synthetic_data: pd.DataFrame) -> None:
        """Test Standard scaling produces approximately zero mean."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=False, scaling_method=ScalingMethod.STANDARD)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        values = target_series.values()
        # Mean should be approximately 0
        assert abs(np.mean(values)) < 0.1

    def test_no_scaling(self, synthetic_data: pd.DataFrame) -> None:
        """Test that no scaling preserves original values."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=False, scaling_method=ScalingMethod.NONE)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        values = target_series.values()
        # Values should be in the original range (around 60 seconds)
        assert np.mean(values) > 10

    def test_inverse_transform_without_preprocessing_raises(self) -> None:
        """Test that inverse transform without preprocessing raises error."""
        from darts import TimeSeries

        preprocessor = DataPreprocessor()
        dummy_series = TimeSeries.from_values(np.array([1, 2, 3]))

        with pytest.raises(ValueError, match="No preprocessing state"):
            preprocessor.inverse_transform_target(dummy_series)


class TestDataValidation:
    """Tests for data validation with synthetic data."""

    def test_valid_data_passes(self, synthetic_data: pd.DataFrame) -> None:
        """Test that valid synthetic data passes validation."""
        report = validate_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert report.is_valid
        assert len(report.issues) == 0

    def test_insufficient_samples_detected(self, minimal_synthetic_data: pd.DataFrame) -> None:
        """Test detection of insufficient samples."""
        report = validate_training_data(
            minimal_synthetic_data,
            "wall_clock_seconds",
            min_samples=10,
        )

        assert not report.is_valid
        assert any("Insufficient" in issue for issue in report.issues)

    def test_missing_target_detected(self, data_with_missing_values: pd.DataFrame) -> None:
        """Test detection of missing target values."""
        report = validate_training_data(
            data_with_missing_values,
            "wall_clock_seconds",
        )

        assert report.missing_values.get("wall_clock_seconds", 0) > 0

    def test_outliers_counted(self, data_with_outliers: pd.DataFrame) -> None:
        """Test that outliers are counted correctly."""
        report = validate_training_data(
            data_with_outliers,
            "wall_clock_seconds",
        )

        assert report.outlier_count >= 2

    def test_missing_target_column(self, synthetic_data: pd.DataFrame) -> None:
        """Test validation with missing target column."""
        report = validate_training_data(
            synthetic_data,
            "nonexistent_column",
        )

        assert not report.is_valid
        assert any("not found" in issue for issue in report.issues)

    def test_date_range_calculated(self, synthetic_data: pd.DataFrame) -> None:
        """Test that date range is calculated correctly."""
        report = validate_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # With 100 samples over ~150 days, date range should be > 100 days
        assert report.date_range_days > 50

    def test_sample_count_reported(self, synthetic_data: pd.DataFrame) -> None:
        """Test that sample count is reported correctly."""
        report = validate_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert report.sample_count == len(synthetic_data)

    def test_negative_values_detected(self) -> None:
        """Test detection of negative values in target column."""
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=20, freq="D"),
                "wall_clock_seconds": list(range(-5, 15)),
            }
        )

        report = validate_training_data(df, "wall_clock_seconds")

        assert not report.is_valid
        assert any("negative" in issue for issue in report.issues)

    def test_high_missing_rate_flagged(self) -> None:
        """Test that high missing rate is flagged as issue."""
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=20, freq="D"),
                "wall_clock_seconds": [1.0] * 5 + [np.nan] * 15,
            }
        )

        report = validate_training_data(df, "wall_clock_seconds")

        # 75% missing should be flagged as an issue
        assert not report.is_valid
        assert any("missing" in issue.lower() for issue in report.issues)
