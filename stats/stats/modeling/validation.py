"""Data quality validation for modeling.

This module provides validation utilities to check data quality
before training time series models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class DataQualityReport:
    """Report on data quality issues.

    Attributes:
        is_valid: Whether the data passes all validation checks.
        sample_count: Number of samples in the dataset.
        issues: List of validation issues found.
        warnings: List of non-critical warnings.
        missing_values: Dictionary mapping column names to missing value counts.
        outlier_count: Number of outliers detected in target column.
        date_range_days: Number of days spanned by the data.
    """

    is_valid: bool
    sample_count: int
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_values: dict[str, int] = field(default_factory=dict)
    outlier_count: int = 0
    date_range_days: int = 0


def validate_training_data(
    df: pd.DataFrame,
    target_column: str,
    min_samples: int = 10,
    outlier_threshold: float = 3.0,
) -> DataQualityReport:
    """Validate data quality for model training.

    Performs comprehensive validation checks on the training data:
    - Sufficient sample count
    - Missing values in target and feature columns
    - Outlier detection using z-score
    - Timestamp column presence and validity
    - Data range coverage

    Args:
        df: DataFrame containing training data.
        target_column: Name of the target column to validate.
        min_samples: Minimum number of samples required (default: 10).
        outlier_threshold: Z-score threshold for outlier detection (default: 3.0).

    Returns:
        DataQualityReport with validation results.

    Example:
        >>> report = validate_training_data(df, "wall_clock_seconds")
        >>> if not report.is_valid:
        ...     print(f"Issues: {report.issues}")
    """
    issues: list[str] = []
    warnings: list[str] = []
    missing_values: dict[str, int] = {}

    # Check sample count
    sample_count = len(df)
    if sample_count < min_samples:
        issues.append(f"Insufficient samples: {sample_count} < {min_samples} required")

    # Check target column exists
    if target_column not in df.columns:
        issues.append(f"Target column '{target_column}' not found in DataFrame")
        return DataQualityReport(
            is_valid=False,
            sample_count=sample_count,
            issues=issues,
            warnings=warnings,
            missing_values=missing_values,
        )

    # Check for missing values in all columns
    for col in df.columns:
        null_count = df[col].isna().sum()
        if null_count > 0:
            missing_values[col] = int(null_count)
            if col == target_column:
                missing_pct = null_count / sample_count * 100
                if missing_pct > 50:
                    issues.append(f"Target column has {missing_pct:.1f}% missing values")
                elif missing_pct > 10:
                    warnings.append(f"Target column has {missing_pct:.1f}% missing values")

    # Check for timestamp column
    timestamp_col = None
    for col in ["timestamp", "start_time", "time", "date"]:
        if col in df.columns:
            timestamp_col = col
            break

    date_range_days = 0
    if timestamp_col is None:
        warnings.append("No timestamp column found (expected: timestamp, start_time, time, date)")
    else:
        # Calculate date range
        try:
            timestamps = df[timestamp_col].dropna()
            if len(timestamps) > 0:
                min_time = timestamps.min()
                max_time = timestamps.max()
                date_range = max_time - min_time
                date_range_days = int(date_range.days) if hasattr(date_range, "days") else 0
        except (TypeError, AttributeError):
            warnings.append(f"Could not parse timestamp column '{timestamp_col}'")

    # Detect outliers in target column
    outlier_count = 0
    target_values = df[target_column].dropna()
    if len(target_values) > 0:
        mean = target_values.mean()
        std = target_values.std()
        if std > 0:
            z_scores = np.abs((target_values - mean) / std)
            outlier_count = int((z_scores > outlier_threshold).sum())
            if outlier_count > sample_count * 0.1:
                warnings.append(
                    f"High outlier count: {outlier_count} ({outlier_count / sample_count * 100:.1f}%)"
                )

    # Check for zero or negative values in target (if it should be positive)
    if target_column in [
        "wall_clock_seconds",
        "cpu_user_seconds",
        "memory_peak_bytes",
        "download_size_bytes",
    ]:
        negative_count = (target_values < 0).sum()
        if negative_count > 0:
            issues.append(f"Target column has {negative_count} negative values")

    is_valid = len(issues) == 0

    return DataQualityReport(
        is_valid=is_valid,
        sample_count=sample_count,
        issues=issues,
        warnings=warnings,
        missing_values=missing_values,
        outlier_count=outlier_count,
        date_range_days=date_range_days,
    )
