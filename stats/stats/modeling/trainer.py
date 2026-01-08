"""Model training pipeline for time series forecasting.

This module provides a training pipeline for time series models using
the Darts library. It supports automatic model selection based on data
size and conformal prediction for calibrated confidence intervals.
"""

from __future__ import annotations

import contextlib
import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from darts import TimeSeries


class ModelType(str, Enum):
    """Available model types for time series forecasting.

    Models are ordered by minimum sample requirements:
    - EXPONENTIAL_SMOOTHING: Baseline, works with few samples (5+)
    - AUTO_ARIMA: Trend + seasonality detection (20+)
    - PROPHET: Strong seasonality patterns (30+)
    - LIGHTGBM: Many covariates, complex patterns (50+)
    - NLINEAR: Long sequences, deep learning (100+)
    """

    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    AUTO_ARIMA = "auto_arima"
    PROPHET = "prophet"
    LIGHTGBM = "lightgbm"
    NLINEAR = "nlinear"


# Minimum samples required for each model type
MODEL_MIN_SAMPLES: dict[ModelType, int] = {
    ModelType.EXPONENTIAL_SMOOTHING: 5,
    ModelType.AUTO_ARIMA: 20,
    ModelType.PROPHET: 30,
    ModelType.LIGHTGBM: 50,
    ModelType.NLINEAR: 100,
}


@dataclass
class TrainingConfig:
    """Configuration for model training.

    Attributes:
        model_type: Type of model to use (if auto_select is False).
        auto_select: Whether to automatically select model based on data size.
        use_conformal: Whether to use conformal prediction for calibrated intervals.
        conformal_alpha: Significance level for conformal prediction (e.g., 0.1 for 90% CI).
        validation_split: Fraction of data to use for validation/calibration.
        horizon: Default prediction horizon (number of steps ahead).
        random_state: Random seed for reproducibility.
    """

    model_type: ModelType = ModelType.EXPONENTIAL_SMOOTHING
    auto_select: bool = True
    use_conformal: bool = True
    conformal_alpha: float = 0.1
    validation_split: float = 0.2
    horizon: int = 1
    random_state: int | None = 42


@dataclass
class TrainingResult:
    """Result of model training.

    Attributes:
        is_successful: Whether training succeeded.
        model_type: Type of model that was trained.
        target_name: Name of the target variable.
        metrics: Dictionary of evaluation metrics (mae, rmse, mape, etc.).
        error_message: Error message if training failed.
        training_samples: Number of samples used for training.
        validation_samples: Number of samples used for validation.
    """

    is_successful: bool
    model_type: ModelType
    target_name: str
    metrics: dict[str, float] = field(default_factory=dict)
    error_message: str | None = None
    training_samples: int = 0
    validation_samples: int = 0


@dataclass
class PredictionResult:
    """Result of prediction with confidence intervals.

    Attributes:
        point_estimate: Point prediction value.
        lower_bound: Lower bound of confidence interval.
        upper_bound: Upper bound of confidence interval.
        confidence_level: Confidence level (e.g., 0.9 for 90% CI).
        horizon: Number of steps ahead predicted.
    """

    point_estimate: float
    lower_bound: float
    upper_bound: float
    confidence_level: float
    horizon: int = 1

    def format(self, precision: int = 1) -> str:
        """Format the prediction as a human-readable string.

        Args:
            precision: Number of decimal places.

        Returns:
            Formatted string like "60.5s (45.2s - 75.8s)".
        """
        return (
            f"{self.point_estimate:.{precision}f} "
            f"({self.lower_bound:.{precision}f} - {self.upper_bound:.{precision}f})"
        )


