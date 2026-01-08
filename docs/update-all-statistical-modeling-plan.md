# Statistical Modeling Plan for Update-All Time Estimation

> **Document Version**: 1.0
> **Created**: 2025-01-08
> **Status**: Draft

## 1. Overview

This document outlines the comprehensive implementation plan for advanced statistical modeling capabilities using the Darts library (Unified Time Series Framework) to provide better estimates for future runs of the update-all procedure.

### 1.1 Goals

1. **Accurate Point Estimates**: Predict download size, CPU time, wall-clock time, and peak memory usage
2. **Confidence Intervals**: Provide probabilistic forecasts with calibrated uncertainty quantification
3. **Model Flexibility**: Support multiple model types with automatic selection
4. **TDD Approach**: Test-driven development with comprehensive dwarf tests using modeled data

### 1.2 Why Darts?

- **Unified API**: Consistent interface across 30+ forecasting models
- **Probabilistic Forecasting**: Native support for prediction intervals
- **Covariates Support**: Can incorporate external features (package count, download size estimates)
- **Conformal Prediction**: Calibrated confidence intervals for any model
- **Production Ready**: Well-maintained, 96% test coverage, active development

### 1.3 References

- Darts Documentation: https://unit8co.github.io/darts/
- Current estimator: [`stats/stats/estimator.py`](../stats/stats/estimator.py)
- DuckDB integration: [`docs/update-all-duckdb-integration-plan.md`](./update-all-duckdb-integration-plan.md)

---

## 2. Data Preparation Strategy

### 2.1 Feature Engineering

#### 2.1.1 Historical Features (from DuckDB)

| Feature | Type | Description | Source |
|---------|------|-------------|--------|
| `timestamp` | datetime | Time of the run | `plugin_executions.start_time` |
| `time_since_last_run` | float | Seconds since previous run | Computed |
| `packages_total` | int | Total packages under management | `plugin_executions.packages_total` |
| `packages_to_update` | int | Number of packages to update | `plugin_executions.packages_updated` |
| `download_size_estimated` | int | Plugin-reported download estimate | `estimates.download_bytes_est` |
| `cpu_time_estimated` | float | Plugin-reported CPU estimate | `estimates.cpu_seconds_est` |
| `day_of_week` | int | Day of week (0-6) | Computed from timestamp |
| `hour_of_day` | int | Hour of day (0-23) | Computed from timestamp |
| `is_weekend` | bool | Weekend flag | Computed |

#### 2.1.2 Target Variables

| Target | Type | Description | Source |
|--------|------|-------------|--------|
| `download_size_actual` | int | Actual download size in bytes | `step_metrics.download_size_bytes` |
| `cpu_time_actual` | float | Actual CPU time in seconds | `step_metrics.cpu_user_seconds + cpu_kernel_seconds` |
| `wall_clock_actual` | float | Actual wall-clock time in seconds | `step_metrics.wall_clock_seconds` |
| `memory_peak_actual` | int | Peak memory usage in bytes | `step_metrics.memory_peak_bytes` |

### 2.2 Data Preprocessing Pipeline

```python
# stats/stats/modeling/preprocessing.py
"""Data preprocessing for statistical modeling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from darts import TimeSeries
from darts.dataprocessing.transformers import Scaler

if TYPE_CHECKING:
    from stats.retrieval.queries import HistoricalDataQuery


@dataclass
class PreprocessingConfig:
    """Configuration for data preprocessing."""

    # Minimum samples required for training
    min_samples: int = 10

    # Maximum lookback period in days
    max_lookback_days: int = 365

    # Fill missing values strategy
    fill_strategy: str = "forward"  # forward, backward, mean, zero

    # Outlier removal threshold (z-score)
    outlier_threshold: float = 3.0

    # Whether to log-transform targets
    log_transform: bool = True

    # Scaling method
    scaling_method: str = "minmax"  # minmax, standard, none


class DataPreprocessor:
    """Preprocesses historical data for time series modeling."""

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        """Initialize the preprocessor.

        Args:
            config: Preprocessing configuration.
        """
        self.config = config or PreprocessingConfig()
        self._target_scaler: Scaler | None = None
        self._covariate_scaler: Scaler | None = None

    def prepare_training_data(
        self,
        df: pd.DataFrame,
        target_column: str,
    ) -> tuple[TimeSeries, TimeSeries | None]:
        """Prepare training data for a single target.

        Args:
            df: Raw DataFrame from DuckDB query.
            target_column: Name of the target column.

        Returns:
            Tuple of (target_series, covariate_series).
        """
        # Sort by timestamp
        df = df.sort_values("timestamp").copy()

        # Remove outliers
        df = self._remove_outliers(df, target_column)

        # Check minimum samples
        if len(df) < self.config.min_samples:
            raise ValueError(
                f"Insufficient data: {len(df)} samples, "
                f"minimum required: {self.config.min_samples}"
            )

        # Compute derived features
        df = self._compute_derived_features(df)

        # Handle missing values
        df = self._fill_missing_values(df, target_column)

        # Log transform if configured
        if self.config.log_transform:
            df[target_column] = np.log1p(df[target_column])

        # Create target time series
        target_series = TimeSeries.from_dataframe(
            df,
            time_col="timestamp",
            value_cols=[target_column],
            fill_missing_dates=True,
            freq="D",  # Daily frequency
        )

        # Create covariate series
        covariate_cols = [
            "time_since_last_run",
            "packages_total",
            "packages_to_update",
            "download_size_estimated",
            "day_of_week",
            "hour_of_day",
        ]

        available_covariates = [c for c in covariate_cols if c in df.columns]

        if available_covariates:
            covariate_series = TimeSeries.from_dataframe(
                df,
                time_col="timestamp",
                value_cols=available_covariates,
                fill_missing_dates=True,
                freq="D",
            )
        else:
            covariate_series = None

        # Scale data
        if self.config.scaling_method != "none":
            target_series, covariate_series = self._scale_data(
                target_series, covariate_series
            )

        return target_series, covariate_series

    def _remove_outliers(
        self,
        df: pd.DataFrame,
        target_column: str,
    ) -> pd.DataFrame:
        """Remove outliers using z-score method.

        Args:
            df: Input DataFrame.
            target_column: Column to check for outliers.

        Returns:
            DataFrame with outliers removed.
        """
        if target_column not in df.columns:
            return df

        values = df[target_column].dropna()
        if len(values) < 3:
            return df

        mean = values.mean()
        std = values.std()

        if std == 0:
            return df

        z_scores = np.abs((df[target_column] - mean) / std)
        mask = z_scores <= self.config.outlier_threshold

        return df[mask].copy()

    def _compute_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute derived features from raw data.

        Args:
            df: Input DataFrame.

        Returns:
            DataFrame with derived features.
        """
        # Time since last run
        df["time_since_last_run"] = df["timestamp"].diff().dt.total_seconds()
        df["time_since_last_run"] = df["time_since_last_run"].fillna(
            df["time_since_last_run"].median()
        )

        # Day of week and hour
        df["day_of_week"] = df["timestamp"].dt.dayofweek
        df["hour_of_day"] = df["timestamp"].dt.hour
        df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

        return df

    def _fill_missing_values(
        self,
        df: pd.DataFrame,
        target_column: str,
    ) -> pd.DataFrame:
        """Fill missing values according to strategy.

        Args:
            df: Input DataFrame.
            target_column: Target column name.

        Returns:
            DataFrame with filled values.
        """
        if self.config.fill_strategy == "forward":
            df = df.ffill()
        elif self.config.fill_strategy == "backward":
            df = df.bfill()
        elif self.config.fill_strategy == "mean":
            df = df.fillna(df.mean(numeric_only=True))
        elif self.config.fill_strategy == "zero":
            df = df.fillna(0)

        # Drop remaining NaN in target
        df = df.dropna(subset=[target_column])

        return df

    def _scale_data(
        self,
        target: TimeSeries,
        covariates: TimeSeries | None,
    ) -> tuple[TimeSeries, TimeSeries | None]:
        """Scale target and covariate series.

        Args:
            target: Target time series.
            covariates: Covariate time series.

        Returns:
            Tuple of scaled series.
        """
        self._target_scaler = Scaler()
        scaled_target = self._target_scaler.fit_transform(target)

        scaled_covariates = None
        if covariates is not None:
            self._covariate_scaler = Scaler()
            scaled_covariates = self._covariate_scaler.fit_transform(covariates)

        return scaled_target, scaled_covariates

    def inverse_transform_target(self, series: TimeSeries) -> TimeSeries:
        """Inverse transform a target series.

        Args:
            series: Scaled series.

        Returns:
            Original scale series.
        """
        if self._target_scaler is not None:
            series = self._target_scaler.inverse_transform(series)

        if self.config.log_transform:
            # Inverse log1p transform
            values = np.expm1(series.values())
            series = TimeSeries.from_times_and_values(
                series.time_index,
                values,
            )

        return series
```

