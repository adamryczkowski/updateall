# Database Research for update-all Historical Data Storage

## Overview

This document presents research findings on database solutions suitable for storing historical data about previous runs of the update-all procedure. The requirements are:

- **Lightweight and easy to set up**: Preferably embedded or serverless
- **Small storage footprint**: Data should ideally be compressed
- **Access patterns**: Mostly appends of new records, reads for statistical modeling filtered by plugin, date range, and run type
- **Well-maintained**: Good documentation and community support
- **Python compatible**: Must work well with Python

## Research Date

January 8, 2025

## Database Solutions Comparison

### 1. SQLite (with sqlite-zstd compression)

**Description**: SQLite is the gold standard for embedded relational databases. It's lightweight, reliable, and requires zero configuration. With the sqlite-zstd extension, transparent row-level compression can reduce database size by up to 80%.

**Key Features**:
- Footprint under 1 MB
- Full ACID compliance
- SQL queries with foreign key constraints
- Public domain license
- Built into Python standard library (`sqlite3` module)
- sqlite-zstd extension provides Zstandard compression (LGPL-3.0)

**Pros**:
- ✅ Zero configuration required
- ✅ Built into Python - no external dependencies
- ✅ Excellent documentation and massive community
- ✅ Cross-platform support
- ✅ ACID compliant with transactions
- ✅ sqlite-zstd can reduce storage by 80% while maintaining random access
- ✅ Mature and battle-tested (used in billions of devices)

**Cons**:
- ❌ Not optimized for heavy concurrent writes
- ❌ sqlite-zstd requires additional setup (Rust-based extension)
- ❌ Limited analytical query performance compared to OLAP databases

**Python Package**: `sqlite3` (built-in), `sqlite-zstd` (PyPI)

**Sources**:
- https://www.sqlite.org/
- https://github.com/phiresky/sqlite-zstd

---

### 2. DuckDB

**Description**: DuckDB is an in-process SQL OLAP database designed for analytical workloads. Unlike SQLite which is optimized for transactional data, DuckDB excels at scanning large datasets and performing complex joins, aggregations, and filtering.

**Key Features**:
- Version 1.4 (stable) as of January 2025
- Python client version 1.4.3
- Requires Python 3.9+
- Native Parquet support with compression
- Columnar storage format
- MIT License

**Pros**:
- ✅ Optimized for analytical queries (OLAP)
- ✅ Excellent for statistical modeling workloads
- ✅ Native compression support (Parquet, Zstandard)
- ✅ No server required - embedded
- ✅ Excellent Python integration with pandas/polars
- ✅ Fast aggregations and filtering by date range, plugin, run type
- ✅ Active development with frequent releases

**Cons**:
- ❌ Larger footprint than SQLite
- ❌ Not optimized for high-frequency single-row inserts
- ❌ Relatively newer (less battle-tested than SQLite)

**Python Package**: `duckdb` (PyPI)

**Sources**:
- https://duckdb.org/docs/
- https://duckdb.org/docs/api/python/overview

---

### 3. TinyDB

**Description**: TinyDB is a lightweight document-oriented database written in pure Python. It stores data in JSON format and is designed for small applications that don't need a full SQL database.

**Key Features**:
- Version 4.8.2 (October 2024)
- Pure Python - no external dependencies
- MIT License
- Document-oriented (NoSQL)
- Supports Python 3.8-3.13 and PyPy

**Pros**:
- ✅ Pure Python - extremely easy to install
- ✅ No external dependencies
- ✅ Simple API for document storage
- ✅ Extensible with custom storage backends
- ✅ 100% test coverage
- ✅ Good for small datasets

**Cons**:
- ❌ No built-in compression
- ❌ Not suitable for large datasets (loads entire DB into memory)
- ❌ No SQL support - limited query capabilities
- ❌ Project in maintenance mode (no new features planned)
- ❌ Slower for complex queries compared to SQL databases

**Python Package**: `tinydb` (PyPI)

**Sources**:
- https://pypi.org/project/tinydb/
- https://tinydb.readthedocs.io/

---

### 4. LMDB (Lightning Memory-Mapped Database)

**Description**: LMDB is a key-value store known for ultra-fast read performance and minimal memory usage. It uses memory-mapped architecture to access data directly from disk, making reads almost as fast as RAM access.

**Key Features**:
- Version 1.7.5 (October 2025)
- OLDAP-2.8 License (permissive)
- Memory-mapped architecture
- ACID compliant
- Multi-threaded reader support

**Pros**:
- ✅ Exceptional read performance
- ✅ Minimal memory footprint
- ✅ Strong consistency with zero data loss on crashes
- ✅ ACID compliant
- ✅ Excellent for read-heavy workloads
- ✅ Small binary footprint

