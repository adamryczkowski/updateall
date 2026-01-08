# Time Series Forecasting Research for update-all Prediction Modeling

## Overview

This document presents research findings on time-series forecasting algorithms suitable for building advanced statistical models based on historical data from the update-all system. The key insight is that the historical data should be treated as **time series** rather than aggregated for regression, preserving the temporal structure and avoiding information loss.

## Requirements

### Target Variables (Measured Features per Plugin Run)
- **Network traffic** (bytes downloaded/uploaded)
- **CPU time** (user + kernel, in seconds)
- **Wall-clock time** (elapsed time in seconds)
- **Peak memory consumption** (max RSS in bytes)
- **IO statistics** (read/write bytes)

### Predictor Variables (Covariates)
- Time period from the update run
- Estimated download size reported by plugin (if available)
- Estimated CPU time reported by plugin (if available)
- Plugin name (categorical)
- Run type (estimate, download, update)
- Number of packages managed by the plugin
- Day of week, time of day (seasonality)
- Time since last update

### Key Requirements
- **Time-series approach**: Preserve temporal structure, no aggregation
- **Multivariate support**: Multiple target variables per observation
- **Confidence/prediction intervals**: Not just point estimates
- **Covariates support**: Use predictor variables as external inputs

## Research Date

January 8, 2025

## Time Series Forecasting Algorithms Comparison

### 1. Vector Autoregression (VAR) / VARIMA

**Description**: VAR is a multivariate extension of autoregressive models that captures linear interdependencies among multiple time series. VARIMA adds integrated and moving average components.

**Key Features**:
- Available in statsmodels 0.14.6
- Native multivariate support
- Captures cross-correlations between variables
- Confidence intervals via forecast error variance decomposition

**Implementation**:
```python
from statsmodels.tsa.api import VAR
import pandas as pd

# Multivariate time series: network, cpu_time, wall_time, memory
data = pd.DataFrame({
    'network_bytes': network_series,
    'cpu_time': cpu_series,
    'wall_time': wall_series,
    'peak_memory': memory_series
})

model = VAR(data)
results = model.fit(maxlags=5, ic='aic')

# Forecast with confidence intervals
forecast = results.forecast(data.values[-results.k_ar:], steps=5)
forecast_ci = results.forecast_interval(data.values[-results.k_ar:], steps=5, alpha=0.05)
# forecast_ci returns (point_forecast, lower_bound, upper_bound)
```

**Pros**:
- ✅ Native multivariate support
- ✅ Captures cross-variable dependencies
- ✅ Built-in confidence intervals
- ✅ Well-established statistical theory
- ✅ Interpretable coefficients (Granger causality)
- ✅ Impulse response analysis

**Cons**:
- ❌ Assumes linear relationships
- ❌ Requires stationary data (or differencing)
- ❌ Limited with exogenous covariates (use VARMAX)
- ❌ Can overfit with many variables/lags
- ❌ Not suitable for very long-range forecasts

**Best For**: Short-term multivariate forecasting with interpretable relationships

**Sources**:
- https://www.statsmodels.org/stable/vector_ar.html

---

### 2. State Space Models (Kalman Filter)

**Description**: State space models provide a flexible framework for time series analysis using the Kalman filter. They can represent many models (ARIMA, structural time series, dynamic factor models) in a unified framework.

**Key Features**:
- Available in statsmodels 0.14.6 (`statsmodels.tsa.statespace`)
- Handles missing observations naturally
- Provides filtered, smoothed, and forecast estimates
- Full uncertainty quantification

**Implementation**:
```python
from statsmodels.tsa.statespace.structural import UnobservedComponents
import numpy as np

# Structural time series model with trend and seasonality
model = UnobservedComponents(
    endog=cpu_time_series,
    level='local linear trend',
    seasonal=7,  # Weekly seasonality
    exog=covariates  # External predictors
)
results = model.fit()

# Forecast with prediction intervals
forecast = results.get_forecast(steps=10)
forecast_mean = forecast.predicted_mean
forecast_ci = forecast.conf_int(alpha=0.1)  # 90% CI
```

**Pros**:
- ✅ Handles missing data naturally
- ✅ Flexible model specification
- ✅ Full Bayesian uncertainty quantification
- ✅ Supports exogenous variables
- ✅ Online updating (Kalman filter)
- ✅ Decomposition into trend, seasonal, irregular

**Cons**:
- ❌ Primarily univariate (multivariate requires custom implementation)
- ❌ Assumes linear Gaussian dynamics
- ❌ Can be computationally intensive
- ❌ Requires careful model specification