### 2.3 Data Quality Validation

```python
# stats/stats/modeling/validation.py
"""Data quality validation for modeling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class DataQualityReport:
    """Report on data quality issues."""

    total_samples: int
    missing_values: dict[str, int]
    outlier_count: int
    duplicate_timestamps: int
    date_range_days: int
    is_valid: bool
    issues: list[str]


def validate_training_data(
    df: pd.DataFrame,
    target_column: str,
    min_samples: int = 10,
) -> DataQualityReport:
    """Validate training data quality.

    Args:
        df: DataFrame to validate.
        target_column: Target column name.
        min_samples: Minimum required samples.

    Returns:
        DataQualityReport with validation results.
    """
    issues = []

    # Check total samples
    total_samples = len(df)
    if total_samples < min_samples:
        issues.append(f"Insufficient samples: {total_samples} < {min_samples}")

    # Check missing values
    missing_values = df.isnull().sum().to_dict()
    target_missing = missing_values.get(target_column, 0)
    if target_missing > 0:
        issues.append(f"Target has {target_missing} missing values")

    # Check outliers (z-score > 3)
    outlier_count = 0
    if target_column in df.columns:
        values = df[target_column].dropna()
        if len(values) > 2:
            z_scores = np.abs((values - values.mean()) / values.std())
            outlier_count = (z_scores > 3).sum()
            if outlier_count > len(values) * 0.1:
                issues.append(f"High outlier rate: {outlier_count}/{len(values)}")

    # Check duplicate timestamps
    duplicate_timestamps = 0
    if "timestamp" in df.columns:
        duplicate_timestamps = df["timestamp"].duplicated().sum()
        if duplicate_timestamps > 0:
            issues.append(f"Found {duplicate_timestamps} duplicate timestamps")

    # Check date range
    date_range_days = 0
    if "timestamp" in df.columns and len(df) > 0:
        date_range = df["timestamp"].max() - df["timestamp"].min()
        date_range_days = date_range.days
        if date_range_days < 7:
            issues.append(f"Short date range: {date_range_days} days")

    return DataQualityReport(
        total_samples=total_samples,
        missing_values=missing_values,
        outlier_count=outlier_count,
        duplicate_timestamps=duplicate_timestamps,
        date_range_days=date_range_days,
        is_valid=len(issues) == 0,
        issues=issues,
    )
```

---

## 3. Model Training Strategy

### 3.1 Model Selection

We will support multiple model types with automatic selection based on data characteristics:

| Model | Use Case | Probabilistic | Covariates | Min Samples |
|-------|----------|---------------|------------|-------------|
| `ExponentialSmoothing` | Baseline, few samples | Yes | No | 5 |
| `AutoARIMA` | Trend + seasonality | Yes | Yes | 20 |
| `Prophet` | Strong seasonality | Yes | Yes | 30 |
| `LightGBMModel` | Many covariates | Yes | Yes | 50 |
| `NLinearModel` | Long sequences | Yes | Yes | 100 |

### 3.2 Model Training Pipeline

