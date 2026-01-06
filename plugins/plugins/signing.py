"""Plugin signing and verification for Phase 4.

This module provides cryptographic signing and verification of plugins
to ensure authenticity and integrity. It supports:

1. SHA256 checksums for integrity verification
2. GPG signatures for authenticity verification (optional)
3. Trust levels for different verification states
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TrustLevel(str, Enum):
    """Trust level for a plugin."""

    UNKNOWN = "unknown"  # No verification performed
    CHECKSUM_VALID = "checksum_valid"  # SHA256 checksum verified
    SIGNED = "signed"  # GPG signature verified
    TRUSTED = "trusted"  # Signed by trusted key


class VerificationStatus(str, Enum):
    """Status of plugin verification."""

    NOT_VERIFIED = "not_verified"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    SIGNATURE_INVALID = "signature_invalid"
    SIGNATURE_EXPIRED = "signature_expired"
    KEY_NOT_TRUSTED = "key_not_trusted"
    VERIFIED = "verified"


@dataclass
class PluginSignature:
    """Signature information for a plugin."""

    plugin_name: str
    version: str
    checksum_sha256: str
    signature: str | None = None  # GPG signature (base64 encoded)
    signer_key_id: str | None = None
    signed_at: datetime | None = None
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plugin_name": self.plugin_name,
            "version": self.version,
            "checksum_sha256": self.checksum_sha256,
            "signature": self.signature,
            "signer_key_id": self.signer_key_id,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginSignature:
        """Create from dictionary."""
        return cls(
            plugin_name=data["plugin_name"],
            version=data["version"],
            checksum_sha256=data["checksum_sha256"],
            signature=data.get("signature"),
            signer_key_id=data.get("signer_key_id"),
            signed_at=(
                datetime.fromisoformat(data["signed_at"]) if data.get("signed_at") else None
            ),
            expires_at=(
                datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            ),
        )


@dataclass
class VerificationResult:
    """Result of plugin verification."""

    plugin_name: str
    status: VerificationStatus
    trust_level: TrustLevel
    message: str = ""
    signature: PluginSignature | None = None
    verified_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_verified(self) -> bool:
        """Check if verification was successful."""
        return self.status == VerificationStatus.VERIFIED

    @property
    def is_trusted(self) -> bool:
        """Check if plugin is trusted."""
        return self.trust_level in (TrustLevel.SIGNED, TrustLevel.TRUSTED)


class PluginSigner:
    """Signs plugins for distribution.

    Creates SHA256 checksums and optionally GPG signatures for plugins.
    """

    def __init__(self, gpg_key_id: str | None = None) -> None:
        """Initialize the signer.

        Args:
            gpg_key_id: Optional GPG key ID for signing.
        """
        self.gpg_key_id = gpg_key_id

    def calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file.

        Args:
            file_path: Path to the file.

        Returns:
            Hex-encoded SHA256 checksum.
        """
        sha256 = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def calculate_directory_checksum(self, directory: Path) -> str:
        """Calculate checksum for a plugin directory.

        Combines checksums of all files in sorted order.

        Args:
            directory: Path to the plugin directory.

        Returns:
            Combined SHA256 checksum.
        """
        sha256 = hashlib.sha256()

        # Get all files sorted by path
        files = sorted(directory.rglob("*"))

        for file_path in files:
            if file_path.is_file():
                # Include relative path in hash for structure verification
                rel_path = file_path.relative_to(directory)
                sha256.update(str(rel_path).encode())
                sha256.update(self.calculate_checksum(file_path).encode())

        return sha256.hexdigest()

    def sign_plugin(
        self,
        plugin_path: Path,
        plugin_name: str,
        version: str,
    ) -> PluginSignature:
        """Sign a plugin file or directory.

        Args:
            plugin_path: Path to the plugin file or directory.
            plugin_name: Name of the plugin.
            version: Plugin version.

        Returns:
            PluginSignature with checksum and optional GPG signature.
        """
        # Calculate checksum
        if plugin_path.is_dir():
            checksum = self.calculate_directory_checksum(plugin_path)
        else:
            checksum = self.calculate_checksum(plugin_path)

        signature = None
        signer_key_id = None
        signed_at = None

        # Create GPG signature if key is configured
        if self.gpg_key_id:
            signature, signer_key_id = self._create_gpg_signature(checksum)
            signed_at = datetime.now(tz=UTC)

        return PluginSignature(
            plugin_name=plugin_name,
            version=version,
            checksum_sha256=checksum,
            signature=signature,
            signer_key_id=signer_key_id,
            signed_at=signed_at,
        )

    def _create_gpg_signature(self, data: str) -> tuple[str | None, str | None]:
        """Create GPG signature for data.

        Args:
            data: Data to sign.

        Returns:
            Tuple of (signature, key_id) or (None, None) on failure.
        """
        if not self.gpg_key_id:
            return None, None

        try:
            # Create detached signature
            result = subprocess.run(
                [
                    "gpg",
                    "--armor",
                    "--detach-sign",
                    "--local-user",
                    self.gpg_key_id,
                    "--output",
                    "-",
                ],
                input=data.encode(),
                capture_output=True,
                check=True,
            )
            signature = result.stdout.decode()
            return signature, self.gpg_key_id
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("gpg_signing_failed", error=str(e))
            return None, None

    def save_signature(self, signature: PluginSignature, output_path: Path) -> None:
        """Save signature to a file.

        Args:
            signature: The signature to save.
            output_path: Path to save the signature file.
        """
        with output_path.open("w") as f:
            json.dump(signature.to_dict(), f, indent=2)

    def load_signature(self, signature_path: Path) -> PluginSignature:
        """Load signature from a file.

        Args:
            signature_path: Path to the signature file.

        Returns:
            Loaded PluginSignature.
        """
        with signature_path.open() as f:
            data = json.load(f)
        return PluginSignature.from_dict(data)


