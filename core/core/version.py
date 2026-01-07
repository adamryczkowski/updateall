"""Version parsing and comparison utilities.

This module provides utilities for parsing and comparing version strings
in various formats commonly used by software packages.

Supported formats:
- Semantic versioning (1.2.3, v1.2.3)
- Date-based versions (2024.01.15)
- Git commit hashes (short and full)
- Versions with prerelease tags (1.2.3-alpha, 1.2.3-rc1)
"""

from __future__ import annotations

import re
from functools import total_ordering
from typing import NamedTuple


class VersionComponents(NamedTuple):
    """Parsed version components."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None


# Regex patterns for version parsing
SEMVER_PATTERN = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?"
    r"(?:[-.]?(alpha|beta|rc|dev|pre|post)\.?(\d+)?)?"
    r"(?:\+(.+))?$",
    re.IGNORECASE,
)

DATE_VERSION_PATTERN = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$")

GIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def parse_version(version: str) -> VersionComponents:
    """Parse a version string into components.

    Args:
        version: Version string to parse.

    Returns:
        VersionComponents tuple with major, minor, patch, prerelease, build.

    Raises:
        ValueError: If the version string cannot be parsed.

    Examples:
        >>> parse_version("1.2.3")
        VersionComponents(major=1, minor=2, patch=3, prerelease=None, build=None)
        >>> parse_version("v1.2.3-alpha")
        VersionComponents(major=1, minor=2, patch=3, prerelease='alpha', build=None)
        >>> parse_version("2024.01.15")
        VersionComponents(major=2024, minor=1, patch=15, prerelease=None, build=None)
    """
    version = version.strip()

    # Try date-based version first
    date_match = DATE_VERSION_PATTERN.match(version)
    if date_match:
        return VersionComponents(
            major=int(date_match.group(1)),
            minor=int(date_match.group(2)),
            patch=int(date_match.group(3)),
        )

    # Try semantic version
    semver_match = SEMVER_PATTERN.match(version)
    if semver_match:
        major = int(semver_match.group(1))
        minor = int(semver_match.group(2) or 0)
        patch = int(semver_match.group(3) or 0)

        prerelease = None
        if semver_match.group(4):
            prerelease = semver_match.group(4).lower()
            if semver_match.group(5):
                prerelease += semver_match.group(5)

        build = semver_match.group(6)

        return VersionComponents(
            major=major,
            minor=minor,
            patch=patch,
            prerelease=prerelease,
            build=build,
        )

    raise ValueError(f"Cannot parse version string: {version}")


def is_git_hash(version: str) -> bool:
    """Check if a version string is a git commit hash.

    Args:
        version: Version string to check.

    Returns:
        True if the string looks like a git hash, False otherwise.
    """
    return bool(GIT_HASH_PATTERN.match(version.strip()))


def _prerelease_order(prerelease: str | None) -> tuple[int, str]:
    """Get ordering value for prerelease tag.

    Prerelease versions are ordered: alpha < beta < dev < pre < rc < post < (none)

    Args:
        prerelease: Prerelease tag string.

    Returns:
        Tuple for comparison ordering.
    """
    if prerelease is None:
        return (100, "")  # No prerelease = stable release

    prerelease_lower = prerelease.lower()

    # Extract the base tag and optional number
    order_map = {
        "alpha": 10,
        "beta": 20,
        "dev": 30,
        "pre": 40,
        "rc": 50,
        "post": 90,
    }

    for tag, order in order_map.items():
        if prerelease_lower.startswith(tag):
            return (order, prerelease_lower)

    return (60, prerelease_lower)  # Unknown prerelease tags


def compare_versions(version1: str, version2: str) -> int:
    """Compare two version strings.

    Args:
        version1: First version string.
        version2: Second version string.

    Returns:
        -1 if version1 < version2
         0 if version1 == version2
         1 if version1 > version2

    Raises:
        ValueError: If either version cannot be parsed.

    Examples:
        >>> compare_versions("1.2.3", "1.3.0")
        -1
        >>> compare_versions("1.3.0", "1.3.0")
        0
        >>> compare_versions("2.0.0", "1.9.9")
        1
        >>> compare_versions("1.2.3-alpha", "1.2.3")
        -1
    """
    # Handle git hashes - just compare as strings
    if is_git_hash(version1) and is_git_hash(version2):
        if version1.lower() == version2.lower():
            return 0
        # Can't meaningfully compare git hashes
        return 0 if version1.lower() == version2.lower() else -1

    v1 = parse_version(version1)
    v2 = parse_version(version2)

    # Compare major.minor.patch
    if v1.major != v2.major:
        return -1 if v1.major < v2.major else 1
    if v1.minor != v2.minor:
        return -1 if v1.minor < v2.minor else 1
    if v1.patch != v2.patch:
        return -1 if v1.patch < v2.patch else 1

    # Compare prerelease tags
    pre1 = _prerelease_order(v1.prerelease)
    pre2 = _prerelease_order(v2.prerelease)

    if pre1 < pre2:
        return -1
    elif pre1 > pre2:
        return 1

    return 0


def needs_update(installed: str | None, available: str | None) -> bool | None:
    """Check if an update is needed based on version comparison.

    Args:
        installed: Currently installed version (None if unknown).
        available: Latest available version (None if unknown).

    Returns:
        True if update is needed (available > installed).
        False if up-to-date (available <= installed).
        None if cannot determine (either version is None or unparsable).

    Examples:
        >>> needs_update("1.2.3", "1.3.0")
        True
        >>> needs_update("1.3.0", "1.3.0")
        False
        >>> needs_update("1.3.0", "1.2.3")
        False
        >>> needs_update(None, "1.3.0")
        None
    """
    if installed is None or available is None:
        return None

    try:
        result = compare_versions(installed, available)
        return result < 0  # Update needed if installed < available
    except ValueError:
        return None


@total_ordering
class Version:
    """A comparable version object.

    This class wraps a version string and provides comparison operators.

    Attributes:
        raw: The original version string.
        components: Parsed version components (None for git hashes).

    Example:
        >>> v1 = Version("1.2.3")
        >>> v2 = Version("1.3.0")
        >>> v1 < v2
        True
        >>> v1 == Version("1.2.3")
        True
    """

    raw: str
    components: VersionComponents | None
    _is_git_hash: bool

    def __init__(self, version: str) -> None:
        """Initialize a Version object.

        Args:
            version: Version string to parse.

        Raises:
            ValueError: If the version cannot be parsed.
        """
        self.raw = version.strip()
        self._is_git_hash = is_git_hash(self.raw)
        if not self._is_git_hash:
            self.components = parse_version(self.raw)
        else:
            self.components = None

    def __str__(self) -> str:
        """Return the original version string."""
        return self.raw

    def __repr__(self) -> str:
        """Return a repr string."""
        return f"Version({self.raw!r})"

    def __eq__(self, other: object) -> bool:
        """Check equality with another Version."""
        if not isinstance(other, Version):
            return NotImplemented
        if self._is_git_hash and other._is_git_hash:
            return self.raw.lower() == other.raw.lower()
        if self._is_git_hash or other._is_git_hash:
            return False
        return compare_versions(self.raw, other.raw) == 0

    def __lt__(self, other: object) -> bool:
        """Check if this version is less than another."""
        if not isinstance(other, Version):
            return NotImplemented
        return compare_versions(self.raw, other.raw) < 0

    def __hash__(self) -> int:
        """Return hash for use in sets/dicts."""
        return hash(self.raw.lower())


def normalize_version(version: str) -> str:
    """Normalize a version string for consistent comparison.

    Removes leading 'v' prefix and normalizes separators.

    Args:
        version: Version string to normalize.

    Returns:
        Normalized version string.

    Examples:
        >>> normalize_version("v1.2.3")
        '1.2.3'
        >>> normalize_version("V1.2.3")
        '1.2.3'
    """
    version = version.strip()
    if version.lower().startswith("v"):
        version = version[1:]
    return version
