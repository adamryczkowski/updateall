"""Tests for multi-target model management."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from stats.modeling.multi_target import (
    TARGET_COLUMNS,
    MultiTargetModelManager,
    MultiTargetTrainingResult,
    PluginPrediction,
)
from stats.modeling.trainer import ModelType, TrainingConfig


class TestPluginPrediction:
    """Tests for PluginPrediction dataclass."""

    def test_has_predictions_false_when_empty(self) -> None:
        """Test has_predictions is False when no predictions exist."""
        prediction = PluginPrediction(plugin_name="test")

        assert prediction.has_predictions is False

    def test_has_predictions_true_with_wall_clock(self) -> None:
        """Test has_predictions is True when wall_clock exists."""
        from stats.modeling.trainer import PredictionResult

        prediction = PluginPrediction(
            plugin_name="test",
            wall_clock=PredictionResult(
                point_estimate=60.0,
                lower_bound=50.0,
                upper_bound=70.0,
                confidence_level=0.9,
            ),
        )

        assert prediction.has_predictions is True

    def test_format_summary_no_predictions(self) -> None:
        """Test format_summary with no predictions."""
        prediction = PluginPrediction(plugin_name="test")

        summary = prediction.format_summary()

        assert "test" in summary
        assert "No predictions" in summary

    def test_format_summary_with_predictions(self) -> None:
        """Test format_summary with predictions."""
        from stats.modeling.trainer import PredictionResult

        prediction = PluginPrediction(
            plugin_name="test",
            wall_clock=PredictionResult(
                point_estimate=60.0,
                lower_bound=50.0,
                upper_bound=70.0,
                confidence_level=0.9,
            ),
            download_size=PredictionResult(
                point_estimate=50 * 1024 * 1024,  # 50MB
                lower_bound=40 * 1024 * 1024,
                upper_bound=60 * 1024 * 1024,
                confidence_level=0.9,
            ),
        )

        summary = prediction.format_summary()

        assert "test" in summary
        assert "Time:" in summary
        assert "Download:" in summary


class TestMultiTargetTrainingResult:
    """Tests for MultiTargetTrainingResult dataclass."""

    def test_successful_targets_empty(self) -> None:
        """Test successful_targets when no results."""
        result = MultiTargetTrainingResult(plugin_name="test")

        assert result.successful_targets == []
        assert result.is_successful is False

    def test_successful_targets_with_results(self) -> None:
        """Test successful_targets with mixed results."""
        from stats.modeling.trainer import ModelType, TrainingResult

        result = MultiTargetTrainingResult(
            plugin_name="test",
            results={
                "wall_clock_seconds": TrainingResult(
                    is_successful=True,
                    model_type=ModelType.EXPONENTIAL_SMOOTHING,
                    target_name="test_wall_clock_seconds",
                ),
                "cpu_user_seconds": TrainingResult(
                    is_successful=False,
                    model_type=ModelType.EXPONENTIAL_SMOOTHING,
                    target_name="test_cpu_user_seconds",
                    error_message="Not enough data",
                ),
            },
        )

        assert "wall_clock_seconds" in result.successful_targets
        assert "cpu_user_seconds" in result.failed_targets
        assert result.is_successful is True


class TestMultiTargetModelManager:
    """Tests for MultiTargetModelManager."""

    def test_train_for_plugin(self, synthetic_data: pd.DataFrame) -> None:
        """Test training models for a plugin."""
        # Use ExponentialSmoothing to avoid LightGBM dependency
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)

        result = manager.train_for_plugin("test-plugin", synthetic_data)

        assert result.plugin_name == "test-plugin"
        assert result.is_successful
        # At least wall_clock_seconds should train successfully
        assert "wall_clock_seconds" in result.successful_targets

    def test_train_for_plugin_specific_targets(self, synthetic_data: pd.DataFrame) -> None:
        """Test training only specific targets."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)

        result = manager.train_for_plugin(
            "test-plugin",
            synthetic_data,
            targets=["wall_clock_seconds"],
        )

        assert result.plugin_name == "test-plugin"
        assert "wall_clock_seconds" in result.results
        # Other targets should not be trained
        assert "cpu_user_seconds" not in result.results

    def test_train_for_plugin_missing_column(self, synthetic_data: pd.DataFrame) -> None:
        """Test training with missing target column."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)
        # Remove a column
        df = synthetic_data.drop(columns=["cpu_user_seconds"])

        result = manager.train_for_plugin("test-plugin", df)

        # Should still succeed for other targets
        assert result.is_successful
        assert "cpu_user_seconds" not in result.results

    def test_predict_for_plugin(self, synthetic_data: pd.DataFrame) -> None:
        """Test making predictions for a plugin."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)
        manager.train_for_plugin("test-plugin", synthetic_data)

        prediction = manager.predict_for_plugin("test-plugin")

        assert isinstance(prediction, PluginPrediction)
        assert prediction.plugin_name == "test-plugin"
        assert prediction.has_predictions
        # Wall clock should have a prediction
        if prediction.wall_clock is not None:
            assert prediction.wall_clock.point_estimate > 0
            assert prediction.wall_clock.lower_bound >= 0

    def test_predict_for_plugin_no_model(self) -> None:
        """Test prediction when no model exists."""
        manager = MultiTargetModelManager()

        prediction = manager.predict_for_plugin("nonexistent")

        assert prediction.plugin_name == "nonexistent"
        assert prediction.has_predictions is False

    def test_has_models_for_plugin(self, synthetic_data: pd.DataFrame) -> None:
        """Test checking if models exist for a plugin."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)

        assert manager.has_models_for_plugin("test-plugin") is False

        manager.train_for_plugin("test-plugin", synthetic_data)

        assert manager.has_models_for_plugin("test-plugin") is True

    def test_get_trained_plugins(self, synthetic_data: pd.DataFrame) -> None:
        """Test getting list of trained plugins."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)

        assert manager.get_trained_plugins() == []

        manager.train_for_plugin("plugin1", synthetic_data)
        manager.train_for_plugin("plugin2", synthetic_data)

        plugins = manager.get_trained_plugins()
        assert "plugin1" in plugins
        assert "plugin2" in plugins

    def test_save_and_load(self, synthetic_data: pd.DataFrame) -> None:
        """Test saving and loading models."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)
        manager.train_for_plugin("test-plugin", synthetic_data)

        with TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            manager.save(save_path)

            # Create new manager and load
            new_manager = MultiTargetModelManager(training_config=config)
            new_manager.load(save_path)

            # Should be able to make predictions
            prediction = new_manager.predict_for_plugin("test-plugin")
            assert prediction.has_predictions

    def test_clear(self, synthetic_data: pd.DataFrame) -> None:
        """Test clearing all models."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)
        manager.train_for_plugin("test-plugin", synthetic_data)

        assert manager.has_models_for_plugin("test-plugin") is True

        manager.clear()

        assert manager.has_models_for_plugin("test-plugin") is False
        assert manager.get_trained_plugins() == []

    def test_custom_training_config(self, synthetic_data: pd.DataFrame) -> None:
        """Test using custom training configuration."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
            use_conformal=True,
            conformal_alpha=0.2,  # 80% CI
        )
        manager = MultiTargetModelManager(training_config=config)

        result = manager.train_for_plugin("test-plugin", synthetic_data)

        assert result.is_successful
        # Check that the model type was used
        for target_result in result.results.values():
            if target_result.is_successful:
                assert target_result.model_type == ModelType.EXPONENTIAL_SMOOTHING


class TestMultiTargetIntegration:
    """Integration tests for multi-target modeling."""

    def test_train_all_targets(self, synthetic_data: pd.DataFrame) -> None:
        """Test training models for all target metrics."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)

        result = manager.train_for_plugin("test-plugin", synthetic_data)

        # Check that we attempted to train all available targets
        trained_targets = set(result.results.keys())
        expected_targets = set(TARGET_COLUMNS) & set(synthetic_data.columns)

        assert trained_targets == expected_targets

    def test_predict_all_targets(self, synthetic_data: pd.DataFrame) -> None:
        """Test predicting all target metrics."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)
        manager.train_for_plugin("test-plugin", synthetic_data)

        prediction = manager.predict_for_plugin("test-plugin")

        assert isinstance(prediction, PluginPrediction)
        assert prediction.plugin_name == "test-plugin"
        assert prediction.has_predictions

        # At least wall_clock should have a prediction
        assert prediction.wall_clock is not None
        assert prediction.wall_clock.point_estimate > 0

    def test_multiple_plugins(self, synthetic_data: pd.DataFrame) -> None:
        """Test training and predicting for multiple plugins."""
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        manager = MultiTargetModelManager(training_config=config)

        # Train for multiple plugins
        for name in ["apt", "flatpak", "snap"]:
            df = synthetic_data.copy()
            manager.train_for_plugin(name, df)

        # All should have models
        assert len(manager.get_trained_plugins()) == 3

        # All should be able to predict
        for name in ["apt", "flatpak", "snap"]:
            prediction = manager.predict_for_plugin(name)
            assert prediction.has_predictions