**Best For**: Univariate forecasting with trend/seasonality, missing data handling

**Sources**:
- https://www.statsmodels.org/stable/statespace.html

---

### 3. Darts Library (Unified Time Series Framework)

**Description**: Darts is a comprehensive Python library for time series forecasting that provides a unified interface to many models, from classical (ARIMA, ETS) to deep learning (TFT, N-BEATS). It has native support for probabilistic forecasting and multivariate time series.

**Key Features**:
- Version 0.40.0 (December 2025)
- Apache-2.0 License
- Python 3.10+ support
- 30+ forecasting models
- Native probabilistic forecasting
- Conformal prediction support
- Past/future covariates support

**Models Available**:
- Classical: ARIMA, VARIMA, ExponentialSmoothing, Theta, Prophet
- Machine Learning: LightGBM, XGBoost, CatBoost, RandomForest
- Deep Learning: TFT, N-BEATS, N-HiTS, TCN, Transformer, RNN/LSTM

**Implementation**:
```python
from darts import TimeSeries
from darts.models import TFTModel
from darts.utils.likelihood_models import QuantileRegression

# Create multivariate time series
series = TimeSeries.from_dataframe(
    df,
    time_col='timestamp',
    value_cols=['network_bytes', 'cpu_time', 'wall_time', 'peak_memory']
)

# Temporal Fusion Transformer with quantile regression
model = TFTModel(
    input_chunk_length=24,
    output_chunk_length=12,
    likelihood=QuantileRegression(quantiles=[0.05, 0.5, 0.95]),
    add_relative_index=True
)

# Train with covariates
model.fit(
    series=series,
    past_covariates=past_covariates,
    future_covariates=future_covariates
)

# Probabilistic forecast
forecast = model.predict(n=10, num_samples=100)
# Get quantiles for prediction intervals
lower = forecast.quantile(0.05)
median = forecast.quantile(0.5)
upper = forecast.quantile(0.95)
```

**Pros**:
- ✅ Unified API for 30+ models
- ✅ Native multivariate support
- ✅ Probabilistic forecasting built-in
- ✅ Conformal prediction for calibrated intervals
- ✅ Past and future covariates support
- ✅ Excellent documentation and examples
- ✅ Active development (6M downloads)

**Cons**:
- ❌ Deep learning models require PyTorch
- ❌ Can be heavyweight for simple use cases
- ❌ Learning curve for full feature set

**Best For**: Production systems requiring flexibility, multivariate forecasting with covariates

**Sources**:
- https://unit8co.github.io/darts/

---

### 4. Temporal Fusion Transformer (TFT)

**Description**: TFT is a state-of-the-art deep learning architecture specifically designed for multi-horizon time series forecasting. It combines high-capacity modeling with interpretability through attention mechanisms.

**Key Features**:
- Available in Darts, PyTorch Forecasting, GluonTS
- Handles multiple input types (static, known future, observed)
- Variable selection for interpretability
- Multi-horizon quantile forecasts

**Implementation**:
```python
from darts.models import TFTModel
from darts.utils.likelihood_models import QuantileRegression

# TFT with static covariates (plugin name) and dynamic covariates
model = TFTModel(
    input_chunk_length=30,
    output_chunk_length=7,
    hidden_size=64,
    lstm_layers=1,
    num_attention_heads=4,
    dropout=0.1,
    likelihood=QuantileRegression(quantiles=[0.1, 0.25, 0.5, 0.75, 0.9])
)

model.fit(
    series=target_series,
    past_covariates=past_covariates,  # Historical features
    future_covariates=future_covariates,  # Known future (day of week, etc.)
    static_covariates=static_covariates  # Plugin name, run type
)

# Get interpretable attention weights
attention_weights = model.get_attention_weights()
```

**Pros**:
- ✅ State-of-the-art accuracy
- ✅ Handles all covariate types
- ✅ Built-in interpretability (attention)
- ✅ Multi-horizon quantile forecasts
- ✅ Variable importance scores
- ✅ Handles heterogeneous time series

**Cons**:
- ❌ Requires substantial training data
- ❌ Computationally expensive
- ❌ Complex hyperparameter tuning
- ❌ Overkill for simple patterns

**Best For**: Complex multivariate forecasting with many covariates, when interpretability matters

**Sources**:
- https://arxiv.org/abs/1912.09363
- https://unit8co.github.io/darts/generated_api/darts.models.forecasting.tft_model.html

---

### 5. N-BEATS / N-HiTS