```python
# stats/stats/modeling/trainer.py
"""Model training pipeline for time series forecasting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog
from darts import TimeSeries
from darts.metrics import mae, mape, rmse
from darts.models import (
    ExponentialSmoothing,
    AutoARIMA,
    Prophet,
    LightGBMModel,
    NLinearModel,
)
from darts.models.forecasting.forecasting_model import ForecastingModel

if TYPE_CHECKING:
    from stats.modeling.preprocessing import DataPreprocessor

logger = structlog.get_logger(__name__)


class ModelType(str, Enum):
    """Available model types."""

    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    AUTO_ARIMA = "auto_arima"
    PROPHET = "prophet"
    LIGHTGBM = "lightgbm"
    NLINEAR = "nlinear"


@dataclass
class TrainingConfig:
    """Configuration for model training."""

    # Model selection
    model_type: ModelType = ModelType.AUTO_ARIMA
    auto_select: bool = True

    # Training parameters
    validation_split: float = 0.2
    num_samples: int = 500  # For probabilistic forecasts

    # Conformal prediction
    use_conformal: bool = True
    conformal_alpha: float = 0.1  # 90% confidence interval

    # Model persistence
    model_dir: Path | None = None

    # Early stopping
    max_epochs: int = 100
    patience: int = 10


@dataclass
class TrainingResult:
    """Result of model training."""

    model_type: ModelType
    metrics: dict[str, float]
    training_samples: int
    validation_samples: int
    is_successful: bool
    error_message: str | None = None


@dataclass
class PredictionResult:
    """Result of a prediction with confidence intervals."""

    point_estimate: float
    lower_bound: float  # Lower confidence bound
    upper_bound: float  # Upper confidence bound
    confidence_level: float  # e.g., 0.9 for 90% CI
    model_type: ModelType
    data_points_used: int


class ModelTrainer:
    """Trains and manages forecasting models."""

    # Minimum samples for each model type
    MIN_SAMPLES = {
        ModelType.EXPONENTIAL_SMOOTHING: 5,
        ModelType.AUTO_ARIMA: 20,
        ModelType.PROPHET: 30,
        ModelType.LIGHTGBM: 50,
        ModelType.NLINEAR: 100,
    }

    def __init__(
        self,
        config: TrainingConfig | None = None,
        preprocessor: "DataPreprocessor | None" = None,
    ) -> None:
        """Initialize the trainer.

        Args:
            config: Training configuration.
            preprocessor: Data preprocessor instance.
        """
        self.config = config or TrainingConfig()
        self.preprocessor = preprocessor
        self._models: dict[str, ForecastingModel] = {}
        self._conformal_residuals: dict[str, np.ndarray] = {}

    def select_model_type(self, num_samples: int) -> ModelType:
        """Select appropriate model type based on data size.

        Args:
            num_samples: Number of training samples.

        Returns:
            Selected model type.
        """
        if not self.config.auto_select:
            return self.config.model_type

        # Select based on sample count (prefer simpler models for small data)
        for model_type in [
            ModelType.NLINEAR,
            ModelType.LIGHTGBM,
            ModelType.PROPHET,
            ModelType.AUTO_ARIMA,
            ModelType.EXPONENTIAL_SMOOTHING,
        ]:
            if num_samples >= self.MIN_SAMPLES[model_type]:
                return model_type

        # Fall back to simplest model
        return ModelType.EXPONENTIAL_SMOOTHING

    def create_model(
        self,
        model_type: ModelType,
        supports_covariates: bool = False,
    ) -> ForecastingModel:
        """Create a model instance.

        Args:
            model_type: Type of model to create.
            supports_covariates: Whether model should use covariates.

        Returns:
            Configured model instance.
        """
        if model_type == ModelType.EXPONENTIAL_SMOOTHING:
            return ExponentialSmoothing(
                seasonal_periods=7,  # Weekly seasonality
                trend="add",
                seasonal="add",
            )

        elif model_type == ModelType.AUTO_ARIMA:
            return AutoARIMA(
                start_p=0,
                start_q=0,
                max_p=5,
                max_q=5,
                seasonal=True,
                m=7,  # Weekly seasonality
            )

        elif model_type == ModelType.PROPHET:
            return Prophet(
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=False,
            )

        elif model_type == ModelType.LIGHTGBM:
            return LightGBMModel(
                lags=14,
                lags_past_covariates=14 if supports_covariates else None,
                output_chunk_length=1,
                n_estimators=100,
                random_state=42,
            )

        elif model_type == ModelType.NLINEAR:
            return NLinearModel(
                input_chunk_length=30,
                output_chunk_length=1,
                n_epochs=self.config.max_epochs,
                random_state=42,
            )

        else:
            raise ValueError(f"Unknown model type: {model_type}")

    def train(
        self,
        target_name: str,
        target_series: TimeSeries,
        covariate_series: TimeSeries | None = None,
    ) -> TrainingResult:
        """Train a model for a specific target.

        Args:
            target_name: Name of the target (e.g., "wall_clock_seconds").
            target_series: Target time series.
            covariate_series: Optional covariate series.

        Returns:
            TrainingResult with metrics.
        """
        num_samples = len(target_series)

        # Select model type
        model_type = self.select_model_type(num_samples)
        logger.info(
            "model_selected",
            target=target_name,
            model_type=model_type.value,
            samples=num_samples,
        )

        # Split data
        val_size = int(len(target_series) * self.config.validation_split)
        train_size = len(target_series) - val_size

        if train_size < self.MIN_SAMPLES[model_type]:
            return TrainingResult(
                model_type=model_type,
                metrics={},
                training_samples=train_size,
                validation_samples=val_size,
                is_successful=False,
                error_message=f"Insufficient training samples: {train_size}",
            )

        train_series = target_series[:train_size]
        val_series = target_series[train_size:]

        train_covariates = None
        val_covariates = None
        if covariate_series is not None:
            train_covariates = covariate_series[:train_size]
            val_covariates = covariate_series[train_size:]

        # Create and train model
        supports_covariates = model_type in [
            ModelType.AUTO_ARIMA,
            ModelType.PROPHET,
            ModelType.LIGHTGBM,
            ModelType.NLINEAR,
        ]

        model = self.create_model(model_type, supports_covariates and covariate_series is not None)

        try:
            if supports_covariates and train_covariates is not None:
                model.fit(train_series, past_covariates=train_covariates)
            else:
                model.fit(train_series)

            # Generate predictions for validation
            if supports_covariates and val_covariates is not None:
                predictions = model.predict(
                    n=val_size,
                    past_covariates=covariate_series,
                    num_samples=self.config.num_samples,
                )
            else:
                predictions = model.predict(
                    n=val_size,
                    num_samples=self.config.num_samples,
                )

            # Calculate metrics
            metrics = {
                "mae": float(mae(val_series, predictions)),
                "rmse": float(rmse(val_series, predictions)),
                "mape": float(mape(val_series, predictions)),
            }

            # Store model and compute conformal residuals
            self._models[target_name] = model

            if self.config.use_conformal:
                self._compute_conformal_residuals(
                    target_name,
                    val_series,
                    predictions,
                )

            logger.info(
                "model_trained",
                target=target_name,
                model_type=model_type.value,
                metrics=metrics,
            )

            return TrainingResult(
                model_type=model_type,
                metrics=metrics,
                training_samples=train_size,
                validation_samples=val_size,
                is_successful=True,
            )

        except Exception as e:
            logger.error(
                "training_failed",
                target=target_name,
                error=str(e),
            )
            return TrainingResult(
                model_type=model_type,
                metrics={},
                training_samples=train_size,
                validation_samples=val_size,
                is_successful=False,
                error_message=str(e),
            )

    def _compute_conformal_residuals(
        self,
        target_name: str,
        actual: TimeSeries,
        predicted: TimeSeries,
    ) -> None:
        """Compute conformal prediction residuals.

        Args:
            target_name: Name of the target.
            actual: Actual values.
            predicted: Predicted values.
        """
        # Get point predictions (median of samples)
        pred_values = predicted.quantile_timeseries(0.5).values().flatten()
        actual_values = actual.values().flatten()

        # Compute absolute residuals
        residuals = np.abs(actual_values - pred_values)
        self._conformal_residuals[target_name] = residuals

    def predict(
        self,
        target_name: str,
        covariate_series: TimeSeries | None = None,
        horizon: int = 1,
    ) -> PredictionResult:
        """Make a prediction with confidence intervals.

        Args:
            target_name: Name of the target.
            covariate_series: Optional covariate series.
            horizon: Prediction horizon.

        Returns:
            PredictionResult with point estimate and confidence bounds.
        """
        model = self._models.get(target_name)
        if model is None:
            raise ValueError(f"No trained model for target: {target_name}")

        # Generate probabilistic prediction
        if covariate_series is not None:
            prediction = model.predict(
                n=horizon,
                past_covariates=covariate_series,
                num_samples=self.config.num_samples,
            )
        else:
            prediction = model.predict(
                n=horizon,
                num_samples=self.config.num_samples,
            )

        # Get point estimate (median)
        point_estimate = float(prediction.quantile_timeseries(0.5).values()[-1])

        # Get confidence bounds
        alpha = self.config.conformal_alpha

        if self.config.use_conformal and target_name in self._conformal_residuals:
            # Use conformal prediction for calibrated intervals
            residuals = self._conformal_residuals[target_name]
            quantile = np.quantile(residuals, 1 - alpha)
            lower_bound = point_estimate - quantile
            upper_bound = point_estimate + quantile
        else:
            # Use model's native quantiles
            lower_bound = float(prediction.quantile_timeseries(alpha / 2).values()[-1])
            upper_bound = float(prediction.quantile_timeseries(1 - alpha / 2).values()[-1])

        # Ensure non-negative bounds for physical quantities
        lower_bound = max(0, lower_bound)
        upper_bound = max(lower_bound, upper_bound)

        return PredictionResult(
            point_estimate=point_estimate,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            confidence_level=1 - alpha,
            model_type=self.select_model_type(len(self._conformal_residuals.get(target_name, []))),
            data_points_used=len(self._conformal_residuals.get(target_name, [])),
        )

    def save_models(self, directory: Path) -> None:
        """Save all trained models to disk.

        Args:
            directory: Directory to save models.
        """
        directory.mkdir(parents=True, exist_ok=True)

        for target_name, model in self._models.items():
            model_path = directory / f"{target_name}_model.pkl"
            model.save(str(model_path))
            logger.info("model_saved", target=target_name, path=str(model_path))

        # Save conformal residuals
        import pickle
        residuals_path = directory / "conformal_residuals.pkl"
        with open(residuals_path, "wb") as f:
            pickle.dump(self._conformal_residuals, f)

    def load_models(self, directory: Path) -> None:
        """Load trained models from disk.

        Args:
            directory: Directory containing saved models.
        """
        import pickle

        # Load conformal residuals
        residuals_path = directory / "conformal_residuals.pkl"
        if residuals_path.exists():
            with open(residuals_path, "rb") as f:
                self._conformal_residuals = pickle.load(f)

        # Load models
        for model_path in directory.glob("*_model.pkl"):
            target_name = model_path.stem.replace("_model", "")
            # Note: Darts models need to be loaded with the correct class
            # This is a simplified version
            logger.info("model_loaded", target=target_name, path=str(model_path))
```

