"""Multi-target model management for all metrics.

This module provides a manager for training and predicting multiple target
metrics (wall clock time, CPU time, memory, download size) for each plugin.
It coordinates the training pipeline and provides a unified interface for
predictions.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.trainer import (
    ModelTrainer,
    PredictionResult,
    TrainingConfig,
    TrainingResult,
)

if TYPE_CHECKING:
    import pandas as pd

logger = structlog.get_logger(__name__)


# Target columns that we train models for
TARGET_COLUMNS = [
    "wall_clock_seconds",
    "cpu_user_seconds",
    "memory_peak_bytes",
    "download_size_bytes",
]


@dataclass
class PluginPrediction:
    """Complete prediction for a plugin across all metrics.

    Attributes:
        plugin_name: Name of the plugin.
        wall_clock: Prediction for wall-clock time (seconds).
        cpu_time: Prediction for CPU time (seconds).
        memory_peak: Prediction for peak memory usage (bytes).
        download_size: Prediction for download size (bytes).
        has_predictions: Whether any predictions are available.
    """

    plugin_name: str
    wall_clock: PredictionResult | None = None
    cpu_time: PredictionResult | None = None
    memory_peak: PredictionResult | None = None
    download_size: PredictionResult | None = None

    @property
    def has_predictions(self) -> bool:
        """Check if any predictions are available."""
        return any(
            [
                self.wall_clock is not None,
                self.cpu_time is not None,
                self.memory_peak is not None,
                self.download_size is not None,
            ]
        )

    def format_summary(self) -> str:
        """Format a summary of all predictions.

        Returns:
            Human-readable summary string.
        """
        parts = []
        if self.wall_clock:
            parts.append(f"Time: {self.wall_clock.format()}s")
        if self.cpu_time:
            parts.append(f"CPU: {self.cpu_time.format()}s")
        if self.memory_peak:
            mb = self.memory_peak.point_estimate / (1024 * 1024)
            parts.append(f"Memory: {mb:.0f}MB")
        if self.download_size:
            mb = self.download_size.point_estimate / (1024 * 1024)
            parts.append(f"Download: {mb:.0f}MB")

        if not parts:
            return f"{self.plugin_name}: No predictions available"

        return f"{self.plugin_name}: {', '.join(parts)}"


@dataclass
class MultiTargetTrainingResult:
    """Result of training models for all targets.

    Attributes:
        plugin_name: Name of the plugin.
        results: Dictionary mapping target names to training results.
        successful_targets: List of targets that trained successfully.
        failed_targets: List of targets that failed to train.
    """

    plugin_name: str
    results: dict[str, TrainingResult] = field(default_factory=dict)

    @property
    def successful_targets(self) -> list[str]:
        """Get list of successfully trained targets."""
        return [name for name, result in self.results.items() if result.is_successful]

    @property
    def failed_targets(self) -> list[str]:
        """Get list of targets that failed to train."""
        return [name for name, result in self.results.items() if not result.is_successful]

    @property
    def is_successful(self) -> bool:
        """Check if at least one target trained successfully."""
        return len(self.successful_targets) > 0


class MultiTargetModelManager:
    """Manager for multi-target model training and prediction.

    Manages models for multiple target metrics (wall clock, CPU time,
    memory, download size) across multiple plugins. Provides a unified
    interface for training and prediction.

    Example:
        >>> manager = MultiTargetModelManager()
        >>> result = manager.train_for_plugin("apt", training_data)
        >>> if result.is_successful:
        ...     prediction = manager.predict_for_plugin("apt")
        ...     print(prediction.format_summary())
    """

    def __init__(
        self,
        training_config: TrainingConfig | None = None,
        preprocessing_config: PreprocessingConfig | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            training_config: Configuration for model training.
            preprocessing_config: Configuration for data preprocessing.
        """
        self.training_config = training_config or TrainingConfig()
        self.preprocessing_config = preprocessing_config or PreprocessingConfig()

        # Store trainers and preprocessors per plugin
        self._trainers: dict[str, ModelTrainer] = {}
        self._preprocessors: dict[str, dict[str, DataPreprocessor]] = {}

    def train_for_plugin(
        self,
        plugin_name: str,
        data: pd.DataFrame,
        targets: list[str] | None = None,
    ) -> MultiTargetTrainingResult:
        """Train models for all target metrics for a plugin.

        Args:
            plugin_name: Name of the plugin.
            data: Training data as a pandas DataFrame.
            targets: Optional list of target columns to train. If None,
                trains all available targets.

        Returns:
            MultiTargetTrainingResult with results for each target.
        """
        targets = targets or TARGET_COLUMNS
        result = MultiTargetTrainingResult(plugin_name=plugin_name)

        # Create trainer for this plugin
        trainer = ModelTrainer(self.training_config)
        self._trainers[plugin_name] = trainer

        # Store preprocessors for each target
        if plugin_name not in self._preprocessors:
            self._preprocessors[plugin_name] = {}

        for target in targets:
            # Skip if target column doesn't exist in data
            if target not in data.columns:
                logger.debug(
                    "target_column_missing",
                    plugin=plugin_name,
                    target=target,
                )
                continue

            # Skip if all values are null
            if data[target].isna().all():
                logger.debug(
                    "target_column_all_null",
                    plugin=plugin_name,
                    target=target,
                )
                continue

            try:
                # Create preprocessor for this target
                preprocessor = DataPreprocessor(self.preprocessing_config)
                self._preprocessors[plugin_name][target] = preprocessor

                # Prepare training data
                target_series, covariate_series = preprocessor.prepare_training_data(
                    data,
                    target,
                )

                # Train model
                training_result = trainer.train(
                    target_name=f"{plugin_name}_{target}",
                    target_series=target_series,
                    covariate_series=covariate_series,
                )

                result.results[target] = training_result

                logger.info(
                    "model_trained",
                    plugin=plugin_name,
                    target=target,
                    success=training_result.is_successful,
                    model_type=training_result.model_type.value,
                    metrics=training_result.metrics,
                )

            except Exception as e:
                logger.warning(
                    "training_failed",
                    plugin=plugin_name,
                    target=target,
                    error=str(e),
                )
                result.results[target] = TrainingResult(
                    is_successful=False,
                    model_type=self.training_config.model_type,
                    target_name=f"{plugin_name}_{target}",
                    error_message=str(e),
                )

        return result

    def predict_for_plugin(
        self,
        plugin_name: str,
        horizon: int = 1,
    ) -> PluginPrediction:
        """Make predictions for all metrics for a plugin.

        Args:
            plugin_name: Name of the plugin.
            horizon: Number of steps ahead to predict.

        Returns:
            PluginPrediction with predictions for all available metrics.
        """
        prediction = PluginPrediction(plugin_name=plugin_name)

        if plugin_name not in self._trainers:
            logger.warning("no_trained_models", plugin=plugin_name)
            return prediction

        trainer = self._trainers[plugin_name]

        # Try to predict each target
        target_mapping = {
            "wall_clock_seconds": "wall_clock",
            "cpu_user_seconds": "cpu_time",
            "memory_peak_bytes": "memory_peak",
            "download_size_bytes": "download_size",
        }

        for target, attr_name in target_mapping.items():
            target_key = f"{plugin_name}_{target}"
            try:
                pred_result = trainer.predict(target_key, horizon=horizon)

                # Note: For now we return the transformed prediction
                # Full inverse transform would require creating a TimeSeries
                # from the prediction result, which is complex
                # TODO: Implement inverse transform when preprocessor is available

                setattr(prediction, attr_name, pred_result)

            except ValueError:
                # No model for this target
                pass
            except Exception as e:
                logger.warning(
                    "prediction_failed",
                    plugin=plugin_name,
                    target=target,
                    error=str(e),
                )

        return prediction

    def has_models_for_plugin(self, plugin_name: str) -> bool:
        """Check if models exist for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            True if at least one model exists for the plugin.
        """
        return plugin_name in self._trainers

    def get_trained_plugins(self) -> list[str]:
        """Get list of plugins with trained models.

        Returns:
            List of plugin names.
        """
        return list(self._trainers.keys())

    def save(self, directory: Path | str) -> None:
        """Save all trained models to disk.

        Args:
            directory: Directory to save models to.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        # Save each plugin's trainer
        for plugin_name, trainer in self._trainers.items():
            plugin_dir = directory / plugin_name
            plugin_dir.mkdir(parents=True, exist_ok=True)
            trainer.save_models(plugin_dir)

        # Save metadata
        metadata = {
            "plugins": list(self._trainers.keys()),
            "training_config": {
                "model_type": self.training_config.model_type.value,
                "auto_select": self.training_config.auto_select,
                "use_conformal": self.training_config.use_conformal,
                "conformal_alpha": self.training_config.conformal_alpha,
            },
        }

        metadata_path = directory / "metadata.pkl"
        with metadata_path.open("wb") as f:
            pickle.dump(metadata, f)

        logger.info("models_saved", directory=str(directory), plugins=metadata["plugins"])

    def load(self, directory: Path | str) -> None:
        """Load trained models from disk.

        Args:
            directory: Directory to load models from.
        """
        directory = Path(directory)

        if not directory.exists():
            logger.warning("model_directory_not_found", directory=str(directory))
            return

        # Load metadata
        metadata_path = directory / "metadata.pkl"
        if metadata_path.exists():
            with metadata_path.open("rb") as f:
                metadata: dict[str, Any] = pickle.load(f)
            plugins = metadata.get("plugins", [])
        else:
            # Discover plugins from subdirectories
            plugins = [d.name for d in directory.iterdir() if d.is_dir()]

        # Load each plugin's trainer
        for plugin_name in plugins:
            plugin_dir = directory / plugin_name
            if plugin_dir.exists():
                trainer = ModelTrainer(self.training_config)
                trainer.load_models(plugin_dir)
                self._trainers[plugin_name] = trainer

        logger.info("models_loaded", directory=str(directory), plugins=plugins)

    def clear(self) -> None:
        """Clear all trained models from memory."""
        self._trainers.clear()
        self._preprocessors.clear()
        logger.info("models_cleared")