**Description**: N-BEATS (Neural Basis Expansion Analysis for Time Series) and N-HiTS are deep learning architectures that achieve excellent performance through basis expansion and hierarchical interpolation.

**Key Features**:
- Available in Darts, NeuralForecast
- Interpretable decomposition (trend, seasonality)
- No feature engineering required
- Fast inference

**Implementation**:
```python
from darts.models import NBEATSModel
from darts.utils.likelihood_models import QuantileRegression

model = NBEATSModel(
    input_chunk_length=30,
    output_chunk_length=7,
    generic_architecture=False,  # Use interpretable architecture
    num_stacks=2,
    num_blocks=3,
    num_layers=4,
    layer_widths=256,
    likelihood=QuantileRegression()
)

model.fit(series)
forecast = model.predict(n=7, num_samples=100)
```

**Pros**:
- ✅ Excellent accuracy without feature engineering
- ✅ Interpretable decomposition
- ✅ Fast training and inference
- ✅ Works well with limited data
- ✅ Probabilistic forecasting support

**Cons**:
- ❌ Primarily univariate (multivariate via stacking)
- ❌ Limited covariate support
- ❌ Requires PyTorch

**Best For**: Univariate forecasting when accuracy is paramount

**Sources**:
- https://arxiv.org/abs/1905.10437 (N-BEATS)
- https://arxiv.org/abs/2201.12886 (N-HiTS)

---

### 6. Prophet / NeuralProphet

**Description**: Prophet is Facebook's time series forecasting library designed for business time series with strong seasonality. NeuralProphet extends it with neural network components.

**Key Features**:
- Prophet: Additive model with trend, seasonality, holidays
- NeuralProphet: Adds AR-Net, lagged regressors, neural network
- Automatic changepoint detection
- Uncertainty intervals via MCMC or MAP

**Implementation**:
```python
from prophet import Prophet
import pandas as pd

# Prophet with uncertainty intervals
df = pd.DataFrame({
    'ds': timestamps,
    'y': cpu_time_series
})

model = Prophet(
    interval_width=0.9,  # 90% prediction interval
    yearly_seasonality=True,
    weekly_seasonality=True
)
model.add_regressor('estimated_download_size')  # Covariate
model.fit(df)

future = model.make_future_dataframe(periods=30)
forecast = model.predict(future)
# forecast contains yhat, yhat_lower, yhat_upper
```

**Pros**:
- ✅ Easy to use, minimal tuning
- ✅ Handles missing data and outliers
- ✅ Built-in uncertainty quantification
- ✅ Interpretable components
- ✅ Supports external regressors

**Cons**:
- ❌ Primarily univariate
- ❌ Limited for complex patterns
- ❌ Can be slow for large datasets
- ❌ Intervals can be overconfident

**Best For**: Business forecasting with seasonality, quick prototyping

**Sources**:
- https://facebook.github.io/prophet/
- https://neuralprophet.com/

---

### 7. MAPIE Time Series (Conformal Prediction)

**Description**: MAPIE provides conformal prediction methods for time series, offering prediction intervals with guaranteed coverage. It wraps any base forecaster to add calibrated uncertainty.

**Key Features**:
- Version 1.2.0 (January 2025)
- BSD-3-Clause License
- EnbPI (Ensemble Batch Prediction Intervals) method
- Works with any sklearn-compatible forecaster

**Implementation**:
```python
from mapie.time_series_regression import MapieTimeSeriesRegressor
from sklearn.ensemble import RandomForestRegressor

# Base forecaster
base_model = RandomForestRegressor(n_estimators=100)

# Wrap with MAPIE for time series
mapie_ts = MapieTimeSeriesRegressor(
    base_model,
    method="enbpi",  # Ensemble Batch Prediction Intervals
    cv="prefit"
)

# Fit and predict with intervals
mapie_ts.fit(X_train, y_train)
y_pred, y_pis = mapie_ts.predict(X_test, alpha=0.1)  # 90% PI

# y_pis[:, 0, 0] = lower bound
# y_pis[:, 1, 0] = upper bound
```

**Pros**:
- ✅ Guaranteed coverage probability
- ✅ Model-agnostic
- ✅ Works with any sklearn forecaster
- ✅ Adaptive to non-stationarity
- ✅ No distributional assumptions

**Cons**:
- ❌ Requires calibration data
- ❌ Intervals may be conservative
- ❌ Limited to regression-style forecasting
- ❌ Not native multivariate

**Best For**: Adding calibrated intervals to any forecaster

**Sources**:
- https://mapie.readthedocs.io/en/stable/theoretical_description_time_series.html

---

