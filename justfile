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

# Package all subprojects into distributable format (wheel and sdist)
# Cleans previous artifacts, builds all packages, and places them in dist/
package:
    #!/usr/bin/env bash
    set -euo pipefail

    # Clean up previous build artifacts
    echo "Cleaning previous build artifacts..."
    rm -rf dist
    for project in {{ subprojects }}; do
        if [ -d "$project" ]; then
            rm -rf "$project/dist"
        fi
    done

    # Create central dist directory
    mkdir -p dist

    # Build all subprojects in dependency order (core first, then others, cli last)
    for project in core plugins stats ui cli; do
        if [ -d "$project" ]; then
            echo "Building $project..."
            (cd "$project" && poetry build)
            # Copy built packages to central dist directory
            if [ -d "$project/dist" ]; then
                cp "$project/dist/"* dist/
            fi
        fi
    done

    echo "All packages built and placed in dist/"
    ls -la dist/

# Install the CLI tool globally using pipx from local sources
install:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Installing update-all CLI via pipx from local sources..."
    # Install the CLI package from the local cli directory
    pipx install ./cli --force
    echo "Installation complete. Run 'update-all --help' to verify."
