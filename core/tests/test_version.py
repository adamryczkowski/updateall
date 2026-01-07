"""Tests for version parsing and comparison utilities."""

from __future__ import annotations

import pytest

from core.version import (
    Version,
    VersionComponents,
    compare_versions,
    is_git_hash,
    needs_update,
    normalize_version,
    parse_version,
)


class TestParseVersion:
    """Tests for parse_version function."""

    def test_parse_semantic_version(self) -> None:
        """Test parsing semantic version strings."""
        result = parse_version("1.2.3")
        assert result == VersionComponents(major=1, minor=2, patch=3)

    def test_parse_semantic_version_with_v_prefix(self) -> None:
        """Test parsing version with 'v' prefix."""
        result = parse_version("v1.2.3")
        assert result == VersionComponents(major=1, minor=2, patch=3)

    def test_parse_semantic_version_with_V_prefix(self) -> None:
        """Test parsing version with uppercase 'V' prefix."""
        result = parse_version("V1.2.3")
        assert result == VersionComponents(major=1, minor=2, patch=3)

    def test_parse_two_part_version(self) -> None:
        """Test parsing version with only major.minor."""
        result = parse_version("1.2")
        assert result == VersionComponents(major=1, minor=2, patch=0)

    def test_parse_single_part_version(self) -> None:
        """Test parsing version with only major."""
        result = parse_version("1")
        assert result == VersionComponents(major=1, minor=0, patch=0)

    def test_parse_date_version(self) -> None:
        """Test parsing date-based versions."""
        result = parse_version("2024.01.15")
        assert result == VersionComponents(major=2024, minor=1, patch=15)

    def test_parse_date_version_single_digit(self) -> None:
        """Test parsing date-based versions with single digit month/day."""
        result = parse_version("2024.1.5")
        assert result == VersionComponents(major=2024, minor=1, patch=5)

    def test_parse_version_with_alpha_prerelease(self) -> None:
        """Test parsing version with alpha prerelease tag."""
        result = parse_version("1.2.3-alpha")
        assert result.major == 1
        assert result.minor == 2
        assert result.patch == 3
        assert result.prerelease == "alpha"

    def test_parse_version_with_beta_prerelease(self) -> None:
        """Test parsing version with beta prerelease tag."""
        result = parse_version("1.2.3-beta")
        assert result.prerelease == "beta"

    def test_parse_version_with_rc_prerelease(self) -> None:
        """Test parsing version with rc prerelease tag."""
        result = parse_version("1.2.3-rc1")
        assert result.prerelease == "rc1"

    def test_parse_version_with_build_metadata(self) -> None:
        """Test parsing version with build metadata."""
        result = parse_version("1.2.3+build123")
        assert result.major == 1
        assert result.minor == 2
        assert result.patch == 3
        assert result.build == "build123"

    def test_parse_invalid_version_raises_error(self) -> None:
        """Test that invalid version strings raise ValueError."""
        with pytest.raises(ValueError, match="Cannot parse version string"):
            parse_version("not-a-version")

    def test_parse_version_strips_whitespace(self) -> None:
        """Test that whitespace is stripped from version strings."""
        result = parse_version("  1.2.3  ")
        assert result == VersionComponents(major=1, minor=2, patch=3)


class TestIsGitHash:
    """Tests for is_git_hash function."""

    def test_short_git_hash(self) -> None:
        """Test detection of short git hash (7 chars)."""
        assert is_git_hash("abc1234") is True

    def test_full_git_hash(self) -> None:
        """Test detection of full git hash (40 chars)."""
        assert is_git_hash("abc1234567890def1234567890abc1234567890a") is True

    def test_not_git_hash_too_short(self) -> None:
        """Test that short strings are not detected as git hashes."""
        assert is_git_hash("abc123") is False

    def test_not_git_hash_invalid_chars(self) -> None:
        """Test that strings with invalid chars are not git hashes."""
        assert is_git_hash("abc123g") is False

    def test_not_git_hash_version_string(self) -> None:
        """Test that version strings are not detected as git hashes."""
        assert is_git_hash("1.2.3") is False

    def test_git_hash_case_insensitive(self) -> None:
        """Test that git hash detection is case insensitive."""
        assert is_git_hash("ABC1234") is True
        assert is_git_hash("AbC1234") is True


