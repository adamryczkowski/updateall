"""Test fixtures for modeling tests - Synthetic data generators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest


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
    rng = np.random.default_rng(seed)

    # Generate timestamps with consistent daily frequency
    # Darts requires regular time series for proper handling
    start_date = datetime.now(tz=UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=num_samples)
    timestamps = [start_date + timedelta(days=i) for i in range(num_samples)]

    # Generate wall clock times with trend + seasonality + noise
    days_from_start = np.array([(t - start_date).days for t in timestamps])
    trend_component = trend * days_from_start
    day_of_week = np.array([t.weekday() for t in timestamps])
    seasonality = seasonality_amplitude * np.sin(2 * np.pi * day_of_week / 7)
    noise = rng.normal(0, noise_std, num_samples)

    wall_clock = base_wall_clock + trend_component + seasonality + noise
    wall_clock = np.maximum(wall_clock, 1.0)  # Ensure positive

    # Generate correlated metrics
    cpu_time = wall_clock * (0.4 + 0.2 * rng.random(num_samples))
    memory_peak = (100 + 50 * rng.random(num_samples)) * 1024 * 1024
    download_size = (20 + 30 * rng.random(num_samples)) * 1024 * 1024

    # Generate package counts
    packages_total = 100 + days_from_start // 10
    packages_updated = rng.poisson(5, num_samples)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "plugin_name": plugin_name,
            "wall_clock_seconds": wall_clock,
            "cpu_user_seconds": cpu_time,
            "memory_peak_bytes": memory_peak.astype(int),
            "download_size_bytes": download_size.astype(int),
            "packages_total": packages_total,
            "packages_updated": packages_updated,
            "status": "success",
        }
    )


@pytest.fixture
def synthetic_data() -> pd.DataFrame:
    """Generate synthetic plugin data for testing (100 samples)."""
    return generate_synthetic_plugin_data(num_samples=100)


@pytest.fixture
def small_synthetic_data() -> pd.DataFrame:
    """Generate small synthetic dataset (15 samples - edge case)."""
    return generate_synthetic_plugin_data(num_samples=15)


@pytest.fixture
def minimal_synthetic_data() -> pd.DataFrame:
    """Generate minimal synthetic dataset (5 samples - below threshold)."""
    return generate_synthetic_plugin_data(num_samples=5)


@pytest.fixture
def noisy_synthetic_data() -> pd.DataFrame:
    """Generate noisy synthetic data for robustness testing."""
    return generate_synthetic_plugin_data(num_samples=100, noise_std=20.0)


@pytest.fixture
def trending_synthetic_data() -> pd.DataFrame:
    """Generate data with strong trend for trend detection testing."""
    return generate_synthetic_plugin_data(num_samples=100, trend=0.5)


@pytest.fixture
def data_with_missing_values() -> pd.DataFrame:
    """Generate data with some missing values."""
    df = generate_synthetic_plugin_data(num_samples=100)
    # Set some values to NaN
    rng = np.random.default_rng(42)
    missing_indices = rng.choice(len(df), size=10, replace=False)
    df.loc[missing_indices, "wall_clock_seconds"] = np.nan
    return df


@pytest.fixture
def data_with_outliers() -> pd.DataFrame:
    """Generate data with outliers."""
    df = generate_synthetic_plugin_data(num_samples=100)
    # Add some extreme outliers
    df.loc[0, "wall_clock_seconds"] = 10000.0
    df.loc[1, "wall_clock_seconds"] = 10000.0
    df.loc[2, "wall_clock_seconds"] = 0.001
    return df
