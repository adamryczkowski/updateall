# Update-All Solution Requirements

> **IMPORTANT**: This document serves as a permanent reminder of the required features for the update-all solution. Reference this document when implementing new features.

## Overview

update-all is a plugin-driven system where each component to be updated is handled by a separate plugin. Each plugin is a standalone executable script that follows a specific CLI API. (Use pre-commit for inspiration on a working Python system that uses plugins written in arbitrary language).

## Plugin Requirements

### Execution Model
* Can be arbitrary executable (e.g. ELF, Python, Bash, etc.)
* Ability to either elevate privileges via sudo internally, or set up sudoers file to allow passwordless execution of specific programs that require sudo privileges, based on plugins.
* Plugin structure analogous to pre-commit project. Plugins must be allowed to self-update.

### Performance
* One command to run the update-all procedure.
* Quick if nothing to update (never download or compile anything if everything is up-to-date).

## User Interface Requirements

### Tabbed Output
* Tabbed output, with one tab per plugin, showing live updates of update check, download and execution steps.
* Each tab functionally equivalent to a rich terminal emulator, capable of displaying live progress of the update process and capturing user input independently of other tabs.
* They should be implemented to look and feel as different threads of a single application, but in reality each tab should be an independent terminal session, capable of running its own subprocesses, capturing their output and displaying it live in the tab.
* If the subprocess requires user input, the tab should capture it and send it to the subprocess without interrupting other tabs.
* User should be able to switch between tabs using configurable keyboard shortcuts (e.g. Ctrl+Tab, Ctrl+Shift+Tab) or mouse clicks.
* Each tab should maintain its own scrollback buffer, allowing the user to scroll through the output history of each tab independently.
* All the keypresses other than those used for tab switching should be sent to the active tab only.

### Visual Output
* Nice visual output about what is being updated:
  * Overall progress displayed on the screen
  * A live log of the current update task in progress
  * Estimated time remaining for the whole update-all procedure, based on previous runs

## Operational Modes

### Check-Only Mode
* A separate algorithm to just check for updates, without actually performing them.
* The command should return:
  * Estimated time required to perform the updates
  * Size of the downloads required
  * Information that everything is up-to-date
  * Information that this update does not apply to this system

### Download-Only Mode
* A separate action to just download the updates, without applying them.
* Only for plugins that support separate download and update steps.
* Should allow a nice visual output about download progress.

### Remote Updates
* Ability to update not only this computer, but also remote computers in my possession, accessed via ssh (a separate script or command for that).

## Parallelization and Resource Control

### Mutex-Based Parallelization
* Ability to run some updates in parallel, if possible, by honoring the mutexes required by each plugin.
* Each plugin will list all the mutexes that are required to be available in order to let it run its steps (estimate-update, download, update), as well as mutexes it will hold during each step.
* The list of mutexes will be dynamic, as it will depend on the information gathered in `estimate-update` step.

### Resource Limits
* Controlling the memory usage of the whole update-all procedure, so the system will be maximally-parallel, but will not exceed a given memory usage limit.
* Controlling the CPU usage of the whole update-all procedure, so the system will be maximally-parallel, but will not schedule more tasks than the number of CPU cores available.
* Controlling the network usage of the whole update-all procedure, so the system will be maximally-parallel, but will not exceed a given network bandwidth usage limit. Probably max 2 parallel downloads at the same time.

## Scheduling

* Ability to schedule the update-all procedure to run automatically at specified intervals (e.g. weekly, monthly), just like the apt system does it on Ubuntu.
* Preferably via systemd timers.

## Logging and Statistics

### Advanced Logging
* Advanced logging of per each step per each plugin:
  * Network traffic
  * CPU usage (kernel and user)
  * Wall-clock time
  * Memory usage (max RSS)
  * IO statistics (read bytes, write bytes)
* The logging will be used to make good estimates for future runs.

### Statistical Modeling
* Advanced statistical modeling of the historical data to provide better estimates for future runs.
* Output not only point estimates, but also confidence intervals for the estimates.

## Great UI Features

* Great UI that displays the progress of the whole update-all procedure
* Per-plugin progress with estimated time remaining
* Download size remaining, etc.

---

## Plugin CLI API

Part of that can be configured by configuration file, rather than by interrogating the plugin each time, just like pre-commit does it.

### Applicability
* `is-applicable` - checks if the update applies to this system, returns 0 if yes, non-zero otherwise.

### Estimation
* `estimate-update` - estimates the download size and CPU time required to perform the update, returns 0 if successful, non-zero otherwise. Must handle the case when the plugin cannot estimate the download size or CPU time (e.g. because the update is not applicable to this system) by returning a specific non-zero exit code.

### Download Separation
* `can-separate-download` - checks, if the script allows for separate download and update steps, returns 0 if yes, non-zero otherwise.
* `download` - performs the download of the update, returns 0 if successful, non-zero otherwise. Only if plugin returned 0 for `can-separate-download`.

### Self-Update
* `self-update` - updates the plugin itself to the latest version, returns 0 if successful, non-zero otherwise. Provision for plugins that do not support self-update by returning a specific non-zero exit code.
* `self-upgrade` - performs the plugin upgrade, returns 0 if successful, non-zero otherwise.

### Sudo Requirements
* `does-require-sudo` - checks if the plugin requires sudo privileges to run, returns 0 if yes, non-zero otherwise.
* `sudo-programs-paths` - if script requires sudo, returns full paths of programs that need to be run with sudo, one per line, returns 0 if successful, non-zero otherwise. Will be used to update the sudoers file to allow passwordless execution of these programs.

### Update Execution
* `update` - performs the update, returns 0 if successful, non-zero otherwise. If the plugin supports separate download and update steps, it must assume that the download step was already performed.

### Mutex Dependencies
* `estimate-update-dependency` - list of all mutexes that must be available to run the estimate-update step. Required if we want to run some plugins in parallel.
* `download-dependency` - list of all mutexes that must be available to run the download step. Required if we want to run some plugins in parallel.
* `update-dependency` - list of all mutexes that must be available to run the update step. Required if we want to run some plugins in parallel.

### Mutex Holdings
* `estimate-update-mutexes` - list of all mutexes that the plugin will hold during the estimate-update step.
* `download-mutexes` - list of all mutexes that the plugin will hold during the download step.
* `update-mutexes` - list of all mutexes that the plugin will hold during the update step.

---

*Document created: 2025-12-05*
*Last updated: 2026-01-06*
