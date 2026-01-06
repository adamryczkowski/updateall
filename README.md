# Update-All

**A unified system update manager for Linux**

Update-All is a command-line tool that orchestrates updates across multiple package managers and system components. Instead of running separate update commands for APT, Flatpak, Snap, pipx, and others, Update-All handles them all with a single command.

## Features

- **Unified Updates** — Update all your package managers with one command
- **Multiple Package Managers** — Supports APT, Flatpak, Snap, pipx, Cargo, npm, and Rustup
- **Smart Execution** — Plugins run in the correct order with dependency awareness
- **Progress Display** — Rich terminal UI showing real-time progress for each plugin
- **Dry Run Mode** — Preview what will be updated before making changes
- **Update History** — Track past update runs and their results
- **Configuration** — Enable/disable plugins and customize behavior
- **Remote Updates** — Update multiple machines via SSH (coming soon)
- **Scheduled Updates** — Automatic updates via systemd timers (coming soon)

## Supported Package Managers

| Package Manager | Description |
|-----------------|-------------|
| **apt** | Debian/Ubuntu system packages |
| **flatpak** | Flatpak applications |
| **snap** | Snap packages |
| **pipx** | Python CLI applications |
| **cargo** | Rust packages installed via cargo |
| **npm** | Global npm packages |
| **rustup** | Rust toolchain updates |

## Installation

### Install with pipx (Recommended)

The easiest way to install Update-All is using [pipx](https://pipx.pypa.io/):

```bash
# Install pipx if you don't have it
sudo apt install pipx
pipx ensurepath

# Install update-all
pipx install git+https://github.com/adamryczkowski/updateall.git#subdirectory=cli

# Verify installation
update-all --version
```

### Install from Source (Development)

For development or if you want to modify the code:

**Prerequisites:**
- Python 3.11 or later
- [Poetry](https://python-poetry.org/) 2.0 or later
- [just](https://github.com/casey/just) command runner

```bash
# Clone the repository
git clone https://github.com/adamryczkowski/updateall.git
cd updateall

# Install all components
just install-all

# Verify installation
just run -- --version

# Run update-all
just run
```

## Usage

### Basic Commands

#### Run All Updates

```bash
# Update all enabled plugins
update-all run

# Or using just
just run
```

#### Check for Available Updates

```bash
# See what updates are available without applying them
update-all check
```

#### Dry Run Mode

```bash
# Preview what would be updated
update-all run --dry-run
```

#### Run Specific Plugins

```bash
# Update only apt and flatpak
update-all run --plugin apt --plugin flatpak
```

### Viewing Status

#### Show Plugin Status

```bash
# See which plugins are available and enabled
update-all status
```

#### View Update History

```bash
# Show recent update runs
update-all history

# Show more entries
update-all history --limit 20
```

### Managing Plugins

#### List All Plugins

```bash
update-all plugins list
```

#### Enable/Disable Plugins

```bash
# Disable a plugin
update-all plugins disable snap

# Enable a plugin
update-all plugins enable snap
```

### Configuration

#### Show Current Configuration

```bash
update-all config show
```

#### Initialize Configuration File

```bash
# Create default configuration
update-all config init

# Show configuration file path
update-all config path
```

### Configuration File

The configuration file is located at `~/.config/update-all/config.yaml`:

```yaml
# Global settings
global:
  max_parallel_tasks: 4
  continue_on_error: true
  verbose: false

# Plugin-specific settings
plugins:
  apt:
    enabled: true
    timeout_seconds: 3600
  flatpak:
    enabled: true
  snap:
    enabled: false  # Disable snap updates
  pipx:
    enabled: true
```

## Command Reference

### Main Commands

| Command | Description |
|---------|-------------|
| `update-all run` | Run system updates |
| `update-all check` | Check for available updates |
| `update-all status` | Show system and plugin status |
| `update-all history` | Show update history |

### Plugin Commands

| Command | Description |
|---------|-------------|
| `update-all plugins list` | List all available plugins |
| `update-all plugins enable <name>` | Enable a plugin |
| `update-all plugins disable <name>` | Disable a plugin |

### Configuration Commands

| Command | Description |
|---------|-------------|
| `update-all config show` | Show current configuration |
| `update-all config init` | Initialize configuration file |
| `update-all config path` | Show configuration file path |

### Common Options

| Option | Description |
|--------|-------------|
| `--dry-run, -n` | Simulate updates without making changes |
| `--verbose, -v` | Enable verbose output |
| `--plugin, -p` | Specify plugins to run (can be repeated) |
| `--continue-on-error, -c` | Continue with remaining plugins after a failure |
| `--version, -V` | Show version and exit |
| `--help` | Show help message |

## Examples

### Update Everything

```bash
# Run all updates with verbose output
update-all run --verbose
```

### Safe Update Workflow

```bash
# 1. Check what's available
update-all check

# 2. Preview the updates
update-all run --dry-run

# 3. Run the actual updates
update-all run
```

### Update Only User Packages

```bash
# Update only user-space package managers (no sudo required)
update-all run --plugin pipx --plugin flatpak --plugin cargo
```

### Scheduled Updates (Coming Soon)

```bash
# Enable weekly updates
update-all schedule enable --interval weekly

# Check schedule status
update-all schedule status

# Disable scheduled updates
update-all schedule disable
```

### Remote Updates (Coming Soon)

```bash
# Update a remote host
update-all remote run server1

# Update multiple hosts in parallel
update-all remote run server1 server2 --parallel

# Check connectivity
update-all remote check server1
```

## Troubleshooting

### Plugin Not Found

If a plugin shows as "not available", ensure the corresponding package manager is installed:

```bash
# Check if apt is available
which apt

# Check if flatpak is available
which flatpak
```

### Permission Issues

Some plugins (like apt) require sudo privileges. Update-All will prompt for your password when needed.

### Timeout Errors

If updates are timing out, increase the timeout in your configuration:

```yaml
plugins:
  apt:
    timeout_seconds: 7200  # 2 hours
```

### View Logs

For detailed debugging information:

```bash
update-all run --verbose
```

## Requirements

- **Operating System**: Linux (tested on Ubuntu 24.04)
- **Python**: 3.11 or later
- **Package Managers**: Only the ones you want to use need to be installed

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please see the [Plugin Development Guide](docs/plugin-development.md) for information on creating new plugins.