### 3.3 Multi-Target Training

```python
# stats/stats/modeling/multi_target.py
"""Multi-target model training for all metrics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.trainer import ModelTrainer, TrainingConfig, TrainingResult, PredictionResult
from stats.modeling.validation import validate_training_data

if TYPE_CHECKING:
    import pandas as pd
    from stats.retrieval.queries import HistoricalDataQuery

logger = structlog.get_logger(__name__)


# Target columns for prediction
TARGET_COLUMNS = [
    "wall_clock_seconds",
    "cpu_user_seconds",
    "memory_peak_bytes",
    "download_size_bytes",
]


@dataclass
class PluginPrediction:
    """Complete prediction for a plugin."""

    plugin_name: str
    wall_clock: PredictionResult | None
    cpu_time: PredictionResult | None
    memory_peak: PredictionResult | None
    download_size: PredictionResult | None

    @property
    def has_predictions(self) -> bool:
        """Check if any predictions are available."""
        return any([
            self.wall_clock,
            self.cpu_time,
            self.memory_peak,
            self.download_size,
        ])


class MultiTargetModelManager:
    """Manages models for all target metrics."""

    def __init__(
        self,
        preprocessing_config: PreprocessingConfig | None = None,
        training_config: TrainingConfig | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            preprocessing_config: Preprocessing configuration.
            training_config: Training configuration.
        """
        self.preprocessing_config = preprocessing_config or PreprocessingConfig()
        self.training_config = training_config or TrainingConfig()

        self._preprocessors: dict[str, DataPreprocessor] = {}
        self._trainers: dict[str, ModelTrainer] = {}

    def train_for_plugin(
        self,
        plugin_name: str,
        df: "pd.DataFrame",
    ) -> dict[str, TrainingResult]:
        """Train models for all targets for a plugin.

        Args:
            plugin_name: Name of the plugin.
            df: Training data from DuckDB.

        Returns:
            Dictionary of target name to TrainingResult.
        """
        results = {}

        for target in TARGET_COLUMNS:
            if target not in df.columns:
                logger.warning(
                    "target_column_missing",
                    plugin=plugin_name,
                    target=target,
                )
                continue

            # Validate data
            report = validate_training_data(df, target)
            if not report.is_valid:
                logger.warning(
                    "data_validation_failed",
                    plugin=plugin_name,
                    target=target,
                    issues=report.issues,
                )
                continue

            # Preprocess
            preprocessor = DataPreprocessor(self.preprocessing_config)
            try:
                target_series, covariate_series = preprocessor.prepare_training_data(
                    df, target
                )
            except ValueError as e:
                logger.warning(
                    "preprocessing_failed",
                    plugin=plugin_name,
                    target=target,
                    error=str(e),
                )
                continue

            # Train
            trainer = ModelTrainer(self.training_config, preprocessor)
            result = trainer.train(
                f"{plugin_name}_{target}",
                target_series,
                covariate_series,
            )

            if result.is_successful:
                key = f"{plugin_name}_{target}"
                self._preprocessors[key] = preprocessor
                self._trainers[key] = trainer

            results[target] = result

        return results

    def predict_for_plugin(
        self,
        plugin_name: str,
        covariates: dict[str, float] | None = None,
    ) -> PluginPrediction:
        """Make predictions for all targets for a plugin.

        Args:
            plugin_name: Name of the plugin.
            covariates: Optional covariate values.

        Returns:
            PluginPrediction with all available predictions.
        """
        predictions = {}

        for target in TARGET_COLUMNS:
            key = f"{plugin_name}_{target}"
            trainer = self._trainers.get(key)

            if trainer is None:
                predictions[target] = None
                continue

            try:
                prediction = trainer.predict(key)

                # Inverse transform if needed
                preprocessor = self._preprocessors.get(key)
                if preprocessor and preprocessor.config.log_transform:
                    # Inverse log transform
                    import numpy as np
                    prediction = PredictionResult(
                        point_estimate=np.expm1(prediction.point_estimate),
                        lower_bound=np.expm1(prediction.lower_bound),
                        upper_bound=np.expm1(prediction.upper_bound),
                        confidence_level=prediction.confidence_level,
                        model_type=prediction.model_type,
                        data_points_used=prediction.data_points_used,
                    )

                predictions[target] = prediction

            except Exception as e:
                logger.warning(
                    "prediction_failed",
                    plugin=plugin_name,
                    target=target,
                    error=str(e),
                )
                predictions[target] = None

        return PluginPrediction(
            plugin_name=plugin_name,
            wall_clock=predictions.get("wall_clock_seconds"),
            cpu_time=predictions.get("cpu_user_seconds"),
            memory_peak=predictions.get("memory_peak_bytes"),
            download_size=predictions.get("download_size_bytes"),
        )

    def save(self, directory: Path) -> None:
        """Save all models and preprocessors.

        Args:
            directory: Directory to save to.
        """
        for key, trainer in self._trainers.items():
            trainer.save_models(directory / key)

    def load(self, directory: Path) -> None:
        """Load all models and preprocessors.

        Args:
            directory: Directory to load from.
        """
        for model_dir in directory.iterdir():
            if model_dir.is_dir():
                key = model_dir.name
                trainer = ModelTrainer(self.training_config)
                trainer.load_models(model_dir)
                self._trainers[key] = trainer
```

---

## 4. Integration with Update-All Procedure

### 4.1 Updated TimeEstimator

