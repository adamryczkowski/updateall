# Update-All Solution Requirements TODO

**Created:** January 7, 2026
**Purpose:** Reminder of all required features for the update-all solution

---

## Core Architecture

- [ ] Plugin-driven system where each component to be updated is handled by a separate plugin
- [ ] Each plugin is a standalone executable script following a specific CLI API
- [ ] Plugins can be arbitrary executables (ELF, Python, Bash, etc.)
- [ ] Plugin structure analogous to pre-commit project
- [ ] Plugins must be allowed to self-update

---

## Privilege Management

- [ ] Ability to elevate privileges via sudo internally
- [ ] Set up sudoers file to allow passwordless execution of specific programs
- [ ] Based on plugins' `does-require-sudo` and `sudo-programs-paths` commands

---

## User Interface

- [ ] One command to run the update-all procedure
- [ ] Tabbed output with one tab per plugin
- [ ] Live updates of update check, download, and execution steps
- [ ] Overall progress displayed on the screen
- [ ] Live log of the current update task in progress
- [ ] Estimated time remaining for the whole update-all procedure (based on previous runs)
- [ ] Nice visual output about what is being updated

### Tab Requirements

- [ ] Each tab functionally equivalent to a rich terminal emulator
- [ ] Capable of displaying live progress of the update process
- [ ] Capturing user input independently of other tabs
- [ ] Implemented to look and feel as different threads of a single application
- [ ] Each tab is an independent terminal session
- [ ] Capable of running its own subprocesses
- [ ] Capturing subprocess output and displaying it live in the tab
- [ ] If subprocess requires user input, capture it and send to subprocess without interrupting other tabs
- [ ] User can switch between tabs using configurable keyboard shortcuts (Ctrl+Tab, Ctrl+Shift+Tab) or mouse clicks
- [ ] Each tab maintains its own scrollback buffer
- [ ] User can scroll through output history of each tab independently
- [ ] All keypresses other than tab switching sent to active tab only

---

## Performance Optimization

- [ ] Quick if nothing to update (never download or compile if everything is up-to-date)
- [ ] Ability to run some updates in parallel by honoring mutexes
- [ ] Each plugin lists mutexes required and held during each step
- [ ] Mutex list is dynamic (depends on information from `estimate-update` step)

### Resource Control

- [ ] Control memory usage of whole update-all procedure
- [ ] Maximally-parallel but not exceeding given memory usage limit
- [ ] Control CPU usage of whole update-all procedure
- [ ] Not schedule more tasks than number of CPU cores available
- [ ] Control network usage of whole update-all procedure
- [ ] Probably max 2 parallel downloads at the same time

---

## Remote Updates

- [ ] Ability to update not only this computer but also remote computers
- [ ] Remote computers accessed via SSH
- [ ] A separate script or command for remote updates

---

## Separate Operations

- [ ] Separate algorithm to just check for updates without performing them
- [ ] Return estimated time required to perform updates
- [ ] Return size of downloads required
- [ ] Return information that everything is up-to-date
- [ ] Return information that update does not apply to this system
- [ ] Separate action to just download updates without applying them
- [ ] Only for plugins that support separate download and update steps
- [ ] Nice visual output about download progress

---

## Scheduling

- [ ] Ability to schedule update-all procedure to run automatically
- [ ] Specified intervals (weekly, monthly)
- [ ] Similar to apt system on Ubuntu
- [ ] Preferably via systemd timers

---

## Logging and Statistics

### Advanced Logging Per Step Per Plugin

- [ ] Network traffic
- [ ] CPU usage (kernel and user)
- [ ] Wall-clock time
- [ ] Memory usage (max RSS)
- [ ] IO statistics (read bytes, write bytes)

### Statistical Modeling

- [ ] Advanced statistical modeling of historical data
- [ ] Provide better estimates for future runs
- [ ] Output not only point estimates but also confidence intervals

---

## Plugin CLI API

### Core Commands

- [ ] `is-applicable` - Check if update applies to this system (0 = yes, non-zero = no)
- [ ] `estimate-update` - Estimate download size and CPU time (0 = success, non-zero = failure)
  - Handle case when plugin cannot estimate (specific non-zero exit code)
- [ ] `can-separate-download` - Check if separate download and update steps supported (0 = yes)
- [ ] `download` - Perform download only (0 = success) - only if `can-separate-download` returns 0
- [ ] `self-update` - Update the plugin itself (0 = success)
  - Provision for plugins that do not support self-update (specific non-zero exit code)
- [ ] `self-upgrade` - Perform plugin upgrade (0 = success)
- [ ] `does-require-sudo` - Check if sudo required (0 = yes)
- [ ] `sudo-programs-paths` - Return full paths of programs needing sudo (one per line)
- [ ] `update` - Perform the update (0 = success)
  - If separate download supported, assume download was already performed

### Dependency and Mutex Commands

- [ ] `estimate-update-dependency` - List mutexes required for estimate-update step
- [ ] `download-dependency` - List mutexes required for download step
- [ ] `update-dependency` - List mutexes required for update step
- [ ] `estimate-update-mutexes` - List mutexes held during estimate-update step
- [ ] `download-mutexes` - List mutexes held during download step
- [ ] `update-mutexes` - List mutexes held during update step

---

## Configuration

- [ ] Part of CLI API can be configured by configuration file
- [ ] Similar to how pre-commit does it
- [ ] Rather than interrogating the plugin each time

---

## Notes

This TODO list was created on January 7, 2026 based on the update-all solution requirements specification. These requirements should guide the development of the complete update-all system.

Key inspirations:
- **pre-commit** - For plugin architecture and configuration approach
- **apt** - For scheduling and update checking patterns
- **systemd** - For timer-based scheduling