### 8. GluonTS (Probabilistic Time Series)

**Description**: GluonTS is Amazon's library for probabilistic time series modeling. It includes many deep learning models and the new Chronos foundation model for zero-shot forecasting.

**Key Features**:
- From AWS Labs
- 5.1k GitHub stars
- DeepAR, DeepState, Transformer models
- Chronos: Zero-shot forecasting foundation model
- Native probabilistic predictions

**Implementation**:
```python
from gluonts.dataset.pandas import PandasDataset
from gluonts.torch.model.deepar import DeepAREstimator
from gluonts.evaluation import make_evaluation_predictions

# Create dataset
dataset = PandasDataset.from_long_dataframe(
    df,
    target="cpu_time",
    item_id="plugin_name"
)

# DeepAR with probabilistic output
estimator = DeepAREstimator(
    prediction_length=7,
    freq="D",
    num_layers=2,
    hidden_size=40,
    dropout_rate=0.1
)

predictor = estimator.train(dataset)

# Get probabilistic forecasts
forecast_it, ts_it = make_evaluation_predictions(
    dataset=dataset,
    predictor=predictor,
    num_samples=100
)

for forecast in forecast_it:
    mean = forecast.mean
    quantile_10 = forecast.quantile(0.1)
    quantile_90 = forecast.quantile(0.9)
```

**Pros**:
- ✅ Excellent probabilistic models
- ✅ Chronos for zero-shot forecasting
- ✅ Handles multiple time series
- ✅ AWS integration (SageMaker)
- ✅ Active development

**Cons**:
- ❌ Steeper learning curve
- ❌ Requires PyTorch/MXNet
- ❌ Less unified API than Darts

**Best For**: Production probabilistic forecasting, zero-shot with Chronos

**Sources**:
- https://github.com/awslabs/gluonts
- https://ts.gluon.ai/

---

### 9. sktime (Unified Time Series Framework)

**Description**: sktime is a unified framework for machine learning with time series, providing scikit-learn compatible tools for forecasting, classification, and clustering.

**Key Features**:
- Version 0.40.1 (November 2025)
- BSD-3-Clause License
- 9.4k GitHub stars, 36M downloads
- Unified sklearn-like API
- Supports forecasting, classification, clustering

**Implementation**:
```python
from sktime.forecasting.compose import make_reduction
from sktime.forecasting.model_selection import temporal_train_test_split
from sklearn.ensemble import GradientBoostingRegressor

# Reduce forecasting to regression
forecaster = make_reduction(
    GradientBoostingRegressor(),
    window_length=10,
    strategy="recursive"
)

# Fit and predict
forecaster.fit(y_train)
y_pred = forecaster.predict(fh=[1, 2, 3, 4, 5])

# With prediction intervals (using ConformalIntervals)
from sktime.forecasting.conformal import ConformalIntervals

conformal_forecaster = ConformalIntervals(
    forecaster,
    coverage=0.9
)
conformal_forecaster.fit(y_train)
y_pred_int = conformal_forecaster.predict_interval(fh=[1, 2, 3, 4, 5])
```

**Pros**:
- ✅ sklearn-compatible API
- ✅ Unified interface for many tasks
- ✅ Conformal prediction intervals
- ✅ Excellent documentation
- ✅ Large community

**Cons**:
- ❌ Less focus on deep learning
- ❌ Multivariate support still developing
- ❌ Can be verbose for complex pipelines

**Best For**: sklearn users, unified ML pipeline with time series

**Sources**:
- https://www.sktime.net/
- https://pypi.org/project/sktime/

---

## Comparison Matrix

| Algorithm | Multivariate | Covariates | Intervals | Complexity | Maturity | Best For |
|-----------|--------------|------------|-----------|------------|----------|----------|
| **VAR/VARIMA** | ✅ Native | ⚠️ VARMAX | ✅ Built-in | Low | ✅ High | Short-term multivariate |
| **State Space** | ⚠️ Limited | ✅ Yes | ✅ Built-in | Medium | ✅ High | Trend/seasonality |
| **Darts** | ✅ Native | ✅ Full | ✅ Native | Medium | ✅ High | Production systems |
| **TFT** | ✅ Native | ✅ Full | ✅ Quantile | High | ⚠️ Medium | Complex patterns |
| **N-BEATS** | ⚠️ Stacking | ❌ Limited | ✅ Quantile | Medium | ⚠️ Medium | Univariate accuracy |
| **Prophet** | ❌ No | ✅ Regressors | ✅ MCMC | Low | ✅ High | Business forecasting |
| **MAPIE TS** | ❌ No | ✅ Features | ✅ Conformal | Low | ⚠️ Medium | Calibrated intervals |
| **GluonTS** | ✅ Native | ✅ Yes | ✅ Probabilistic | High | ✅ High | Probabilistic forecasting |
| **sktime** | ⚠️ Developing | ✅ Yes | ✅ Conformal | Medium | ✅ High | sklearn integration |