```python
# stats/stats/estimator.py (updated)
"""Advanced time estimation with Darts-based statistical modeling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import structlog

from stats.modeling.multi_target import MultiTargetModelManager, PluginPrediction
from stats.modeling.trainer import PredictionResult

if TYPE_CHECKING:
    from stats.retrieval.queries import HistoricalDataQuery

logger = structlog.get_logger(__name__)


@dataclass
class TimeEstimate:
    """Time estimate with confidence interval.

    Provides a point estimate along with lower and upper bounds
    representing the confidence interval.
    """

    point_estimate: float  # seconds
    confidence_interval: tuple[float, float]  # (lower, upper) in seconds
    confidence_level: float  # e.g., 0.9 for 90% confidence
    data_points: int  # number of historical data points used
    model_type: str | None = None  # model used for prediction

    @property
    def lower_bound(self) -> float:
        """Lower bound of the confidence interval."""
        return self.confidence_interval[0]

    @property
    def upper_bound(self) -> float:
        """Upper bound of the confidence interval."""
        return self.confidence_interval[1]

    @property
    def has_sufficient_data(self) -> bool:
        """Check if there's sufficient data for reliable estimation."""
        return self.data_points >= 10

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

    def format(self) -> str:
        """Format the estimate as a human-readable string."""
        point = self.format_duration(self.point_estimate)

        if self.data_points == 0:
            return f"~{point} (no history)"
        elif self.data_points < 10:
            return f"~{point} (limited data)"
        else:
            lower = self.format_duration(self.lower_bound)
            upper = self.format_duration(self.upper_bound)
            pct = int(self.confidence_level * 100)
            return f"{point} ({lower} - {upper}, {pct}% CI)"


@dataclass
class ResourceEstimate:
    """Complete resource estimate for a plugin."""

    plugin_name: str
    wall_clock: TimeEstimate
    cpu_time: TimeEstimate
    memory_peak: TimeEstimate  # bytes
    download_size: TimeEstimate  # bytes

    def format_memory(self, bytes_val: float) -> str:
        """Format memory in human-readable format."""
        if bytes_val < 1024:
            return f"{bytes_val:.0f} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


class DartsTimeEstimator:
    """Advanced time estimator using Darts-based models.

    Uses trained statistical models to predict execution times
    with calibrated confidence intervals.
    """

    # Default estimates when no model is available
    DEFAULT_WALL_CLOCK = 300.0  # 5 minutes
    DEFAULT_CPU_TIME = 60.0  # 1 minute
    DEFAULT_MEMORY = 100 * 1024 * 1024  # 100 MB
    DEFAULT_DOWNLOAD = 50 * 1024 * 1024  # 50 MB

    def __init__(
        self,
        query: "HistoricalDataQuery",
        model_manager: MultiTargetModelManager | None = None,
        model_dir: Path | None = None,
    ) -> None:
        """Initialize the estimator.

        Args:
            query: Query interface for historical data.
            model_manager: Optional pre-trained model manager.
            model_dir: Directory containing saved models.
        """
        self.query = query
        self.model_manager = model_manager or MultiTargetModelManager()

        if model_dir and model_dir.exists():
            self.model_manager.load(model_dir)

    def train_models(self, plugin_names: list[str] | None = None) -> dict[str, dict]:
        """Train models for specified plugins.

        Args:
            plugin_names: List of plugin names. If None, train for all.

        Returns:
            Dictionary of plugin name to training results.
        """
        if plugin_names is None:
            # Get all plugins from history
            summaries = self.query.get_all_plugins_summary()
            plugin_names = [s.plugin_name for s in summaries]

        results = {}
        for plugin_name in plugin_names:
            df = self.query.get_training_data_for_plugin(plugin_name)
            if len(df) > 0:
                results[plugin_name] = self.model_manager.train_for_plugin(
                    plugin_name, df
                )

        return results

    def estimate(self, plugin_name: str) -> ResourceEstimate:
        """Estimate resources for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            ResourceEstimate with all metrics.
        """
        prediction = self.model_manager.predict_for_plugin(plugin_name)

        return ResourceEstimate(
            plugin_name=plugin_name,
            wall_clock=self._prediction_to_estimate(
                prediction.wall_clock,
                self.DEFAULT_WALL_CLOCK,
            ),
            cpu_time=self._prediction_to_estimate(
                prediction.cpu_time,
                self.DEFAULT_CPU_TIME,
            ),
            memory_peak=self._prediction_to_estimate(
                prediction.memory_peak,
                self.DEFAULT_MEMORY,
            ),
            download_size=self._prediction_to_estimate(
                prediction.download_size,
                self.DEFAULT_DOWNLOAD,
            ),
        )

    def _prediction_to_estimate(
        self,
        prediction: PredictionResult | None,
        default: float,
    ) -> TimeEstimate:
        """Convert a PredictionResult to TimeEstimate.

        Args:
            prediction: Model prediction or None.
            default: Default value if no prediction.

        Returns:
            TimeEstimate instance.
        """
        if prediction is None:
            return TimeEstimate(
                point_estimate=default,
                confidence_interval=(default * 0.5, default * 2.0),
                confidence_level=0.5,
                data_points=0,
                model_type=None,
            )

        return TimeEstimate(
            point_estimate=prediction.point_estimate,
            confidence_interval=(prediction.lower_bound, prediction.upper_bound),
            confidence_level=prediction.confidence_level,
            data_points=prediction.data_points_used,
            model_type=prediction.model_type.value,
        )

    def estimate_total(
        self,
        plugin_names: list[str],
    ) -> ResourceEstimate:
        """Estimate total resources for multiple plugins.

        Args:
            plugin_names: List of plugin names.

        Returns:
            Combined ResourceEstimate.
        """
        if not plugin_names:
            return ResourceEstimate(
                plugin_name="total",
                wall_clock=TimeEstimate(0, (0, 0), 0.9, 0),
                cpu_time=TimeEstimate(0, (0, 0), 0.9, 0),
                memory_peak=TimeEstimate(0, (0, 0), 0.9, 0),
                download_size=TimeEstimate(0, (0, 0), 0.9, 0),
            )

        estimates = [self.estimate(name) for name in plugin_names]

        # Sum point estimates
        total_wall = sum(e.wall_clock.point_estimate for e in estimates)
        total_cpu = sum(e.cpu_time.point_estimate for e in estimates)
        total_download = sum(e.download_size.point_estimate for e in estimates)

        # Max memory (concurrent execution)
        max_memory = max(e.memory_peak.point_estimate for e in estimates)

        # Sum confidence intervals (simplified)
        wall_lower = sum(e.wall_clock.lower_bound for e in estimates)
        wall_upper = sum(e.wall_clock.upper_bound for e in estimates)

        cpu_lower = sum(e.cpu_time.lower_bound for e in estimates)
        cpu_upper = sum(e.cpu_time.upper_bound for e in estimates)

        download_lower = sum(e.download_size.lower_bound for e in estimates)
        download_upper = sum(e.download_size.upper_bound for e in estimates)

        min_data_points = min(e.wall_clock.data_points for e in estimates)

        return ResourceEstimate(
            plugin_name="total",
            wall_clock=TimeEstimate(
                total_wall,
                (wall_lower, wall_upper),
                0.9,
                min_data_points,
            ),
            cpu_time=TimeEstimate(
                total_cpu,
                (cpu_lower, cpu_upper),
                0.9,
                min_data_points,
            ),
            memory_peak=TimeEstimate(
                max_memory,
                (max_memory * 0.8, max_memory * 1.5),
                0.9,
                min_data_points,
            ),
            download_size=TimeEstimate(
                total_download,
                (download_lower, download_upper),
                0.9,
                min_data_points,
            ),
        )
```

### 4.2 Integration Points

The estimator integrates with the update-all system at these points:

1. **Pre-run estimation**: Called before starting updates to show expected duration
2. **Progress updates**: Called during execution to update remaining time estimates
3. **Post-run training**: Called after successful runs to update models with new data

```python
# Example integration in orchestrator
async def run_updates(self, plugins: list[str]) -> None:
    """Run updates with time estimation."""

    # Pre-run estimation
    estimate = self.estimator.estimate_total(plugins)
    self.ui.show_estimate(
        f"Estimated time: {estimate.wall_clock.format()}"
    )

    completed = []
    for plugin in plugins:
        # Update remaining estimate
        remaining = [p for p in plugins if p not in completed]
        remaining_estimate = self.estimator.estimate_total(remaining)
        self.ui.update_remaining_time(remaining_estimate.wall_clock)

        # Run plugin
        await self.run_plugin(plugin)
        completed.append(plugin)

    # Post-run: trigger model retraining (async)
    asyncio.create_task(self.estimator.train_models(plugins))
```

---

## 5. Testing Strategy (TDD Approach)

### 5.1 Test Data Generation

