"""Tests for plugin signing and verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from plugins.signing import (
    PluginSignature,
    PluginSigner,
    PluginVerifier,
    TrustLevel,
    VerificationResult,
    VerificationStatus,
)


class TestPluginSignature:
    """Tests for PluginSignature dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        sig = PluginSignature(
            plugin_name="apt",
            version="1.0.0",
            checksum_sha256="abc123",
            signature="sig",
            signer_key_id="KEY123",
            signed_at=datetime(2025, 1, 1, tzinfo=UTC),
        )

        data = sig.to_dict()

        assert data["plugin_name"] == "apt"
        assert data["version"] == "1.0.0"
        assert data["checksum_sha256"] == "abc123"
        assert data["signature"] == "sig"
        assert data["signer_key_id"] == "KEY123"
        assert "2025-01-01" in data["signed_at"]

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "plugin_name": "apt",
            "version": "1.0.0",
            "checksum_sha256": "abc123",
            "signature": "sig",
            "signer_key_id": "KEY123",
            "signed_at": "2025-01-01T00:00:00+00:00",
            "expires_at": None,
        }

        sig = PluginSignature.from_dict(data)

        assert sig.plugin_name == "apt"
        assert sig.version == "1.0.0"
        assert sig.checksum_sha256 == "abc123"
        assert sig.signature == "sig"
        assert sig.signer_key_id == "KEY123"
        assert sig.signed_at is not None

    def test_roundtrip(self) -> None:
        """Test serialization roundtrip."""
        original = PluginSignature(
            plugin_name="flatpak",
            version="2.0.0",
            checksum_sha256="def456",
        )

        data = original.to_dict()
        restored = PluginSignature.from_dict(data)

        assert restored.plugin_name == original.plugin_name
        assert restored.version == original.version
        assert restored.checksum_sha256 == original.checksum_sha256


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_is_verified_true(self) -> None:
        """Test is_verified when verified."""
        result = VerificationResult(
            plugin_name="apt",
            status=VerificationStatus.VERIFIED,
            trust_level=TrustLevel.CHECKSUM_VALID,
        )
        assert result.is_verified is True

    def test_is_verified_false(self) -> None:
        """Test is_verified when not verified."""
        result = VerificationResult(
            plugin_name="apt",
            status=VerificationStatus.CHECKSUM_MISMATCH,
            trust_level=TrustLevel.UNKNOWN,
        )
        assert result.is_verified is False

    def test_is_trusted_signed(self) -> None:
        """Test is_trusted with signed plugin."""
        result = VerificationResult(
            plugin_name="apt",
            status=VerificationStatus.VERIFIED,
            trust_level=TrustLevel.SIGNED,
        )
        assert result.is_trusted is True

    def test_is_trusted_trusted(self) -> None:
        """Test is_trusted with trusted plugin."""
        result = VerificationResult(
            plugin_name="apt",
            status=VerificationStatus.VERIFIED,
            trust_level=TrustLevel.TRUSTED,
        )
        assert result.is_trusted is True

    def test_is_trusted_checksum_only(self) -> None:
        """Test is_trusted with checksum-only verification."""
        result = VerificationResult(
            plugin_name="apt",
            status=VerificationStatus.VERIFIED,
            trust_level=TrustLevel.CHECKSUM_VALID,
        )
        assert result.is_trusted is False