class PluginVerifier:
    """Verifies plugin signatures and checksums.

    Supports verification of:
    1. SHA256 checksums for integrity
    2. GPG signatures for authenticity
    3. Trust chain for trusted keys
    """

    def __init__(self, trusted_keys: list[str] | None = None) -> None:
        """Initialize the verifier.

        Args:
            trusted_keys: List of trusted GPG key IDs.
        """
        self.trusted_keys = set(trusted_keys or [])
        self._signer = PluginSigner()

    def verify_plugin(
        self,
        plugin_path: Path,
        signature: PluginSignature,
    ) -> VerificationResult:
        """Verify a plugin against its signature.

        Args:
            plugin_path: Path to the plugin file or directory.
            signature: Expected signature.

        Returns:
            VerificationResult with status and trust level.
        """
        plugin_name = signature.plugin_name
        log = logger.bind(plugin=plugin_name)

        # Step 1: Verify checksum
        if plugin_path.is_dir():
            actual_checksum = self._signer.calculate_directory_checksum(plugin_path)
        else:
            actual_checksum = self._signer.calculate_checksum(plugin_path)

        if actual_checksum != signature.checksum_sha256:
            log.warning(
                "checksum_mismatch",
                expected=signature.checksum_sha256[:16],
                actual=actual_checksum[:16],
            )
            return VerificationResult(
                plugin_name=plugin_name,
                status=VerificationStatus.CHECKSUM_MISMATCH,
                trust_level=TrustLevel.UNKNOWN,
                message="Checksum verification failed",
                signature=signature,
            )

        # Step 2: If no GPG signature, return checksum-only verification
        if not signature.signature:
            log.info("checksum_verified", checksum=actual_checksum[:16])
            return VerificationResult(
                plugin_name=plugin_name,
                status=VerificationStatus.VERIFIED,
                trust_level=TrustLevel.CHECKSUM_VALID,
                message="Checksum verified (no signature)",
                signature=signature,
            )

        # Step 3: Verify GPG signature
        gpg_result = self._verify_gpg_signature(
            signature.checksum_sha256,
            signature.signature,
        )

        if not gpg_result["valid"]:
            log.warning("signature_invalid", error=gpg_result.get("error"))
            return VerificationResult(
                plugin_name=plugin_name,
                status=VerificationStatus.SIGNATURE_INVALID,
                trust_level=TrustLevel.CHECKSUM_VALID,
                message=f"Signature verification failed: {gpg_result.get('error', 'Unknown error')}",
                signature=signature,
            )

        # Step 4: Check signature expiration
        if signature.expires_at and signature.expires_at < datetime.now(tz=UTC):
            log.warning("signature_expired", expires_at=signature.expires_at)
            return VerificationResult(
                plugin_name=plugin_name,
                status=VerificationStatus.SIGNATURE_EXPIRED,
                trust_level=TrustLevel.CHECKSUM_VALID,
                message="Signature has expired",
                signature=signature,
            )

        # Step 5: Check if signer is trusted
        if signature.signer_key_id and signature.signer_key_id in self.trusted_keys:
            log.info("plugin_trusted", signer=signature.signer_key_id)
            return VerificationResult(
                plugin_name=plugin_name,
                status=VerificationStatus.VERIFIED,
                trust_level=TrustLevel.TRUSTED,
                message="Plugin verified and trusted",
                signature=signature,
            )

        # Signature valid but key not in trusted list
        log.info("plugin_signed", signer=signature.signer_key_id)
        return VerificationResult(
            plugin_name=plugin_name,
            status=VerificationStatus.VERIFIED,
            trust_level=TrustLevel.SIGNED,
            message="Plugin signature verified (key not in trusted list)",
            signature=signature,
        )

    def _verify_gpg_signature(
        self,
        data: str,
        signature: str,
    ) -> dict[str, Any]:
        """Verify GPG signature.

        Args:
            data: Original data that was signed.
            signature: GPG signature to verify.

        Returns:
            Dict with 'valid' boolean and optional 'error' message.
        """
        try:
            # Write signature to temp file
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".sig", delete=False) as sig_file:
                sig_file.write(signature)
                sig_path = sig_file.name

            try:
                # Verify signature
                result = subprocess.run(
                    ["gpg", "--verify", sig_path, "-"],
                    input=data.encode(),
                    capture_output=True,
                )
                return {"valid": result.returncode == 0}
            finally:
                Path(sig_path).unlink(missing_ok=True)

        except FileNotFoundError:
            return {"valid": False, "error": "GPG not available"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def add_trusted_key(self, key_id: str) -> None:
        """Add a key to the trusted list.

        Args:
            key_id: GPG key ID to trust.
        """
        self.trusted_keys.add(key_id)
        logger.info("trusted_key_added", key_id=key_id)

    def remove_trusted_key(self, key_id: str) -> bool:
        """Remove a key from the trusted list.

        Args:
            key_id: GPG key ID to remove.

        Returns:
            True if key was removed, False if not found.
        """
        if key_id in self.trusted_keys:
            self.trusted_keys.remove(key_id)
            logger.info("trusted_key_removed", key_id=key_id)
            return True
        return False
