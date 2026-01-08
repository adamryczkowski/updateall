"""Statistical modeling module for time series forecasting.

This module provides data preprocessing, validation, and model training
utilities using the Darts library for time series forecasting with
calibrated confidence intervals via conformal prediction.
"""

from __future__ import annotations

from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.validation import DataQualityReport, validate_training_data

__all__ = [
    "DataPreprocessor",
    "DataQualityReport",
    "PreprocessingConfig",
    "validate_training_data",
]