class ModelTrainer:
    """Trainer for time series forecasting models.

    Supports automatic model selection based on data size, training with
    validation, and conformal prediction for calibrated confidence intervals.

    Example:
        >>> trainer = ModelTrainer(TrainingConfig(auto_select=True))
        >>> result = trainer.train("wall_clock", target_series)
        >>> if result.is_successful:
        ...     prediction = trainer.predict("wall_clock")
        ...     print(f"Predicted: {prediction.format()}")
    """

    def __init__(self, config: TrainingConfig | None = None) -> None:
        """Initialize the trainer.

        Args:
            config: Training configuration. Uses defaults if None.
        """
        self.config = config or TrainingConfig()
        self._models: dict[str, Any] = {}
        self._conformal_models: dict[str, Any] = {}
        self._conformal_residuals: dict[str, npt.NDArray[np.floating[Any]]] = {}
        self._training_series: dict[str, TimeSeries] = {}
        self._covariate_series: dict[str, TimeSeries | None] = {}

    def select_model_type(self, num_samples: int) -> ModelType:
        """Select the appropriate model type based on data size.

        Args:
            num_samples: Number of training samples available.

        Returns:
            Selected model type.
        """
        if not self.config.auto_select:
            return self.config.model_type

        # Select the most capable model that meets the sample requirement
        # Order from most to least capable
        model_order = [
            ModelType.LIGHTGBM,
            ModelType.PROPHET,
            ModelType.AUTO_ARIMA,
            ModelType.EXPONENTIAL_SMOOTHING,
        ]

        for model_type in model_order:
            if num_samples >= MODEL_MIN_SAMPLES[model_type]:
                return model_type

        # Default to simplest model
        return ModelType.EXPONENTIAL_SMOOTHING

    def create_model(
        self,
        model_type: ModelType,
    ) -> Any:
        """Create a model instance of the specified type.

        Args:
            model_type: Type of model to create.

        Returns:
            Model instance.
        """
        if model_type == ModelType.EXPONENTIAL_SMOOTHING:
            from darts.models import ExponentialSmoothing
            from darts.utils.utils import SeasonalityMode

            # Disable seasonality to avoid issues with short series
            return ExponentialSmoothing(seasonal=SeasonalityMode.NONE)

        elif model_type == ModelType.AUTO_ARIMA:
            from darts.models import StatsForecastAutoARIMA

            return StatsForecastAutoARIMA()

        elif model_type == ModelType.PROPHET:
            from darts.models import Prophet

            return Prophet()

        elif model_type == ModelType.LIGHTGBM:
            from darts.models import LightGBMModel

            return LightGBMModel(
                lags=7,
                output_chunk_length=self.config.horizon,
                random_state=self.config.random_state,
            )

        elif model_type == ModelType.NLINEAR:
            from darts.models import NLinearModel

            return NLinearModel(
                input_chunk_length=14,
                output_chunk_length=self.config.horizon,
                random_state=self.config.random_state,
            )

        else:
            msg = f"Unknown model type: {model_type}"
            raise ValueError(msg)

    def train(
        self,
        target_name: str,
        target_series: TimeSeries,
        covariate_series: TimeSeries | None = None,
    ) -> TrainingResult:
        """Train a model for the specified target.

        Args:
            target_name: Name of the target variable (used as key for storage).
            target_series: Target time series to train on.
            covariate_series: Optional covariate time series.

        Returns:
            TrainingResult with training outcome and metrics.
        """
        num_samples = len(target_series)

        # Select model type
        model_type = self.select_model_type(num_samples)

        # Check minimum samples for selected model
        min_samples = MODEL_MIN_SAMPLES[model_type]
        if num_samples < min_samples:
            return TrainingResult(
                is_successful=False,
                model_type=model_type,
                target_name=target_name,
                error_message=(
                    f"Insufficient data for {model_type.value}: "
                    f"{num_samples} samples, minimum {min_samples} required"
                ),
            )

        # Split data for training and validation
        val_size = max(1, int(num_samples * self.config.validation_split))
        train_size = num_samples - val_size

        if train_size < min_samples:
            # Not enough data for validation split, use all for training
            train_series = target_series
            val_series = None
            val_size = 0
        else:
            train_series = target_series[:train_size]
            val_series = target_series[train_size:]

        # Create and train model
        try:
            model = self.create_model(model_type)

            # Train the model
            # Note: ExponentialSmoothing and some other models don't support covariates
            if self._model_supports_covariates(model_type) and covariate_series is not None:
                train_cov = covariate_series[:train_size] if val_series else covariate_series
                model.fit(train_series, future_covariates=train_cov)
            else:
                model.fit(train_series)

            # Store model and training data
            self._models[target_name] = model
            self._training_series[target_name] = target_series
            self._covariate_series[target_name] = covariate_series

            # Calculate validation metrics if we have validation data
            metrics: dict[str, float] = {}
            if val_series is not None and len(val_series) > 0:
                try:
                    # Make predictions on validation set
                    # Local models (ExponentialSmoothing, Prophet) don't take series arg
                    if self._is_local_model(model_type):
                        pred = model.predict(n=len(val_series))
                    else:
                        pred = model.predict(n=len(val_series), series=train_series)

                    # Calculate metrics
                    from darts.metrics import mae, mape, rmse

                    metrics["mae"] = float(mae(val_series, pred))
                    metrics["rmse"] = float(rmse(val_series, pred))
                    with contextlib.suppress(ValueError, ZeroDivisionError):
                        # MAPE can fail with zero values
                        metrics["mape"] = float(mape(val_series, pred))

                    # Store residuals for conformal prediction
                    if self.config.use_conformal:
                        residuals = np.abs(val_series.values().flatten() - pred.values().flatten())
                        self._conformal_residuals[target_name] = residuals

                except Exception:
                    # Validation failed, but training succeeded
                    pass

            return TrainingResult(
                is_successful=True,
                model_type=model_type,
                target_name=target_name,
                metrics=metrics,
                training_samples=train_size,
                validation_samples=val_size,
            )

        except Exception as e:
            return TrainingResult(
                is_successful=False,
                model_type=model_type,
                target_name=target_name,
                error_message=str(e),
            )

    def predict(
        self,
        target_name: str,
        horizon: int | None = None,
    ) -> PredictionResult:
        """Make a prediction for the specified target.

        Args:
            target_name: Name of the target variable.
            horizon: Number of steps ahead to predict (defaults to config.horizon).

        Returns:
            PredictionResult with point estimate and confidence interval.

        Raises:
            ValueError: If no trained model exists for the target.
        """
        if target_name not in self._models:
            msg = f"No trained model for target '{target_name}'"
            raise ValueError(msg)

        model = self._models[target_name]
        n = horizon or self.config.horizon

        # Make prediction - local models don't take series argument
        pred = model.predict(n=n)
        point_estimate = float(pred.values().flatten()[-1])

        # Calculate confidence interval
        confidence_level = 1.0 - self.config.conformal_alpha

        if self.config.use_conformal and target_name in self._conformal_residuals:
            # Use conformal prediction for calibrated intervals
            residuals = self._conformal_residuals[target_name]
            quantile = np.quantile(residuals, confidence_level)
            lower_bound = max(0, point_estimate - quantile)
            upper_bound = point_estimate + quantile
        else:
            # Use simple heuristic for intervals (±20% of point estimate)
            margin = abs(point_estimate) * 0.2
            lower_bound = max(0, point_estimate - margin)
            upper_bound = point_estimate + margin

        return PredictionResult(
            point_estimate=point_estimate,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            confidence_level=confidence_level,
            horizon=n,
        )

    def save_models(self, directory: Path | str) -> None:
        """Save trained models to disk.

        Args:
            directory: Directory to save models to.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        for target_name, model in self._models.items():
            model_path = directory / f"{target_name}_model.pkl"
            with model_path.open("wb") as f:
                pickle.dump(model, f)

            # Save conformal residuals if available
            if target_name in self._conformal_residuals:
                residuals_path = directory / f"{target_name}_residuals.npy"
                np.save(residuals_path, self._conformal_residuals[target_name])

    def load_models(self, directory: Path | str) -> None:
        """Load trained models from disk.

        Args:
            directory: Directory to load models from.
        """
        directory = Path(directory)

        for model_path in directory.glob("*_model.pkl"):
            target_name = model_path.stem.replace("_model", "")
            with model_path.open("rb") as f:
                self._models[target_name] = pickle.load(f)

            # Load conformal residuals if available
            residuals_path = directory / f"{target_name}_residuals.npy"
            if residuals_path.exists():
                self._conformal_residuals[target_name] = np.load(residuals_path)

    def _model_supports_covariates(self, model_type: ModelType) -> bool:
        """Check if a model type supports covariates.

        Args:
            model_type: Model type to check.

        Returns:
            True if the model supports covariates.
        """
        # ExponentialSmoothing and Prophet don't support future covariates in the same way
        return model_type in {ModelType.LIGHTGBM, ModelType.NLINEAR}

    def _is_local_model(self, model_type: ModelType) -> bool:
        """Check if a model type is a local model.

        Local models are trained on a single series and don't take a series
        argument in predict(). Global models can predict on new series.

        Args:
            model_type: Model type to check.

        Returns:
            True if the model is a local model.
        """
        return model_type in {
            ModelType.EXPONENTIAL_SMOOTHING,
            ModelType.AUTO_ARIMA,
            ModelType.PROPHET,
        }