## Recommendation

For the update-all prediction system with multivariate time series (network traffic, CPU time, wall time, peak memory), a **tiered approach** is recommended:

### Primary Recommendation: Darts with TFT or LightGBM

**Rationale**:
1. **Native multivariate support**: Can forecast all metrics simultaneously
2. **Full covariate support**: Past, future, and static covariates
3. **Probabilistic forecasting**: Quantile regression for prediction intervals
4. **Conformal prediction**: Calibrated intervals with guaranteed coverage
5. **Unified API**: Easy to experiment with different models
6. **Production-ready**: Well-documented, actively maintained

### Implementation Strategy

```python
from darts import TimeSeries
from darts.models import LightGBMModel
from darts.utils.likelihood_models import QuantileRegression

# Create multivariate time series from historical data
target_series = TimeSeries.from_dataframe(
    history_df,
    time_col='timestamp',
    value_cols=['network_bytes', 'cpu_time', 'wall_time', 'peak_memory']
)

# Past covariates (observed historical features)
past_covariates = TimeSeries.from_dataframe(
    history_df,
    time_col='timestamp',
    value_cols=['estimated_download_size', 'estimated_cpu_time', 'num_packages']
)

# Static covariates (per-plugin)
static_covariates = pd.DataFrame({
    'plugin_name': ['apt', 'snap', 'pip', ...],
    'run_type': ['update', 'download', 'estimate', ...]
})

# LightGBM with quantile regression for fast, accurate forecasting
model = LightGBMModel(
    lags=30,  # Use last 30 observations
    lags_past_covariates=30,
    output_chunk_length=7,
    likelihood='quantile',
    quantiles=[0.05, 0.25, 0.5, 0.75, 0.95]
)

model.fit(
    series=target_series,
    past_covariates=past_covariates
)

# Forecast with prediction intervals
forecast = model.predict(n=7, num_samples=100)

# Extract intervals
lower_5 = forecast.quantile(0.05)
median = forecast.quantile(0.5)
upper_95 = forecast.quantile(0.95)

# Report: "Estimated CPU time: 45s (90% CI: 30-65s)"
```

### Alternative: VAR for Simplicity

For a simpler approach with fewer dependencies:

```python
from statsmodels.tsa.api import VAR
import pandas as pd

# Multivariate time series
data = pd.DataFrame({
    'network_bytes': network_series,
    'cpu_time': cpu_series,
    'wall_time': wall_series,
    'peak_memory': memory_series
}, index=timestamps)

# Fit VAR model
model = VAR(data)
results = model.fit(maxlags=10, ic='aic')

# Forecast with intervals
forecast, lower, upper = results.forecast_interval(
    data.values[-results.k_ar:],
    steps=7,
    alpha=0.1  # 90% CI
)
```

### Per-Plugin Hierarchical Approach

For per-plugin forecasting with shared learning:

```python
from darts.models import TFTModel

# Train global model on all plugins
global_model = TFTModel(
    input_chunk_length=30,
    output_chunk_length=7,
    likelihood=QuantileRegression()
)

# Fit on all plugin time series
global_model.fit(
    series=[series_apt, series_snap, series_pip, ...],
    past_covariates=[cov_apt, cov_snap, cov_pip, ...],
    static_covariates=plugin_metadata  # Plugin-specific features
)

# Predict for specific plugin
forecast_apt = global_model.predict(
    n=7,
    series=series_apt,
    past_covariates=cov_apt
)
```

## Sources Used

1. statsmodels VAR: https://www.statsmodels.org/stable/vector_ar.html
2. statsmodels State Space: https://www.statsmodels.org/stable/statespace.html
3. Darts Documentation: https://unit8co.github.io/darts/
4. Temporal Fusion Transformer Paper: https://arxiv.org/abs/1912.09363
5. N-BEATS Paper: https://arxiv.org/abs/1905.10437
6. Prophet Documentation: https://facebook.github.io/prophet/
7. MAPIE Time Series: https://mapie.readthedocs.io/en/stable/
8. GluonTS GitHub: https://github.com/awslabs/gluonts
9. sktime Documentation: https://www.sktime.net/
10. NeuralProphet: https://neuralprophet.com/