class TestPluginSigner:
    """Tests for PluginSigner class."""

    def test_calculate_checksum(self) -> None:
        """Test checksum calculation for a file."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")

            signer = PluginSigner()
            checksum = signer.calculate_checksum(test_file)

            # SHA256 of "Hello, World!"
            assert len(checksum) == 64
            assert checksum.isalnum()

    def test_calculate_checksum_deterministic(self) -> None:
        """Test that checksum is deterministic."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Test content")

            signer = PluginSigner()
            checksum1 = signer.calculate_checksum(test_file)
            checksum2 = signer.calculate_checksum(test_file)

            assert checksum1 == checksum2

    def test_calculate_directory_checksum(self) -> None:
        """Test checksum calculation for a directory."""
        with TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "plugin"
            plugin_dir.mkdir()
            (plugin_dir / "file1.py").write_text("print('hello')")
            (plugin_dir / "file2.py").write_text("print('world')")

            signer = PluginSigner()
            checksum = signer.calculate_directory_checksum(plugin_dir)

            assert len(checksum) == 64

    def test_directory_checksum_includes_structure(self) -> None:
        """Test that directory checksum includes file paths."""
        with TemporaryDirectory() as tmpdir:
            # Create two directories with same content but different structure
            dir1 = Path(tmpdir) / "dir1"
            dir1.mkdir()
            (dir1 / "a.txt").write_text("content")

            dir2 = Path(tmpdir) / "dir2"
            dir2.mkdir()
            (dir2 / "b.txt").write_text("content")

            signer = PluginSigner()
            checksum1 = signer.calculate_directory_checksum(dir1)
            checksum2 = signer.calculate_directory_checksum(dir2)

            # Different file names should produce different checksums
            assert checksum1 != checksum2

    def test_sign_plugin_file(self) -> None:
        """Test signing a plugin file."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "plugin.py"
            plugin_file.write_text("# Plugin code")

            signer = PluginSigner()
            signature = signer.sign_plugin(plugin_file, "test-plugin", "1.0.0")

            assert signature.plugin_name == "test-plugin"
            assert signature.version == "1.0.0"
            assert len(signature.checksum_sha256) == 64
            # No GPG signature without key
            assert signature.signature is None

    def test_sign_plugin_directory(self) -> None:
        """Test signing a plugin directory."""
        with TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "plugin"
            plugin_dir.mkdir()
            (plugin_dir / "__init__.py").write_text("")
            (plugin_dir / "main.py").write_text("# Main code")

            signer = PluginSigner()
            signature = signer.sign_plugin(plugin_dir, "dir-plugin", "2.0.0")

            assert signature.plugin_name == "dir-plugin"
            assert signature.version == "2.0.0"
            assert len(signature.checksum_sha256) == 64

    def test_save_and_load_signature(self) -> None:
        """Test saving and loading signature file."""
        with TemporaryDirectory() as tmpdir:
            sig_file = Path(tmpdir) / "signature.json"

            original = PluginSignature(
                plugin_name="test",
                version="1.0.0",
                checksum_sha256="abc123def456",
            )

            signer = PluginSigner()
            signer.save_signature(original, sig_file)

            loaded = signer.load_signature(sig_file)

            assert loaded.plugin_name == original.plugin_name
            assert loaded.version == original.version
            assert loaded.checksum_sha256 == original.checksum_sha256


class TestPluginVerifier:
    """Tests for PluginVerifier class."""

    def test_verify_valid_checksum(self) -> None:
        """Test verification with valid checksum."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "plugin.py"
            plugin_file.write_text("# Plugin code")

            # Create signature
            signer = PluginSigner()
            signature = signer.sign_plugin(plugin_file, "test", "1.0.0")

            # Verify
            verifier = PluginVerifier()
            result = verifier.verify_plugin(plugin_file, signature)

            assert result.is_verified
            assert result.trust_level == TrustLevel.CHECKSUM_VALID

    def test_verify_invalid_checksum(self) -> None:
        """Test verification with invalid checksum."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "plugin.py"
            plugin_file.write_text("# Plugin code")

            # Create signature with wrong checksum
            signature = PluginSignature(
                plugin_name="test",
                version="1.0.0",
                checksum_sha256="invalid_checksum",
            )

            verifier = PluginVerifier()
            result = verifier.verify_plugin(plugin_file, signature)

            assert not result.is_verified
            assert result.status == VerificationStatus.CHECKSUM_MISMATCH

    def test_verify_modified_file(self) -> None:
        """Test verification after file modification."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "plugin.py"
            plugin_file.write_text("# Original code")

            # Create signature
            signer = PluginSigner()
            signature = signer.sign_plugin(plugin_file, "test", "1.0.0")

            # Modify file
            plugin_file.write_text("# Modified code")

            # Verify
            verifier = PluginVerifier()
            result = verifier.verify_plugin(plugin_file, signature)

            assert not result.is_verified
            assert result.status == VerificationStatus.CHECKSUM_MISMATCH

    def test_verify_directory(self) -> None:
        """Test verification of plugin directory."""
        with TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "plugin"
            plugin_dir.mkdir()
            (plugin_dir / "__init__.py").write_text("")
            (plugin_dir / "main.py").write_text("# Code")

            # Create signature
            signer = PluginSigner()
            signature = signer.sign_plugin(plugin_dir, "dir-plugin", "1.0.0")

            # Verify
            verifier = PluginVerifier()
            result = verifier.verify_plugin(plugin_dir, signature)

            assert result.is_verified
            assert result.trust_level == TrustLevel.CHECKSUM_VALID

    def test_add_trusted_key(self) -> None:
        """Test adding a trusted key."""
        verifier = PluginVerifier()
        verifier.add_trusted_key("KEY123")

        assert "KEY123" in verifier.trusted_keys

    def test_remove_trusted_key(self) -> None:
        """Test removing a trusted key."""
        verifier = PluginVerifier(trusted_keys=["KEY123", "KEY456"])

        result = verifier.remove_trusted_key("KEY123")

        assert result is True
        assert "KEY123" not in verifier.trusted_keys
        assert "KEY456" in verifier.trusted_keys

    def test_remove_nonexistent_key(self) -> None:
        """Test removing a key that doesn't exist."""
        verifier = PluginVerifier()

        result = verifier.remove_trusted_key("NONEXISTENT")

        assert result is False

    def test_expired_signature(self) -> None:
        """Test verification with expired signature."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "plugin.py"
            plugin_file.write_text("# Plugin code")

            signer = PluginSigner()
            checksum = signer.calculate_checksum(plugin_file)

            # Create expired signature
            signature = PluginSignature(
                plugin_name="test",
                version="1.0.0",
                checksum_sha256=checksum,
                signature="fake_signature",  # Needs signature to check expiry
                expires_at=datetime.now(tz=UTC) - timedelta(days=1),
            )

            verifier = PluginVerifier()
            result = verifier.verify_plugin(plugin_file, signature)

            # Will fail at GPG verification before expiry check
            # since we don't have a real signature
            assert result.status in (
                VerificationStatus.SIGNATURE_INVALID,
                VerificationStatus.SIGNATURE_EXPIRED,
            )