**Cons**:
- ❌ Key-value store only - no SQL support
- ❌ No built-in compression
- ❌ Requires manual serialization of complex data structures
- ❌ Not suitable for complex analytical queries
- ❌ Steeper learning curve for relational data modeling

**Python Package**: `lmdb` (PyPI)

**Sources**:
- https://pypi.org/project/lmdb/
- https://lmdb.readthedocs.io/

---

### 5. Parquet Files with Polars/PyArrow

**Description**: Apache Parquet is a columnar storage format designed for efficient data storage and retrieval. Combined with Polars or PyArrow, it provides excellent compression and fast analytical queries without a traditional database.

**Key Features**:
- Columnar storage format
- Built-in compression (Snappy, Zstandard, LZ4)
- Schema evolution support
- Polars: Rust-Python hybrid for fast data processing

**Pros**:
- ✅ Excellent compression ratios
- ✅ Optimized for analytical workloads
- ✅ No database server required
- ✅ Polars is extremely fast (faster than pandas)
- ✅ Easy to partition by date/plugin for efficient filtering
- ✅ Widely supported in data ecosystem

**Cons**:
- ❌ Not a database - no ACID transactions
- ❌ Append operations require rewriting files (or partitioning strategy)
- ❌ No SQL interface (though DuckDB can query Parquet files)
- ❌ Requires careful file management for append-heavy workloads

**Python Packages**: `polars`, `pyarrow` (PyPI)

**Sources**:
- https://docs.pola.rs/
- https://arrow.apache.org/docs/python/

---

## Comparison Matrix

| Feature | SQLite + zstd | DuckDB | TinyDB | LMDB | Parquet + Polars |
|---------|---------------|--------|--------|------|------------------|
| **License** | Public Domain / LGPL-3.0 | MIT | MIT | OLDAP-2.8 | Apache 2.0 |
| **Storage Type** | Relational | Relational (OLAP) | Document | Key-Value | Columnar Files |
| **Compression** | ✅ (with extension) | ✅ Native | ❌ | ❌ | ✅ Native |
| **SQL Support** | ✅ Full | ✅ Full | ❌ | ❌ | ❌ (via DuckDB) |
| **ACID Compliance** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Analytical Queries** | ⚠️ Moderate | ✅ Excellent | ❌ Poor | ❌ Poor | ✅ Excellent |
| **Append Performance** | ✅ Good | ⚠️ Moderate | ✅ Good | ✅ Excellent | ⚠️ Requires strategy |
| **Python Integration** | ✅ Built-in | ✅ Excellent | ✅ Pure Python | ✅ Good | ✅ Excellent |
| **Setup Complexity** | ⚠️ Low-Medium | ✅ Low | ✅ Very Low | ⚠️ Medium | ⚠️ Medium |
| **Maturity** | ✅ Very High | ⚠️ Medium | ✅ High | ✅ High | ✅ High |

## Recommendation

For the update-all historical data storage use case, **DuckDB** is the recommended primary choice, with **SQLite + sqlite-zstd** as a strong alternative.

### Primary Recommendation: DuckDB

**Rationale**:
1. **Optimized for our access pattern**: The primary use case involves statistical modeling and filtering by plugin, date range, and run type - exactly what OLAP databases excel at.
2. **Native compression**: Built-in support for compressed storage formats reduces footprint.
3. **Excellent Python integration**: First-class Python support with pandas/polars interoperability.
4. **SQL support**: Full SQL capabilities for complex analytical queries.
5. **Active development**: Frequent releases and growing community.

### Alternative: SQLite + sqlite-zstd

**When to choose SQLite instead**:
1. If append performance is critical and writes are very frequent
2. If you need maximum compatibility (SQLite is everywhere)
3. If you prefer using Python's built-in sqlite3 module
4. If the analytical query complexity is low

### Implementation Notes

For DuckDB:
```python
import duckdb

# Create persistent database
conn = duckdb.connect('update_all_history.duckdb')

# Create table with appropriate schema
conn.execute("""
    CREATE TABLE IF NOT EXISTS run_history (
        id INTEGER PRIMARY KEY,
        timestamp TIMESTAMP,
        plugin_name VARCHAR,
        run_type VARCHAR,  -- 'estimate', 'download', 'update'
        download_size BIGINT,
        cpu_time_user DOUBLE,
        cpu_time_kernel DOUBLE,
        wall_clock_time DOUBLE,
        peak_memory_bytes BIGINT,
        io_read_bytes BIGINT,
        io_write_bytes BIGINT,
        network_bytes BIGINT,
        success BOOLEAN,
        error_message VARCHAR
    )
""")

# Efficient filtering for statistical modeling
results = conn.execute("""
    SELECT * FROM run_history
    WHERE plugin_name = ?
    AND timestamp BETWEEN ? AND ?
    AND run_type = ?
""", ['apt', '2024-01-01', '2025-01-01', 'update']).fetchall()
```