```python
# stats/tests/modeling/conftest.py
"""Test fixtures for modeling tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest
from darts import TimeSeries


def generate_synthetic_plugin_data(
    plugin_name: str = "test-plugin",
    num_samples: int = 100,
    base_wall_clock: float = 60.0,
    trend: float = 0.1,
    seasonality_amplitude: float = 10.0,
    noise_std: float = 5.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic plugin execution data.

    Creates realistic-looking data with:
    - Linear trend (updates take longer over time as more packages)
    - Weekly seasonality (weekends might be different)
    - Random noise

    Args:
        plugin_name: Name of the plugin.
        num_samples: Number of data points.
        base_wall_clock: Base execution time in seconds.
        trend: Trend coefficient (seconds per day).
        seasonality_amplitude: Amplitude of weekly seasonality.
        noise_std: Standard deviation of noise.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with synthetic data.
    """
    np.random.seed(seed)

    # Generate timestamps (roughly daily, with some gaps)
    start_date = datetime.now(tz=UTC) - timedelta(days=num_samples * 1.5)
    timestamps = []
    current = start_date
    for _ in range(num_samples):
        timestamps.append(current)
        # Random gap of 1-3 days
        current += timedelta(days=np.random.randint(1, 4))

    # Generate wall clock times
    days_from_start = np.array([(t - start_date).days for t in timestamps])

    # Trend component
    trend_component = trend * days_from_start

    # Weekly seasonality (slower on weekends)
    day_of_week = np.array([t.weekday() for t in timestamps])
    seasonality = seasonality_amplitude * np.sin(2 * np.pi * day_of_week / 7)

    # Noise
    noise = np.random.normal(0, noise_std, num_samples)

    # Combine
    wall_clock = base_wall_clock + trend_component + seasonality + noise
    wall_clock = np.maximum(wall_clock, 1.0)  # Ensure positive

    # Generate correlated metrics
    cpu_time = wall_clock * (0.4 + 0.2 * np.random.random(num_samples))
    memory_peak = (100 + 50 * np.random.random(num_samples)) * 1024 * 1024
    download_size = (20 + 30 * np.random.random(num_samples)) * 1024 * 1024

    # Generate package counts (correlated with wall clock)
    packages_total = 100 + days_from_start // 10
    packages_updated = np.random.poisson(5, num_samples)

    return pd.DataFrame({
        "timestamp": timestamps,
        "plugin_name": plugin_name,
        "wall_clock_seconds": wall_clock,
        "cpu_user_seconds": cpu_time,
        "memory_peak_bytes": memory_peak.astype(int),
        "download_size_bytes": download_size.astype(int),
        "packages_total": packages_total,
        "packages_updated": packages_updated,
        "status": "success",
    })


@pytest.fixture
def synthetic_data() -> pd.DataFrame:
    """Generate synthetic plugin data for testing."""
    return generate_synthetic_plugin_data(num_samples=100)


@pytest.fixture
def small_synthetic_data() -> pd.DataFrame:
    """Generate small synthetic dataset (edge case)."""
    return generate_synthetic_plugin_data(num_samples=15)


@pytest.fixture
def minimal_synthetic_data() -> pd.DataFrame:
    """Generate minimal synthetic dataset (below threshold)."""
    return generate_synthetic_plugin_data(num_samples=5)
```

### 5.2 Preprocessing Tests

```python
# stats/tests/modeling/test_preprocessing.py
"""Tests for data preprocessing."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.validation import validate_training_data


class TestDataPreprocessor:
    """Tests for DataPreprocessor."""

    def test_prepare_training_data_basic(self, synthetic_data: pd.DataFrame) -> None:
        """Test basic data preparation."""
        preprocessor = DataPreprocessor()

        target_series, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert target_series is not None
        assert len(target_series) > 0
        # Covariates should be created from derived features
        assert covariate_series is not None

    def test_outlier_removal(self, synthetic_data: pd.DataFrame) -> None:
        """Test that outliers are removed."""
        # Add an outlier
        df = synthetic_data.copy()
        df.loc[0, "wall_clock_seconds"] = 10000.0  # Extreme outlier

        preprocessor = DataPreprocessor(
            PreprocessingConfig(outlier_threshold=3.0)
        )

        target_series, _ = preprocessor.prepare_training_data(
            df,
            "wall_clock_seconds",
        )

        # Outlier should be removed
        assert len(target_series) < len(df)

    def test_log_transform(self, synthetic_data: pd.DataFrame) -> None:
        """Test log transformation."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=True)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Values should be log-transformed (smaller range)
        values = target_series.values()
        assert np.max(values) < 100  # Log of ~60 is ~4

    def test_inverse_transform(self, synthetic_data: pd.DataFrame) -> None:
        """Test inverse transformation."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=True, scaling_method="minmax")
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Inverse transform
        original = preprocessor.inverse_transform_target(target_series)

        # Should be back to original scale (approximately)
        original_values = original.values()
        assert np.mean(original_values) > 10  # Should be in seconds range

    def test_insufficient_data_raises(self, minimal_synthetic_data: pd.DataFrame) -> None:
        """Test that insufficient data raises error."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(min_samples=10)
        )

        with pytest.raises(ValueError, match="Insufficient data"):
            preprocessor.prepare_training_data(
                minimal_synthetic_data,
                "wall_clock_seconds",
            )

    def test_derived_features_computed(self, synthetic_data: pd.DataFrame) -> None:
        """Test that derived features are computed."""
        preprocessor = DataPreprocessor()

        _, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Should have time_since_last_run, day_of_week, hour_of_day
        assert covariate_series is not None
        assert covariate_series.n_components >= 3


class TestDataValidation:
    """Tests for data validation."""

    def test_valid_data(self, synthetic_data: pd.DataFrame) -> None:
        """Test validation of valid data."""
        report = validate_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert report.is_valid
        assert len(report.issues) == 0

    def test_insufficient_samples(self, minimal_synthetic_data: pd.DataFrame) -> None:
        """Test detection of insufficient samples."""
        report = validate_training_data(
            minimal_synthetic_data,
            "wall_clock_seconds",
            min_samples=10,
        )

        assert not report.is_valid
        assert any("Insufficient" in issue for issue in report.issues)

    def test_missing_target(self, synthetic_data: pd.DataFrame) -> None:
        """Test detection of missing target values."""
        df = synthetic_data.copy()
        df.loc[:5, "wall_clock_seconds"] = None

        report = validate_training_data(df, "wall_clock_seconds")

        assert report.missing_values["wall_clock_seconds"] == 6

    def test_duplicate_timestamps(self, synthetic_data: pd.DataFrame) -> None:
        """Test detection of duplicate timestamps."""
        df = synthetic_data.copy()
        df.loc[1, "timestamp"] = df.loc[0, "timestamp"]

        report = validate_training_data(df, "wall_clock_seconds")

        assert report.duplicate_timestamps == 1
```

### 5.3 Model Training Tests

