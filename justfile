# Update-All: System Update Orchestrator
# Root justfile for monorepo operations

# List of all subprojects
subprojects := "core cli plugins ui stats"

# Default recipe - show available commands
default:
    @just --list

# Install dependencies for all subprojects
install-all:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        echo "Installing dependencies for $project..."
        (cd "$project" && poetry lock && poetry install)
    done

# Run validation across all subprojects
validate: pre-commit lint test
    @echo "All validations passed!"

# Run linters across all subprojects
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ] && [ -f "$project/justfile" ]; then
            echo "Linting $project..."
            (cd "$project" && just lint)
        fi
    done

# Run tests across all subprojects
test:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ] && [ -f "$project/justfile" ]; then
            echo "Testing $project..."
            (cd "$project" && just test)
        fi
    done

# Format code across all subprojects
fmt:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ] && [ -f "$project/justfile" ]; then
            echo "Formatting $project..."
            (cd "$project" && just fmt)
        fi
    done

# Run pre-commit hooks
pre-commit:
    pre-commit run --all-files

# Install pre-commit hooks
pre-commit-install:
    pre-commit install

# Clean build artifacts across all subprojects
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ]; then
            echo "Cleaning $project..."
            rm -rf "$project/.venv" "$project/dist" "$project/.pytest_cache" "$project/.mypy_cache" "$project/.ruff_cache"
            find "$project" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        fi
    done

# Run the CLI (development mode)
run *args:
    cd cli && poetry run update-all {{ args }}

# Run the CLI with only mock plugins (for debugging interactive UI)
run-mock *args:
    cd cli && UPDATE_ALL_DEBUG_MOCK_ONLY=1 poetry run update-all {{ args }}

# Run interactive mode with mock plugins only
run-mock-interactive:
    cd cli && UPDATE_ALL_DEBUG_MOCK_ONLY=1 poetry run update-all run --interactive

# Build all subprojects
build:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ] && [ -f "$project/justfile" ]; then
            echo "Building $project..."
            (cd "$project" && poetry build)
        fi
    done

# Show dependency tree for a subproject
deps project:
    (cd {{ project }} && poetry show --tree)

# Update dependencies for all subprojects
update-deps:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ]; then
            echo "Updating dependencies for $project..."
            (cd "$project" && poetry update)
        fi
    done

# Lock dependencies for all subprojects
lock:
    #!/usr/bin/env bash
    set -euo pipefail
    for project in {{ subprojects }}; do
        if [ -d "$project" ]; then
            echo "Locking dependencies for $project..."
            (cd "$project" && poetry lock)
        fi
    done