class TestCompareVersions:
    """Tests for compare_versions function."""

    def test_compare_versions_less_than(self) -> None:
        """Test version comparison: less than."""
        assert compare_versions("1.2.3", "1.3.0") < 0
        assert compare_versions("1.2.3", "2.0.0") < 0
        assert compare_versions("1.2.3", "1.2.4") < 0

    def test_compare_versions_equal(self) -> None:
        """Test version comparison: equal."""
        assert compare_versions("1.2.3", "1.2.3") == 0

    def test_compare_versions_equal_with_v_prefix(self) -> None:
        """Test version comparison with v prefix."""
        assert compare_versions("v1.2.3", "1.2.3") == 0

    def test_compare_versions_greater_than(self) -> None:
        """Test version comparison: greater than."""
        assert compare_versions("1.3.0", "1.2.3") > 0
        assert compare_versions("2.0.0", "1.2.3") > 0
        assert compare_versions("1.2.4", "1.2.3") > 0

    def test_compare_versions_with_prerelease(self) -> None:
        """Test version comparison with prerelease tags."""
        # Alpha < stable
        assert compare_versions("1.2.3-alpha", "1.2.3") < 0
        # Beta > alpha
        assert compare_versions("1.2.3-beta", "1.2.3-alpha") > 0
        # RC > beta
        assert compare_versions("1.2.3-rc1", "1.2.3-beta") > 0

    def test_compare_versions_major_difference(self) -> None:
        """Test that major version takes precedence."""
        assert compare_versions("2.0.0", "1.9.9") > 0

    def test_compare_versions_minor_difference(self) -> None:
        """Test that minor version takes precedence over patch."""
        assert compare_versions("1.10.0", "1.9.9") > 0

    def test_compare_git_hashes_equal(self) -> None:
        """Test comparing identical git hashes."""
        assert compare_versions("abc1234", "abc1234") == 0
        assert compare_versions("ABC1234", "abc1234") == 0


class TestNeedsUpdate:
    """Tests for needs_update function."""

    def test_needs_update_true(self) -> None:
        """Test needs_update returns True when update available."""
        assert needs_update("1.2.3", "1.3.0") is True

    def test_needs_update_false_same_version(self) -> None:
        """Test needs_update returns False when versions are equal."""
        assert needs_update("1.3.0", "1.3.0") is False

    def test_needs_update_false_newer_installed(self) -> None:
        """Test needs_update returns False when installed is newer."""
        assert needs_update("1.3.0", "1.2.3") is False

    def test_needs_update_none_when_installed_none(self) -> None:
        """Test needs_update returns None when installed is None."""
        assert needs_update(None, "1.3.0") is None

    def test_needs_update_none_when_available_none(self) -> None:
        """Test needs_update returns None when available is None."""
        assert needs_update("1.2.3", None) is None

    def test_needs_update_none_when_both_none(self) -> None:
        """Test needs_update returns None when both are None."""
        assert needs_update(None, None) is None

    def test_needs_update_with_prerelease(self) -> None:
        """Test needs_update with prerelease versions."""
        assert needs_update("1.2.3-alpha", "1.2.3") is True
        assert needs_update("1.2.3", "1.2.3-alpha") is False


class TestVersion:
    """Tests for Version class."""

    def test_version_creation(self) -> None:
        """Test creating a Version object."""
        v = Version("1.2.3")
        assert v.raw == "1.2.3"
        assert v.components == VersionComponents(major=1, minor=2, patch=3)

    def test_version_str(self) -> None:
        """Test Version string representation."""
        v = Version("1.2.3")
        assert str(v) == "1.2.3"

    def test_version_repr(self) -> None:
        """Test Version repr."""
        v = Version("1.2.3")
        assert repr(v) == "Version('1.2.3')"

    def test_version_equality(self) -> None:
        """Test Version equality comparison."""
        v1 = Version("1.2.3")
        v2 = Version("1.2.3")
        assert v1 == v2

    def test_version_equality_with_v_prefix(self) -> None:
        """Test Version equality with v prefix."""
        v1 = Version("v1.2.3")
        v2 = Version("1.2.3")
        assert v1 == v2

    def test_version_less_than(self) -> None:
        """Test Version less than comparison."""
        v1 = Version("1.2.3")
        v2 = Version("1.3.0")
        assert v1 < v2

    def test_version_greater_than(self) -> None:
        """Test Version greater than comparison."""
        v1 = Version("1.3.0")
        v2 = Version("1.2.3")
        assert v1 > v2

    def test_version_less_than_or_equal(self) -> None:
        """Test Version less than or equal comparison."""
        v1 = Version("1.2.3")
        v2 = Version("1.3.0")
        v3 = Version("1.2.3")
        assert v1 <= v2
        assert v1 <= v3

    def test_version_hash(self) -> None:
        """Test Version can be used in sets and dicts."""
        v1 = Version("1.2.3")
        v2 = Version("1.2.3")
        s = {v1, v2}
        assert len(s) == 1

    def test_version_git_hash(self) -> None:
        """Test Version with git hash."""
        v = Version("abc1234")
        assert v._is_git_hash is True
        assert v.components is None

    def test_version_invalid_raises_error(self) -> None:
        """Test that invalid version raises ValueError."""
        with pytest.raises(ValueError):
            Version("not-a-version")


class TestNormalizeVersion:
    """Tests for normalize_version function."""

    def test_normalize_removes_v_prefix(self) -> None:
        """Test that v prefix is removed."""
        assert normalize_version("v1.2.3") == "1.2.3"

    def test_normalize_removes_V_prefix(self) -> None:
        """Test that uppercase V prefix is removed."""
        assert normalize_version("V1.2.3") == "1.2.3"

    def test_normalize_strips_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        assert normalize_version("  1.2.3  ") == "1.2.3"

    def test_normalize_no_change_needed(self) -> None:
        """Test that versions without prefix are unchanged."""
        assert normalize_version("1.2.3") == "1.2.3"
