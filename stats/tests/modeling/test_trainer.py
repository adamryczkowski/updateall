"""Tests for model training - Dwarf tests with synthetic data."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.trainer import (
    ModelTrainer,
    ModelType,
    PredictionResult,
    TrainingConfig,
    TrainingResult,
)

if TYPE_CHECKING:
    import pandas as pd


def _lightgbm_available() -> bool:
    """Check if LightGBM is available."""
    try:
        import lightgbm  # type: ignore[import-not-found]  # noqa: F401

        return True
    except ImportError:
        return False


class TestModelSelection:
    """Tests for automatic model selection."""

    def test_selects_exponential_smoothing_for_small_data(self) -> None:
        """Test that ExponentialSmoothing is selected for small datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=8)

        assert model_type == ModelType.EXPONENTIAL_SMOOTHING

    def test_selects_auto_arima_for_medium_data(self) -> None:
        """Test that AutoARIMA is selected for medium datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=25)

        assert model_type == ModelType.AUTO_ARIMA

    def test_selects_prophet_for_larger_data(self) -> None:
        """Test that Prophet is selected for larger datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=35)

        assert model_type == ModelType.PROPHET

    def test_selects_lightgbm_for_large_data(self) -> None:
        """Test that LightGBM is selected for large datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=60)

        assert model_type == ModelType.LIGHTGBM

    def test_respects_manual_selection(self) -> None:
        """Test that manual model selection is respected."""
        trainer = ModelTrainer(TrainingConfig(model_type=ModelType.PROPHET, auto_select=False))

        model_type = trainer.select_model_type(num_samples=10)

        assert model_type == ModelType.PROPHET


class TestModelTraining:
    """Tests for model training with synthetic data."""

    def test_train_exponential_smoothing(self, synthetic_data: pd.DataFrame) -> None:
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
        assert result.target_name == "test_target"
        assert result.training_samples > 0

    @pytest.mark.skipif(not _lightgbm_available(), reason="LightGBM not installed")
    def test_train_with_auto_selection(self, synthetic_data: pd.DataFrame) -> None:
        """Test training with automatic model selection."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        result = trainer.train("test_target", target_series)

        assert result.is_successful
        # With 100 samples, should select LightGBM
        assert result.model_type == ModelType.LIGHTGBM

    def test_train_computes_validation_metrics(self, synthetic_data: pd.DataFrame) -> None:
        """Test that training computes validation metrics."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                validation_split=0.2,
            )
        )

        result = trainer.train("test_target", target_series)

        assert result.is_successful
        assert "mae" in result.metrics
        assert "rmse" in result.metrics
        assert result.validation_samples > 0

    def test_train_with_small_data(self, small_synthetic_data: pd.DataFrame) -> None:
        """Test training with small dataset."""
        preprocessor = DataPreprocessor(PreprocessingConfig(min_samples=5))
        target_series, _ = preprocessor.prepare_training_data(
            small_synthetic_data,
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

    @pytest.mark.skipif(not _lightgbm_available(), reason="LightGBM not installed")
    def test_insufficient_training_data_fails_gracefully(
        self, minimal_synthetic_data: pd.DataFrame
    ) -> None:
        """Test that insufficient data is handled gracefully."""
        preprocessor = DataPreprocessor(PreprocessingConfig(min_samples=3))
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
        assert "Insufficient" in (result.error_message or "")

    def test_train_stores_conformal_residuals(self, synthetic_data: pd.DataFrame) -> None:
        """Test that conformal residuals are stored after training."""
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
            )
        )

        trainer.train("test_target", target_series)

        assert "test_target" in trainer._conformal_residuals
        assert len(trainer._conformal_residuals["test_target"]) > 0


class TestPrediction:
    """Tests for prediction with confidence intervals."""

    def test_prediction_returns_confidence_interval(self, synthetic_data: pd.DataFrame) -> None:
        """Test that predictions include confidence intervals."""
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

    def test_prediction_bounds_are_non_negative(self, synthetic_data: pd.DataFrame) -> None:
        """Test that prediction bounds are non-negative for physical quantities."""
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

        trainer.train("test_target", target_series)
        prediction = trainer.predict("test_target")

        assert prediction.lower_bound >= 0
        assert prediction.upper_bound >= 0

    def test_prediction_without_training_raises(self) -> None:
        """Test that predicting without training raises error."""
        trainer = ModelTrainer()

        with pytest.raises(ValueError, match="No trained model"):
            trainer.predict("nonexistent_target")

    def test_prediction_with_custom_horizon(self, synthetic_data: pd.DataFrame) -> None:
        """Test prediction with custom horizon."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                horizon=1,
            )
        )

        trainer.train("test_target", target_series)
        prediction = trainer.predict("test_target", horizon=3)

        assert prediction.horizon == 3

    def test_prediction_format(self, synthetic_data: pd.DataFrame) -> None:
        """Test that predictions format correctly."""
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

        trainer.train("test_target", target_series)
        prediction = trainer.predict("test_target")
        formatted = prediction.format()

        assert isinstance(formatted, str)
        assert len(formatted) > 0
        assert "(" in formatted and ")" in formatted
        assert "-" in formatted