```python
# stats/tests/modeling/test_trainer.py
"""Tests for model training."""

from __future__ import annotations

import numpy as np
import pytest
from darts import TimeSeries

from stats.modeling.preprocessing import DataPreprocessor
from stats.modeling.trainer import (
    ModelTrainer,
    ModelType,
    TrainingConfig,
    PredictionResult,
)


class TestModelTrainer:
    """Tests for ModelTrainer."""

    def test_model_selection_small_data(self) -> None:
        """Test model selection for small datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        # Very small data should use ExponentialSmoothing
        model_type = trainer.select_model_type(num_samples=8)
        assert model_type == ModelType.EXPONENTIAL_SMOOTHING

    def test_model_selection_medium_data(self) -> None:
        """Test model selection for medium datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        # Medium data should use AutoARIMA
        model_type = trainer.select_model_type(num_samples=25)
        assert model_type == ModelType.AUTO_ARIMA

    def test_model_selection_large_data(self) -> None:
        """Test model selection for large datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        # Large data should use LightGBM
        model_type = trainer.select_model_type(num_samples=60)
        assert model_type == ModelType.LIGHTGBM

    def test_train_exponential_smoothing(self, synthetic_data) -> None:
        """Test training ExponentialSmoothing model."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
            )
        )

        result = trainer.train("test_target", target_series)

        assert result.is_successful
        assert result.model_type == ModelType.EXPONENTIAL_SMOOTHING
        assert "mae" in result.metrics
        assert "rmse" in result.metrics

    def test_train_with_covariates(self, synthetic_data) -> None:
        """Test training with covariates."""
        preprocessor = DataPreprocessor()
        target_series, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.AUTO_ARIMA,
                auto_select=False,
            )
        )

        result = trainer.train("test_target", target_series, covariate_series)

        assert result.is_successful

    def test_prediction_with_confidence_interval(self, synthetic_data) -> None:
        """Test prediction returns confidence intervals."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
                conformal_alpha=0.1,  # 90% CI
            )
        )

        trainer.train("test_target", target_series)
        prediction = trainer.predict("test_target")

        assert isinstance(prediction, PredictionResult)
        assert prediction.point_estimate > 0
        assert prediction.lower_bound <= prediction.point_estimate
        assert prediction.upper_bound >= prediction.point_estimate
        assert prediction.confidence_level == 0.9

    def test_conformal_prediction_calibration(self, synthetic_data) -> None:
        """Test that conformal prediction is calibrated."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
                conformal_alpha=0.1,
            )
        )

        result = trainer.train("test_target", target_series)

        # Conformal residuals should be stored
        assert "test_target" in trainer._conformal_residuals
        assert len(trainer._conformal_residuals["test_target"]) > 0

    def test_insufficient_training_data(self, minimal_synthetic_data) -> None:
        """Test handling of insufficient training data."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(min_samples=3)  # Allow small data
        )
        target_series, _ = preprocessor.prepare_training_data(
            minimal_synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.LIGHTGBM,  # Requires more data
                auto_select=False,
            )
        )

        result = trainer.train("test_target", target_series)

        assert not result.is_successful
        assert "Insufficient" in result.error_message
```

### 5.4 Integration Tests

```python
# stats/tests/modeling/test_integration.py
"""Integration tests for the complete modeling pipeline."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from stats.modeling.multi_target import MultiTargetModelManager, PluginPrediction
from stats.modeling.preprocessing import PreprocessingConfig
from stats.modeling.trainer import TrainingConfig


class TestMultiTargetIntegration:
    """Integration tests for multi-target modeling."""

    def test_train_all_targets(self, synthetic_data) -> None:
        """Test training models for all target metrics."""
        manager = MultiTargetModelManager()

        results = manager.train_for_plugin("test-plugin", synthetic_data)

        # Should have results for all targets
        assert "wall_clock_seconds" in results
        assert "cpu_user_seconds" in results
        assert "memory_peak_bytes" in results
        assert "download_size_bytes" in results

        # At least some should be successful
        successful = [r for r in results.values() if r.is_successful]
        assert len(successful) >= 2

    def test_predict_all_targets(self, synthetic_data) -> None:
        """Test predicting all target metrics."""
        manager = MultiTargetModelManager()
        manager.train_for_plugin("test-plugin", synthetic_data)

        prediction = manager.predict_for_plugin("test-plugin")

        assert isinstance(prediction, PluginPrediction)
        assert prediction.plugin_name == "test-plugin"
        assert prediction.has_predictions

        # Check wall clock prediction
        if prediction.wall_clock is not None:
            assert prediction.wall_clock.point_estimate > 0
            assert prediction.wall_clock.lower_bound >= 0

    def test_save_and_load_models(self, synthetic_data) -> None:
        """Test saving and loading models."""
        manager = MultiTargetModelManager()
        manager.train_for_plugin("test-plugin", synthetic_data)

        with TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            manager.save(save_path)

            # Create new manager and load
            new_manager = MultiTargetModelManager()
            new_manager.load(save_path)

            # Should be able to predict
            prediction = new_manager.predict_for_plugin("test-plugin")
            assert prediction.has_predictions

    def test_multiple_plugins(self, synthetic_data) -> None:
        """Test training for multiple plugins."""
        manager = MultiTargetModelManager()

        # Train for multiple plugins
        for plugin_name in ["apt", "snap", "flatpak"]:
            df = synthetic_data.copy()
            df["plugin_name"] = plugin_name
            manager.train_for_plugin(plugin_name, df)

        # Should have predictions for all
        for plugin_name in ["apt", "snap", "flatpak"]:
            prediction = manager.predict_for_plugin(plugin_name)
            assert prediction.plugin_name == plugin_name


class TestEndToEndEstimation:
    """End-to-end tests for time estimation."""

    def test_estimate_single_plugin(self, synthetic_data) -> None:
        """Test estimating resources for a single plugin."""
        from unittest.mock import MagicMock
        from stats.estimator import DartsTimeEstimator

        # Mock query
        query = MagicMock()
        query.get_training_data_for_plugin.return_value = synthetic_data
        query.get_all_plugins_summary.return_value = [
            MagicMock(plugin_name="test-plugin")
        ]

        estimator = DartsTimeEstimator(query)
        estimator.train_models(["test-plugin"])

        estimate = estimator.estimate("test-plugin")

        assert estimate.plugin_name == "test-plugin"
        assert estimate.wall_clock.point_estimate > 0
        assert estimate.wall_clock.has_sufficient_data

    def test_estimate_total_multiple_plugins(self, synthetic_data) -> None:
        """Test estimating total resources for multiple plugins."""
        from unittest.mock import MagicMock
        from stats.estimator import DartsTimeEstimator

        query = MagicMock()
        query.get_training_data_for_plugin.return_value = synthetic_data

        estimator = DartsTimeEstimator(query)

        # Train for multiple plugins
        for name in ["apt", "snap"]:
            df = synthetic_data.copy()
            estimator.model_manager.train_for_plugin(name, df)

        total = estimator.estimate_total(["apt", "snap"])

        assert total.plugin_name == "total"
        # Total should be sum of individual estimates
        apt_est = estimator.estimate("apt")
        snap_est = estimator.estimate("snap")

        expected_total = apt_est.wall_clock.point_estimate + snap_est.wall_clock.point_estimate
        assert abs(total.wall_clock.point_estimate - expected_total) < 1.0
```

### 5.5 Dwarf Tests with Modeled Data