## Performance Crossover Analysis: SQLite vs DuckDB

This section analyzes at what database size the performance difference between SQLite and DuckDB becomes significant, and estimates the storage footprint at that point.

### Key Findings from Benchmarks

Based on research from multiple benchmark sources (January 2025):

#### Performance Crossover Point

| Row Count | SQLite Performance | DuckDB Performance | Winner |
|-----------|-------------------|-------------------|--------|
| < 10,000 | Excellent | Good | SQLite (simpler) |
| 10,000 - 100,000 | Good | Good | Comparable |
| 100,000 - 1,000,000 | Moderate | Good | DuckDB starts winning |
| > 1,000,000 | Slow for analytics | Excellent | DuckDB (8x faster) |

**The crossover point is approximately 100,000 to 1,000,000 rows** for analytical queries (aggregations, filtering, statistical modeling). For simple CRUD operations, SQLite remains competitive even at larger scales.

#### Benchmark at 10 Million Rows (Analytical Query)

A benchmark comparing monthly sales aggregation query performance:

| Metric | DuckDB | SQLite | Ratio |
|--------|--------|--------|-------|
| Query Time | 2.3 seconds | 18.7 seconds | DuckDB 8x faster |
| Memory Usage | 180 MB | 420 MB | DuckDB 2.3x less |
| CPU Utilization | 65% (4 cores) | 98% (1 core) | DuckDB uses parallelism |

#### Import Performance at 50 Million Rows

DuckDB imports large CSV datasets approximately **7x faster** than SQLite due to parallel processing capabilities.

### Storage Footprint Estimates for update-all

#### Assumptions for update-all Use Case

- **Plugins**: ~20 plugins
- **Runs per week**: 2-3 update runs
- **Steps per run**: 3 (estimate, download, update)
- **Records per run**: 20 plugins × 3 steps = 60 records
- **Records per year**: 60 × 3 × 52 = ~9,360 records/year
- **Record size**: ~500 bytes (all metrics, timestamps, plugin names)

#### Estimated Timeline to Crossover Point

| Timeframe | Approximate Rows | Recommended Database |
|-----------|------------------|---------------------|
| 1 year | ~10,000 | Either (SQLite simpler) |
| 5 years | ~50,000 | Either (comparable) |
| 10 years | ~100,000 | DuckDB starts to shine |
| 20+ years | ~200,000+ | DuckDB recommended |

**Conclusion**: For typical update-all usage, the crossover point would be reached after approximately **10-15 years** of continuous operation.

#### Storage Footprint at Crossover Point (~100,000 rows)

| Database | Uncompressed | Compressed | Notes |
|----------|-------------|------------|-------|
| SQLite (plain) | ~50 MB | N/A | No built-in compression |
| SQLite + sqlite-zstd | ~50 MB | ~10-15 MB | 70-80% compression ratio |
| DuckDB | ~30-40 MB | ~8-12 MB | Native columnar compression |

**Key observations**:
1. At 100,000 rows, both databases have very small footprints (< 50 MB)
2. DuckDB's columnar format is inherently more compact for analytical data
3. sqlite-zstd achieves similar compression but requires additional setup
4. Storage is unlikely to be a concern for either solution in this use case

### Recommendation Based on Scale Analysis

Given the update-all use case characteristics:

1. **For immediate deployment**: **SQLite** is sufficient
   - Simpler setup (built into Python)
   - Adequate performance for years of data
   - Add sqlite-zstd later if compression becomes important

2. **For long-term planning**: **DuckDB** is the better investment
   - Better analytical query performance from day one
   - Native compression without extensions
   - Will scale better as data grows
   - Better integration with statistical modeling libraries (pandas, polars)

3. **Practical recommendation**: Start with **DuckDB**
   - The performance difference is negligible at small scales
   - No need to migrate later when data grows
   - Better suited for the statistical modeling use case
   - Minimal additional complexity over SQLite

## Sources Used

1. Explo - Top 8 Embedded SQL Databases in 2025: https://www.explo.co/blog/embedded-sql-databases
2. DuckDB Documentation: https://duckdb.org/docs/
3. SQLite Official Website: https://www.sqlite.org/
4. sqlite-zstd GitHub: https://github.com/phiresky/sqlite-zstd
5. TinyDB PyPI: https://pypi.org/project/tinydb/
6. LMDB PyPI: https://pypi.org/project/lmdb/
7. Polars Documentation: https://docs.pola.rs/
8. MarkAICode - SQLite vs DuckDB Performance Comparison: https://markaicode.com/sqlite-vs-duckdb-performance-comparison/
9. KDnuggets - DuckDB vs SQLite Benchmarks: https://www.kdnuggets.com/duckdb-vs-sqlite-benchmarks
