"""Statistical modeling module for time series forecasting.

This module provides data preprocessing, validation, and model training
utilities using the Darts library for time series forecasting with
calibrated confidence intervals via conformal prediction.
"""

from __future__ import annotations

from stats.modeling.conformal import (
    ConformalConfig,
    ConformalMethod,
    ConformalPrediction,
    ConformalPredictor,
    compute_coverage,
    compute_interval_score,
)
from stats.modeling.multi_target import (
    TARGET_COLUMNS,
    MultiTargetModelManager,
    MultiTargetTrainingResult,
    PluginPrediction,
)
from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.trainer import (
    ModelTrainer,
    ModelType,
    PredictionResult,
    TrainingConfig,
    TrainingResult,
)
from stats.modeling.validation import DataQualityReport, validate_training_data

__all__ = [
    "TARGET_COLUMNS",
    "ConformalConfig",
    "ConformalMethod",
    "ConformalPrediction",
    "ConformalPredictor",
    "DataPreprocessor",
    "DataQualityReport",
    "ModelTrainer",
    "ModelType",
    "MultiTargetModelManager",
    "MultiTargetTrainingResult",
    "PluginPrediction",
    "PredictionResult",
    "PreprocessingConfig",
    "TrainingConfig",
    "TrainingResult",
    "compute_coverage",
    "compute_interval_score",
    "validate_training_data",
]
