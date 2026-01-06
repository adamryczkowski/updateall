# Common justfile for all subprojects
# Import this file in each subproject's justfile

# Default recipe - show available commands
default:
    @just --list

# Install dependencies
install:
    poetry install

# Run tests
test *args:
    poetry run pytest {{ args }}

# Run tests with coverage
test-cov:
    poetry run pytest --cov --cov-report=term-missing --cov-report=html

# Format code with ruff
fmt:
    poetry run ruff format .
    poetry run ruff check --fix .

# Run linters
lint:
    poetry run ruff check .
    poetry run ruff format --check .

# Run type checking
typecheck:
    poetry run mypy .

# Run all validations
validate: lint typecheck test
    @echo "All validations passed!"

# Clean build artifacts
clean:
    rm -rf dist .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Build the package
build:
    poetry build

# Show dependency tree
deps:
    poetry show --tree

# Update dependencies
update:
    poetry update

# Lock dependencies
lock:
    poetry lock

# Add a dependency
add *args:
    poetry add {{ args }}

# Add a dev dependency
add-dev *args:
    poetry add --group dev {{ args }}

# Remove a dependency
remove *args:
    poetry remove {{ args }}
