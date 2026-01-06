# Example External Plugins

This directory contains example external plugins that demonstrate the Update-All streaming protocol.

## Available Examples

### Bash Plugin (`example-bash-plugin.sh`)

A complete example plugin written in Bash that demonstrates:
- All required and optional CLI commands
- Streaming progress events
- Download and execute phases
- Dry-run mode support

**Usage:**
```bash
# Make executable
chmod +x example-bash-plugin.sh

# Check if applicable
./example-bash-plugin.sh is-applicable

# Run with dry-run
./example-bash-plugin.sh update --dry-run

# Download only
./example-bash-plugin.sh download

# Full update
./example-bash-plugin.sh update
```

### Python Plugin (`example-python-plugin.py`)

A complete example plugin written in Python that demonstrates:
- All required and optional CLI commands
- Streaming progress events with proper JSON formatting
- Download and execute phases
- Dry-run mode support
- Type hints and modern Python practices

**Usage:**
```bash
# Make executable
chmod +x example-python-plugin.py

# Check if applicable
./example-python-plugin.py is-applicable

# Run with dry-run
./example-python-plugin.py update --dry-run

# Download only
./example-python-plugin.py download

# Full update
./example-python-plugin.py update
```

## Validating Plugins

Use the Update-All validation tool to check your plugin:

```bash
# Validate a plugin
update-all plugins validate ./example-bash-plugin.sh

# Validate with verbose output
update-all plugins validate ./example-python-plugin.py --verbose
```

## Streaming Protocol

External plugins communicate with Update-All through stdout and stderr:

| Stream | Purpose | Format |
|--------|---------|--------|
| **stdout** | Regular output | Plain text lines |
| **stderr** | Progress events | `PROGRESS:` prefix + JSON |

### Progress Event Example

```bash
# Bash
echo 'PROGRESS:{"phase":"execute","percent":50,"message":"Installing..."}' >&2

# Python
print('PROGRESS:{"phase":"execute","percent":50,"message":"Installing..."}', file=sys.stderr)
```

## Required Commands

| Command | Description | Exit Code |
|---------|-------------|-----------|
| `is-applicable` | Check if plugin can run | 0=yes, 1=no |
| `update` | Execute updates | 0=success, non-zero=failure |

## Optional Commands

| Command | Description |
|---------|-------------|
| `does-require-sudo` | Check if sudo needed (exit 0=yes, 1=no) |
| `can-separate-download` | Check if download is separate (exit 0=yes, 1=no) |
| `estimate-update` | Return JSON with size/time estimates |
| `download` | Download updates only |

## Documentation

For complete protocol documentation, see:
- [External Plugin Streaming Protocol](../../docs/external-plugin-streaming-protocol.md)
- [Plugin Development Guide](../../docs/plugin-development.md)