class TestModelPersistence:
    """Tests for saving and loading models."""

    def test_save_and_load_models(self, synthetic_data: pd.DataFrame) -> None:
        """Test saving and loading models."""
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
            )
        )
        trainer.train("test_target", target_series)

        with TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            trainer.save_models(save_path)

            # Verify files were created
            assert (save_path / "test_target_model.pkl").exists()
            assert (save_path / "test_target_residuals.npy").exists()

            # Load into new trainer
            new_trainer = ModelTrainer()
            new_trainer.load_models(save_path)

            assert "test_target" in new_trainer._models
            assert "test_target" in new_trainer._conformal_residuals

    def test_loaded_model_can_predict(self, synthetic_data: pd.DataFrame) -> None:
        """Test that loaded models can make predictions."""
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
        trainer.train("test_target", target_series)
        trainer._training_series["test_target"] = target_series

        with TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            trainer.save_models(save_path)

            new_trainer = ModelTrainer()
            new_trainer.load_models(save_path)
            # Need to also set training series for prediction
            new_trainer._training_series["test_target"] = target_series

            prediction = new_trainer.predict("test_target")

            assert prediction.point_estimate > 0


class TestTrainingResult:
    """Tests for TrainingResult dataclass."""

    def test_successful_result(self) -> None:
        """Test creating a successful training result."""
        result = TrainingResult(
            is_successful=True,
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            target_name="test",
            metrics={"mae": 1.5, "rmse": 2.0},
            training_samples=80,
            validation_samples=20,
        )

        assert result.is_successful
        assert result.metrics["mae"] == 1.5
        assert result.error_message is None

    def test_failed_result(self) -> None:
        """Test creating a failed training result."""
        result = TrainingResult(
            is_successful=False,
            model_type=ModelType.LIGHTGBM,
            target_name="test",
            error_message="Insufficient data",
        )

        assert not result.is_successful
        assert result.error_message == "Insufficient data"
        assert result.metrics == {}


class TestPredictionResult:
    """Tests for PredictionResult dataclass."""

    def test_format_default_precision(self) -> None:
        """Test formatting with default precision."""
        result = PredictionResult(
            point_estimate=60.5,
            lower_bound=45.2,
            upper_bound=75.8,
            confidence_level=0.9,
        )

        formatted = result.format()

        assert "60.5" in formatted
        assert "45.2" in formatted
        assert "75.8" in formatted

    def test_format_custom_precision(self) -> None:
        """Test formatting with custom precision."""
        result = PredictionResult(
            point_estimate=60.567,
            lower_bound=45.234,
            upper_bound=75.891,
            confidence_level=0.9,
        )

        formatted = result.format(precision=2)

        assert "60.57" in formatted
        assert "45.23" in formatted
        assert "75.89" in formatted


class TestModelCreation:
    """Tests for model creation."""

    def test_create_exponential_smoothing(self) -> None:
        """Test creating ExponentialSmoothing model."""
        trainer = ModelTrainer()

        model = trainer.create_model(ModelType.EXPONENTIAL_SMOOTHING)

        assert model is not None

    @pytest.mark.skipif(not _lightgbm_available(), reason="LightGBM not installed")
    def test_create_lightgbm(self) -> None:
        """Test creating LightGBM model."""
        trainer = ModelTrainer(TrainingConfig(horizon=1, random_state=42))

        model = trainer.create_model(ModelType.LIGHTGBM)

        assert model is not None

    def test_create_unknown_model_raises(self) -> None:
        """Test that creating unknown model raises error."""
        trainer = ModelTrainer()

        # Create a fake model type value
        with pytest.raises(ValueError, match="Unknown model type"):
            trainer.create_model("unknown_model")  # type: ignore[arg-type]