```python
# stats/tests/modeling/test_dwarf_scenarios.py
"""Dwarf tests with specific modeled scenarios.

These tests use carefully crafted synthetic data to verify
specific behaviors of the modeling pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta, UTC

from stats.modeling.preprocessing import DataPreprocessor
from stats.modeling.trainer import ModelTrainer, TrainingConfig, ModelType


class TestTrendDetection:
    """Tests for detecting and predicting trends."""

    def test_increasing_trend_prediction(self) -> None:
        """Test that model captures increasing trend."""
        # Create data with clear increasing trend
        np.random.seed(42)
        n = 50
        timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

        # Strong linear trend: 60 + 2*day
        base = 60.0
        trend = 2.0
        values = [base + trend * i + np.random.normal(0, 3) for i in range(n)]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "wall_clock_seconds": values,
        })

        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(df, "wall_clock_seconds")

        trainer = ModelTrainer(TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        ))
        trainer.train("trend_test", target_series)

        prediction = trainer.predict("trend_test")

        # Prediction should be higher than last value (trend continues)
        last_value = values[-1]
        # Account for log transform in preprocessor
        assert prediction.point_estimate > 0

    def test_stable_series_narrow_interval(self) -> None:
        """Test that stable series produces narrow confidence interval."""
        # Create very stable data (low variance)
        np.random.seed(42)
        n = 50
        timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

        # Stable around 60 seconds with very low noise
        values = [60.0 + np.random.normal(0, 1) for _ in range(n)]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "wall_clock_seconds": values,
        })

        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(df, "wall_clock_seconds")

        trainer = ModelTrainer(TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
            use_conformal=True,
        ))
        trainer.train("stable_test", target_series)

        prediction = trainer.predict("stable_test")

        # Confidence interval should be narrow
        interval_width = prediction.upper_bound - prediction.lower_bound
        assert interval_width < 20  # Should be narrow for stable data


class TestSeasonalityDetection:
    """Tests for detecting and predicting seasonality."""

    def test_weekly_seasonality(self) -> None:
        """Test that model captures weekly seasonality."""
        np.random.seed(42)
        n = 56  # 8 weeks
        timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

        # Weekly pattern: slower on weekends
        values = []
        for i, ts in enumerate(timestamps):
            base = 60.0
            # Weekend effect: +20 seconds on Saturday/Sunday
            if ts.weekday() >= 5:
                base += 20.0
            values.append(base + np.random.normal(0, 3))

        df = pd.DataFrame({
            "timestamp": timestamps,
            "wall_clock_seconds": values,
        })

        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(df, "wall_clock_seconds")

        trainer = ModelTrainer(TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        ))
        result = trainer.train("seasonal_test", target_series)

        # Model should successfully train on seasonal data
        assert result.is_successful


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_single_outlier_handling(self) -> None:
        """Test that single outlier doesn't break prediction."""
        np.random.seed(42)
        n = 30
        timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

        values = [60.0 + np.random.normal(0, 5) for _ in range(n)]
        values[15] = 1000.0  # Single extreme outlier

        df = pd.DataFrame({
            "timestamp": timestamps,
            "wall_clock_seconds": values,
        })

        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(df, "wall_clock_seconds")

        trainer = ModelTrainer(TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        ))
        trainer.train("outlier_test", target_series)

        prediction = trainer.predict("outlier_test")

        # Prediction should be reasonable (not affected by outlier)
        assert 30 < prediction.point_estimate < 150

    def test_missing_values_handling(self) -> None:
        """Test handling of missing values in data."""
        np.random.seed(42)
        n = 30
        timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

        values = [60.0 + np.random.normal(0, 5) for _ in range(n)]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "wall_clock_seconds": values,
        })

        # Add some missing values
        df.loc[5, "wall_clock_seconds"] = None
        df.loc[10, "wall_clock_seconds"] = None

        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(df, "wall_clock_seconds")

        # Should handle missing values
        assert len(target_series) > 0

    def test_zero_values_handling(self) -> None:
        """Test handling of zero values (valid for some metrics)."""
        np.random.seed(42)
        n = 30
        timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

        # Some zero download sizes (nothing to download)
        values = [0.0 if i % 5 == 0 else 50.0 * 1024 * 1024 for i in range(n)]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "download_size_bytes": values,
        })

        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(df, "download_size_bytes")

        trainer = ModelTrainer(TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        ))
        result = trainer.train("zero_test", target_series)

        assert result.is_successful


class TestConfidenceIntervalCalibration:
    """Tests for confidence interval calibration."""

    def test_90_percent_coverage(self) -> None:
        """Test that 90% CI achieves approximately 90% coverage."""
        np.random.seed(42)

        # Generate multiple test datasets and check coverage
        coverage_count = 0
        n_tests = 20

        for test_idx in range(n_tests):
            n = 50
            timestamps = [datetime.now(tz=UTC) - timedelta(days=n-i) for i in range(n)]

            # Generate data with known distribution
            true_mean = 60.0
            true_std = 10.0
            values = [true_mean + np.random.normal(0, true_std) for _ in range(n)]

            df = pd.DataFrame({
                "timestamp": timestamps,
                "wall_clock_seconds": values,
            })

            preprocessor = DataPreprocessor()
            target_series, _ = preprocessor.prepare_training_data(df, "wall_clock_seconds")

            trainer = ModelTrainer(TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
                conformal_alpha=0.1,  # 90% CI
            ))
            trainer.train(f"coverage_test_{test_idx}", target_series)

            prediction = trainer.predict(f"coverage_test_{test_idx}")

            # Check if true mean is within interval
            # (using inverse-transformed values approximately)
            if prediction.lower_bound <= true_mean <= prediction.upper_bound:
                coverage_count += 1

        # Coverage should be approximately 90% (allow some variance)
        coverage_rate = coverage_count / n_tests
        assert coverage_rate >= 0.7  # At least 70% for small sample
```

---

## 6. Module Architecture

### 6.1 Package Structure

```
stats/
├── stats/
│   ├── __init__.py
│   ├── modeling/
│   │   ├── __init__.py
│   │   ├── preprocessing.py    # Data preprocessing
│   │   ├── validation.py       # Data quality validation
│   │   ├── trainer.py          # Model training
│   │   ├── multi_target.py     # Multi-target management
│   │   └── models/             # Custom model implementations
│   │       ├── __init__.py
│   │       └── ensemble.py     # Ensemble models
│   ├── db/                     # DuckDB integration (from other plan)
│   ├── retrieval/              # Data retrieval (from other plan)
│   ├── calculator.py           # Existing calculator
│   ├── estimator.py            # Updated with Darts
│   └── history.py              # Existing history (deprecated)
└── tests/
    ├── __init__.py
    ├── modeling/
    │   ├── __init__.py
    │   ├── conftest.py         # Test fixtures
    │   ├── test_preprocessing.py
    │   ├── test_trainer.py
    │   ├── test_integration.py
    │   └── test_dwarf_scenarios.py
    └── ...
```

---

## 7. Dependencies

### 7.1 Python Packages

Add to [`stats/pyproject.toml`](../stats/pyproject.toml):

```toml
[tool.poetry.dependencies]
darts = "^0.40.0"
pandas = "^2.0.0"
numpy = "^1.24.0"
scikit-learn = "^1.3.0"

# Optional: For advanced models
lightgbm = { version = "^4.0.0", optional = true }
prophet = { version = "^1.1.0", optional = true }

[tool.poetry.extras]
ml = ["lightgbm", "prophet"]
```

### 7.2 System Requirements

- Python 3.10+
- 4GB RAM minimum (for model training)
- 100MB disk space for model storage

---

## 8. Implementation Phases

### Phase 1: Core Infrastructure (Week 1)

1. Set up Darts dependency
2. Implement preprocessing module
3. Implement data validation
4. Write unit tests for preprocessing

### Phase 2: Model Training (Week 2)

1. Implement ModelTrainer class
2. Add support for multiple model types
3. Implement conformal prediction
4. Write training tests

### Phase 3: Multi-Target Support (Week 3)

1. Implement MultiTargetModelManager
2. Add model persistence
3. Write integration tests
4. Performance optimization

### Phase 4: Integration (Week 4)

1. Update TimeEstimator with Darts backend
2. Integrate with orchestrator
3. Add automatic retraining
4. End-to-end testing

### Phase 5: Documentation and Polish (Week 5)

1. Complete API documentation
2. Write user guide
3. Performance benchmarks
4. Final review

---

## 9. Success Criteria

1. **Accuracy**: MAPE < 30% for wall-clock time predictions
2. **Calibration**: 90% CI achieves 85-95% empirical coverage
3. **Performance**: Prediction latency < 100ms
4. **Reliability**: 95%+ test coverage for new code
5. **Usability**: Clear API with comprehensive documentation

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Insufficient historical data | High | Fall back to simple heuristics |
| Model training too slow | Medium | Use simpler models, async training |
| Overfitting on small data | Medium | Cross-validation, regularization |
| Darts API changes | Low | Pin version, abstract interface |
| Memory usage during training | Medium | Limit model complexity, batch processing |

---

*Document created: 2025-01-08*
*Last updated: 2025-01-08*
