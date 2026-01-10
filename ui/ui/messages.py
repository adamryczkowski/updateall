"""Textual message classes for the UI module.

This module contains Textual Message classes used for communication
between widgets and the application, extracted for better separation
of concerns and maintainability.

Milestone 4 - UI Module Architecture Refactoring
See docs/cleanup-and-refactoring-plan.md section 4.3.1
"""

from __future__ import annotations

from textual.message import Message


class AllPluginsCompleted(Message):
    """Message sent when all plugins have completed.

    This message is posted by the InteractiveTabbedApp when all plugins
    have finished execution, allowing the app to perform cleanup and
    display final results.

    Attributes:
        total: Total number of plugins that were executed.
        successful: Number of plugins that completed successfully.
        failed: Number of plugins that failed.
    """

    def __init__(
        self,
        total: int,
        successful: int,
        failed: int,
    ) -> None:
        """Initialize the message.

        Args:
            total: Total number of plugins.
            successful: Number of successful plugins.
            failed: Number of failed plugins.
        """
        self.total = total
        self.successful = successful
        self.failed = failed
        super().__init__()
