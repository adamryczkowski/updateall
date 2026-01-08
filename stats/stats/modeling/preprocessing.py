"""Data preprocessing for time series modeling.

This module provides preprocessing utilities to prepare data for
training time series forecasting models using the Darts library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
from darts import TimeSeries
from darts.dataprocessing.transformers import Scaler


class FillStrategy(str, Enum):
    """Strategy for filling missing values."""

    FORWARD = "forward"
    BACKWARD = "backward"
    MEAN = "mean"
    ZERO = "zero"


class ScalingMethod(str, Enum):
    """Method for scaling target values."""

    MINMAX = "minmax"
    STANDARD = "standard"
    NONE = "none"


@dataclass
class PreprocessingConfig:
    """Configuration for data preprocessing.

    Attributes:
        min_samples: Minimum samples required for training (default: 10).
        max_lookback_days: Maximum lookback period in days (default: 365).
        fill_strategy: Strategy for filling missing values (default: forward).
        outlier_threshold: Z-score threshold for outlier removal (default: 3.0).
        log_transform: Whether to apply log transformation to targets (default: True).
        scaling_method: Method for scaling values (default: minmax).
        frequency: Time series frequency (default: None for auto-detection).
    """

    min_samples: int = 10
    max_lookback_days: int = 365
    fill_strategy: FillStrategy = FillStrategy.FORWARD
    outlier_threshold: float = 3.0
    log_transform: bool = True
    scaling_method: ScalingMethod = ScalingMethod.MINMAX
    frequency: str | None = None


@dataclass
class PreprocessingState:
    """State saved during preprocessing for inverse transformation.

    Attributes:
        log_transform_applied: Whether log transform was applied.
        scaler: The fitted scaler instance (if any).
        target_column: Name of the target column.
        original_min: Minimum value before transformation.
        original_max: Maximum value before transformation.
    """

    log_transform_applied: bool = False
    scaler: Scaler | None = None
    target_column: str = ""
    original_min: float = 0.0
    original_max: float = 0.0


class DataPreprocessor:
    """Preprocessor for time series data.

    Prepares pandas DataFrames for training Darts time series models.
    Handles missing values, outliers, feature engineering, and scaling.

    Example:
        >>> preprocessor = DataPreprocessor()
        >>> target_series, covariate_series = preprocessor.prepare_training_data(
        ...     df, "wall_clock_seconds"
        ... )
        >>> # After prediction, inverse transform to original scale
        >>> original_scale = preprocessor.inverse_transform_target(prediction)
    """

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        """Initialize the preprocessor.

        Args:
            config: Preprocessing configuration. Uses defaults if None.
        """
        self.config = config or PreprocessingConfig()
        self._state: PreprocessingState | None = None

    def prepare_training_data(
        self,
        df: pd.DataFrame,
        target_column: str,
    ) -> tuple[TimeSeries, TimeSeries | None]:
        """Prepare data for training time series models.

        Performs the following preprocessing steps:
        1. Validates minimum sample count
        2. Removes outliers based on z-score threshold
        3. Fills missing values according to fill strategy
        4. Applies log transformation (if configured)
        5. Applies scaling (if configured)
        6. Computes derived features (time_since_last_run, day_of_week, etc.)
        7. Converts to Darts TimeSeries format

        Args:
            df: DataFrame with training data. Must have a timestamp column
                and the specified target column.
            target_column: Name of the column to predict.

        Returns:
            Tuple of (target_series, covariate_series). The covariate_series
            may be None if no covariates are available.

        Raises:
            ValueError: If insufficient data or missing required columns.
        """
        # Validate minimum samples
        if len(df) < self.config.min_samples:
            msg = (
                f"Insufficient data: {len(df)} samples, minimum {self.config.min_samples} required"
            )
            raise ValueError(msg)

        # Make a copy to avoid modifying original
        df = df.copy()

        # Find timestamp column
        timestamp_col = self._find_timestamp_column(df)
        if timestamp_col is None:
            msg = "No timestamp column found (expected: timestamp, start_time, time, date)"
            raise ValueError(msg)

        # Ensure target column exists
        if target_column not in df.columns:
            msg = f"Target column '{target_column}' not found in DataFrame"
            raise ValueError(msg)

        # Sort by timestamp
        df = df.sort_values(timestamp_col).reset_index(drop=True)

        # Remove outliers
        df = self._remove_outliers(df, target_column)

        # Check again after outlier removal
        if len(df) < self.config.min_samples:
            msg = (
                f"Insufficient data after outlier removal: {len(df)} samples, "
                f"minimum {self.config.min_samples} required"
            )
            raise ValueError(msg)

        # Fill missing values
        df = self._fill_missing_values(df, target_column)

        # Store original range for inverse transform
        target_values = df[target_column].dropna()
        original_min = float(target_values.min())
        original_max = float(target_values.max())

        # Apply log transformation
        log_applied = False
        if self.config.log_transform:
            # Add small epsilon to avoid log(0)
            df[target_column] = np.log1p(df[target_column])
            log_applied = True

        # Compute derived features
        df = self._compute_derived_features(df, timestamp_col)

        # Create TimeSeries for target
        target_series = self._create_target_series(df, timestamp_col, target_column)

        # Apply scaling
        scaler = None
        if self.config.scaling_method != ScalingMethod.NONE:
            scaler = self._create_scaler()
            target_series = scaler.fit_transform(target_series)

        # Save state for inverse transformation
        self._state = PreprocessingState(
            log_transform_applied=log_applied,
            scaler=scaler,
            target_column=target_column,
            original_min=original_min,
            original_max=original_max,
        )

        # Create covariate series
        covariate_series = self._create_covariate_series(df, timestamp_col)

        return target_series, covariate_series

    def inverse_transform_target(self, series: TimeSeries) -> TimeSeries:
        """Reverse preprocessing transformations on target series.

        Applies inverse transformations in reverse order:
        1. Inverse scaling (if applied)
        2. Inverse log transformation (if applied)

        Args:
            series: Transformed TimeSeries to convert back to original scale.

        Returns:
            TimeSeries in original scale.

        Raises:
            ValueError: If no preprocessing state is available.
        """
        if self._state is None:
            msg = "No preprocessing state available. Call prepare_training_data first."
            raise ValueError(msg)

        result = series

        # Inverse scaling
        if self._state.scaler is not None:
            result = self._state.scaler.inverse_transform(result)

        # Inverse log transformation
        if self._state.log_transform_applied:
            values = result.values()
            # Apply expm1 (inverse of log1p)
            inverse_values = np.expm1(values)
            # Ensure non-negative
            inverse_values = np.maximum(inverse_values, 0)
            result = TimeSeries.from_times_and_values(
                times=result.time_index,
                values=inverse_values,
            )

        return result

    def _find_timestamp_column(self, df: pd.DataFrame) -> str | None:
        """Find the timestamp column in the DataFrame."""
        for col in ["timestamp", "start_time", "time", "date"]:
            if col in df.columns:
                return col
        return None

    def _remove_outliers(self, df: pd.DataFrame, target_column: str) -> pd.DataFrame:
        """Remove outliers based on z-score threshold."""
        target_values = df[target_column].dropna()
        if len(target_values) == 0:
            return df

        mean = target_values.mean()
        std = target_values.std()

        if std == 0:
            return df

        z_scores = np.abs((df[target_column] - mean) / std)
        mask = z_scores <= self.config.outlier_threshold
        # Also keep rows where target is NaN (they'll be handled later)
        mask = mask | df[target_column].isna()

        return df[mask].reset_index(drop=True)

    def _fill_missing_values(self, df: pd.DataFrame, target_column: str) -> pd.DataFrame:
        """Fill missing values according to the configured strategy."""
        if self.config.fill_strategy == FillStrategy.FORWARD:
            df[target_column] = df[target_column].ffill()
        elif self.config.fill_strategy == FillStrategy.BACKWARD:
            df[target_column] = df[target_column].bfill()
        elif self.config.fill_strategy == FillStrategy.MEAN:
            mean_value = df[target_column].mean()
            df[target_column] = df[target_column].fillna(mean_value)
        elif self.config.fill_strategy == FillStrategy.ZERO:
            df[target_column] = df[target_column].fillna(0)

        # Drop any remaining NaN rows
        df = df.dropna(subset=[target_column]).reset_index(drop=True)

        return df

    def _compute_derived_features(self, df: pd.DataFrame, timestamp_col: str) -> pd.DataFrame:
        """Compute derived features from timestamp and other columns."""
        # Ensure timestamp is datetime
        df[timestamp_col] = pd.to_datetime(df[timestamp_col])

        # Time since last run (in seconds)
        df["time_since_last_run"] = df[timestamp_col].diff().dt.total_seconds()
        df["time_since_last_run"] = df["time_since_last_run"].fillna(0)

        # Day of week (0=Monday, 6=Sunday)
        df["day_of_week"] = df[timestamp_col].dt.dayofweek

        # Hour of day
        df["hour_of_day"] = df[timestamp_col].dt.hour

        # Is weekend
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

        return df

    def _create_target_series(
        self, df: pd.DataFrame, timestamp_col: str, target_column: str
    ) -> TimeSeries:
        """Create a Darts TimeSeries for the target variable."""
        # Filter to only rows with valid target values
        valid_df = df[[timestamp_col, target_column]].dropna()

        return TimeSeries.from_times_and_values(
            times=pd.DatetimeIndex(valid_df[timestamp_col]),
            values=valid_df[target_column].values.reshape(-1, 1),
            fill_missing_dates=True,
            freq=self.config.frequency,
        )

    def _create_covariate_series(self, df: pd.DataFrame, timestamp_col: str) -> TimeSeries | None:
        """Create a Darts TimeSeries for covariates."""
        covariate_columns = [
            "time_since_last_run",
            "day_of_week",
            "hour_of_day",
            "is_weekend",
        ]

        # Add any other numeric columns that might be useful
        for col in ["packages_total", "packages_updated"]:
            if col in df.columns:
                covariate_columns.append(col)

        # Filter to columns that exist
        available_columns = [c for c in covariate_columns if c in df.columns]

        if not available_columns:
            return None

        # Create covariate DataFrame
        cov_df = df[[timestamp_col, *available_columns]].copy()

        # Fill any missing values in covariates
        for col in available_columns:
            cov_df[col] = cov_df[col].fillna(0)

        return TimeSeries.from_times_and_values(
            times=pd.DatetimeIndex(cov_df[timestamp_col]),
            values=cov_df[available_columns].values,
            columns=available_columns,
            fill_missing_dates=True,
            freq=self.config.frequency,
        )

    def _create_scaler(self) -> Scaler:
        """Create a scaler based on the configured method."""
        if self.config.scaling_method == ScalingMethod.MINMAX:
            from sklearn.preprocessing import MinMaxScaler

            return Scaler(scaler=MinMaxScaler())
        elif self.config.scaling_method == ScalingMethod.STANDARD:
            from sklearn.preprocessing import StandardScaler

            return Scaler(scaler=StandardScaler())
        else:
            msg = f"Unknown scaling method: {self.config.scaling_method}"
            raise ValueError(msg)
