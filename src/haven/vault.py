"""Local encrypted SQLite vault for Haven family profiles, listings, and removal tracking.

Personal data never leaves the user's machine except in the final, user-approved
opt-out request that the user sends to the broker themselves. All records in
SQLite are encrypted at rest using ``cryptography.fernet.Fernet`` (AES-128-CBC
with PKCS7 padding + HMAC-SHA256 authentication).

Key resolution order:
  1. Explicit ``key`` passed to :class:`EncryptedVault`
  2. ``HAVEN_VAULT_KEY`` environment variable (Fernet key or passphrase derived via PBKDF2-HMAC-SHA256)
  3. OS keyring (via ``keyring`` or Windows Credential Manager ``win32cred`` when available)
  4. Local restricted keyfile (``<vault_dir>/vault.key``, mode ``0600``)
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from haven.fixtures import SyntheticListing
from haven.models import Family, FamilyMember, Identifier, PipelineState

_KEYRING_SERVICE = "haven-privacy-vault"
_KEYRING_USERNAME = "master-fernet-key"
_PBKDF2_ITERATIONS = 600_000


class VaultDecryptionError(RuntimeError):
    """Raised when the vault cannot be decrypted with the provided key."""


def default_vault_path() -> Path:
    """Resolve the default SQLite vault path from ``HAVEN_VAULT_PATH`` or ``~/.haven/vault.db``."""
    override = os.environ.get("HAVEN_VAULT_PATH", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".haven" / "vault.db"


def _derive_fernet_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a URL-safe 32-byte Fernet key from *passphrase* and *salt*."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _is_valid_fernet_key(candidate: str) -> bool:
    try:
        Fernet(candidate.encode("ascii"))
        return True
    except Exception:
        return False


def _keyring_get(service: str, username: str) -> str | None:
    """Read a secret from the OS keyring if available."""
    if os.environ.get("HAVEN_DISABLE_OS_KEYRING", "").strip() == "1":
        return None
    try:
        import keyring  # type: ignore[import-not-found]

        val = keyring.get_password(service, username)
        if val:
            return str(val)
    except Exception:
        pass

    if os.name == "nt":
        try:
            import win32cred  # type: ignore[import-untyped]

            cred = win32cred.CredRead(f"{service}:{username}", win32cred.CRED_TYPE_GENERIC, 0)
            blob = cred.get("CredentialBlob")
            if isinstance(blob, bytes):
                decoded = blob.decode("utf-16-le", errors="ignore").strip("\x00")
                if decoded and _is_valid_fernet_key(decoded):
                    return decoded
        except Exception:
            pass
    return None


def _keyring_set(service: str, username: str, secret: str) -> bool:
    """Store a secret in the OS keyring if available."""
    if os.environ.get("HAVEN_DISABLE_OS_KEYRING", "").strip() == "1":
        return False
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.set_password(service, username, secret)
        return True
    except Exception:
        pass

    if os.name == "nt":
        try:
            import win32cred  # type: ignore[import-untyped]

            win32cred.CredWrite(
                {
                    "Type": win32cred.CRED_TYPE_GENERIC,
                    "TargetName": f"{service}:{username}",
                    "UserName": username,
                    "CredentialBlob": secret,
                    "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
            return True
        except Exception:
            pass
    return False


def _keyring_delete(service: str, username: str) -> None:
    """Delete a secret from the OS keyring if present."""
    if os.environ.get("HAVEN_DISABLE_OS_KEYRING", "").strip() == "1":
        return
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.delete_password(service, username)
    except Exception:
        pass

    if os.name == "nt":
        try:
            import win32cred  # type: ignore[import-untyped]

            win32cred.CredDelete(f"{service}:{username}", win32cred.CRED_TYPE_GENERIC, 0)
        except Exception:
            pass


class EncryptedVault:
    """SQLite-backed encrypted local store for family profiles and removal tracking."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        key: str | bytes | None = None,
        use_os_keyring: bool = False,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_vault_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path = self.db_path.with_suffix(".key")
        self.salt_path = self.db_path.with_suffix(".salt")
        self.use_os_keyring = use_os_keyring
        self._explicit_key = key
        self._fernet = Fernet(self._resolve_or_create_key())
        self._init_schema()

    def _resolve_or_create_key(self) -> bytes:
        if self._explicit_key is not None:
            raw = (
                self._explicit_key.decode("utf-8")
                if isinstance(self._explicit_key, bytes)
                else self._explicit_key
            )
            if _is_valid_fernet_key(raw):
                return raw.encode("ascii")
            return _derive_fernet_key(raw, self._get_or_create_salt())

        env_key = os.environ.get("HAVEN_VAULT_KEY", "").strip()
        if env_key:
            if _is_valid_fernet_key(env_key):
                return env_key.encode("ascii")
            return _derive_fernet_key(env_key, self._get_or_create_salt())

        scope_user = f"{_KEYRING_USERNAME}:{self.db_path.resolve()}"
        if self.use_os_keyring:
            stored = _keyring_get(_KEYRING_SERVICE, scope_user)
            if stored and _is_valid_fernet_key(stored):
                return stored.encode("ascii")

        if self.key_path.exists():
            content = self.key_path.read_text(encoding="utf-8").strip()
            if _is_valid_fernet_key(content):
                return content.encode("ascii")

        generated = Fernet.generate_key()
        generated_str = generated.decode("ascii")
        if self.use_os_keyring and _keyring_set(_KEYRING_SERVICE, scope_user, generated_str):
            return generated

        self.key_path.write_text(generated_str, encoding="utf-8")
        try:
            self.key_path.chmod(0o600)
        except OSError:
            pass
        return generated

    def _get_or_create_salt(self) -> bytes:
        if self.salt_path.exists():
            raw = self.salt_path.read_bytes()
            if len(raw) >= 16:
                return raw
        salt = secrets.token_bytes(16)
        self.salt_path.write_bytes(salt)
        try:
            self.salt_path.chmod(0o600)
        except OSError:
            pass
        return salt

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA secure_delete=ON")
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vault_records (
                    record_key TEXT PRIMARY KEY,
                    ciphertext BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _encrypt(self, payload: dict | list) -> bytes:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw)

    def _decrypt(self, token: bytes) -> dict | list:
        try:
            raw = self._fernet.decrypt(bytes(token))
            return json.loads(raw.decode("utf-8"))
        except InvalidToken as exc:
            raise VaultDecryptionError(
                "Failed to decrypt local vault record: invalid key or tampered ciphertext."
            ) from exc

    def _put_record(self, record_key: str, payload: dict | list) -> None:
        ciphertext = self._encrypt(payload)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vault_records (record_key, ciphertext, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(record_key) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    updated_at = excluded.updated_at
                """,
                (record_key, ciphertext, now),
            )
            conn.commit()

    def _get_record(self, record_key: str) -> dict | list | None:
        if not self.db_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ciphertext FROM vault_records WHERE record_key = ?",
                (record_key,),
            ).fetchone()
        if row is None:
            return None
        return self._decrypt(row[0])

    # ── Family CRUD ────────────────────────────────────────────────────────

    def load_family(self) -> Family | None:
        """Load and decrypt the stored family profile, or None if empty."""
        data = self._get_record("family")
        if not isinstance(data, dict):
            return None
        return Family.model_validate(data)

    def save_family(self, family: Family) -> Family:
        """Encrypt and save *family* to the SQLite vault."""
        for idx, member in enumerate(family.members):
            if not member.member_id:
                member.member_id = f"mem_{idx + 1}_{uuid.uuid4().hex[:6]}"
        self._put_record("family", family.model_dump(mode="json"))
        return family

    def ensure_family(
        self,
        *,
        address: str = "",
        city: str = "",
        state: str = "CA",
        zip_code: str = "",
        jurisdiction: str = "CCPA",
    ) -> Family:
        """Return the stored family, or initialize a new empty household."""
        existing = self.load_family()
        if existing is not None:
            return existing
        family = Family(
            family_id=str(uuid.uuid4()),
            members=[],
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            jurisdiction=jurisdiction,
            is_synthetic=False,
            created_at=datetime.now(timezone.utc),
        )
        return self.save_family(family)

    def update_household(
        self,
        *,
        address: str,
        city: str,
        state: str,
        zip_code: str,
        jurisdiction: str = "CCPA",
    ) -> Family:
        """Update household address and refresh member city_state/address identifiers."""
        family = self.ensure_family(
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            jurisdiction=jurisdiction,
        )
        family.address = address.strip()
        family.city = city.strip()
        family.state = state.strip().upper()
        family.zip_code = zip_code.strip()
        family.jurisdiction = jurisdiction.strip() or "CCPA"
        family.is_synthetic = False

        city_state = f"{family.city}, {family.state}".strip(", ")
        full_address = f"{family.address}, {city_state} {family.zip_code}".strip(", ")

        for member in family.members:
            updated_ids: list[Identifier] = [
                i for i in member.identifiers if i.kind not in ("city_state", "address")
            ]
            if family.city and family.state:
                updated_ids.append(
                    Identifier(kind="city_state", value=city_state, sensitivity="low")
                )
            if family.address:
                updated_ids.append(
                    Identifier(kind="address", value=full_address, sensitivity="high")
                )
            member.identifiers = updated_ids

        return self.save_family(family)

    def add_member(
        self,
        *,
        first_name: str,
        last_name: str,
        role: Literal["parent", "child"] = "parent",
        age: int = 35,
        email: str | None = None,
        phone: str | None = None,
        aliases: list[str] | None = None,
        parental_consent_confirmed: bool = False,
        address: str | None = None,
        city: str | None = None,
        state: str | None = None,
        zip_code: str | None = None,
    ) -> Family:
        """Add a member and their identifiers to the encrypted family profile."""
        family = self.load_family()
        if family is None or family.is_synthetic:
            family = Family(
                family_id=str(uuid.uuid4()),
                members=[],
                address=(address or "").strip(),
                city=(city or "").strip(),
                state=(state or "CA").strip().upper(),
                zip_code=(zip_code or "").strip(),
                jurisdiction="CCPA",
                is_synthetic=False,
                created_at=datetime.now(timezone.utc),
            )
        else:
            if address is not None:
                family.address = address.strip()
            if city is not None:
                family.city = city.strip()
            if state is not None:
                family.state = state.strip().upper()
            if zip_code is not None:
                family.zip_code = zip_code.strip()

        is_minor = role == "child" or age < 18
        if is_minor and not parental_consent_confirmed:
            raise ValueError(
                "Adding a minor (role='child' or age < 18) requires explicit "
                "parental_consent_confirmed=True."
            )

        full_name = f"{first_name.strip()} {last_name.strip()}".strip()
        identifiers: list[Identifier] = [
            Identifier(
                kind="name",
                value=full_name,
                sensitivity="high" if is_minor else "low",
            )
        ]

        for alias in aliases or []:
            if alias.strip():
                identifiers.append(
                    Identifier(
                        kind="alias",
                        value=alias.strip(),
                        sensitivity="high" if is_minor else "low",
                    )
                )

        if family.city and family.state:
            identifiers.append(
                Identifier(
                    kind="city_state",
                    value=f"{family.city}, {family.state}",
                    sensitivity="high" if is_minor else "low",
                )
            )

        if email and email.strip():
            identifiers.append(
                Identifier(kind="email", value=email.strip(), sensitivity="high")
            )
        if phone and phone.strip():
            identifiers.append(
                Identifier(kind="phone", value=phone.strip(), sensitivity="high")
            )
        if family.address:
            full_addr = (
                f"{family.address}, {family.city}, {family.state} {family.zip_code}".strip(", ")
            )
            identifiers.append(
                Identifier(kind="address", value=full_addr, sensitivity="high")
            )

        member = FamilyMember(
            member_id=f"mem_{uuid.uuid4().hex[:8]}",
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            role=role,
            age=age,
            identifiers=identifiers,
            parental_consent_confirmed=parental_consent_confirmed,
        )
        family.members.append(member)
        return self.save_family(family)

    def update_member(
        self,
        member_id: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        role: Literal["parent", "child"] | None = None,
        age: int | None = None,
        email: str | None = None,
        phone: str | None = None,
        parental_consent_confirmed: bool | None = None,
    ) -> Family:
        """Edit an existing member in the vault by ``member_id``."""
        family = self.load_family()
        if family is None:
            raise KeyError(f"Member {member_id} not found (vault is empty)")

        target: FamilyMember | None = None
        for member in family.members:
            if member.member_id == member_id:
                target = member
                break
        if target is None:
            raise KeyError(f"Member {member_id} not found")

        if first_name is not None:
            target.first_name = first_name.strip()
        if last_name is not None:
            target.last_name = last_name.strip()
        if role is not None:
            target.role = role
        if age is not None:
            target.age = age
        if parental_consent_confirmed is not None:
            target.parental_consent_confirmed = parental_consent_confirmed

        if target.is_minor and not target.parental_consent_confirmed:
            raise ValueError(
                "Minor profile updates require parental_consent_confirmed=True."
            )

        # Refresh primary name identifier
        kept = [i for i in target.identifiers if i.kind != "name"]
        kept.insert(
            0,
            Identifier(
                kind="name",
                value=f"{target.first_name} {target.last_name}".strip(),
                sensitivity="high" if target.is_minor else "low",
            ),
        )
        if email is not None:
            kept = [i for i in kept if i.kind != "email"]
            if email.strip():
                kept.append(Identifier(kind="email", value=email.strip(), sensitivity="high"))
        if phone is not None:
            kept = [i for i in kept if i.kind != "phone"]
            if phone.strip():
                kept.append(Identifier(kind="phone", value=phone.strip(), sensitivity="high"))

        target.identifiers = kept
        return self.save_family(family)

    def delete_member(self, member_id: str) -> Family:
        """Delete a family member by ``member_id``."""
        family = self.load_family()
        if family is None:
            raise KeyError(f"Member {member_id} not found")
        before = len(family.members)
        family.members = [m for m in family.members if m.member_id != member_id]
        if len(family.members) == before:
            raise KeyError(f"Member {member_id} not found")
        return self.save_family(family)

    def add_identifier(
        self,
        member_id: str,
        *,
        kind: Literal["name", "phone", "email", "address", "city_state", "alias"],
        value: str,
        sensitivity: Literal["low", "high"] = "high",
    ) -> Family:
        """Add an identifier to a specific family member."""
        family = self.load_family()
        if family is None:
            raise KeyError(f"Member {member_id} not found")
        for member in family.members:
            if member.member_id == member_id:
                effective_sens: Literal["low", "high"] = (
                    "high" if member.is_minor else sensitivity
                )
                member.identifiers.append(
                    Identifier(kind=kind, value=value.strip(), sensitivity=effective_sens)
                )
                return self.save_family(family)
        raise KeyError(f"Member {member_id} not found")

    def delete_identifier(self, member_id: str, *, kind: str, value: str) -> Family:
        """Delete a specific identifier from a family member."""
        family = self.load_family()
        if family is None:
            raise KeyError(f"Member {member_id} not found")
        for member in family.members:
            if member.member_id == member_id:
                member.identifiers = [
                    i
                    for i in member.identifiers
                    if not (i.kind == kind and i.value == value)
                ]
                return self.save_family(family)
        raise KeyError(f"Member {member_id} not found")

    # ── User-pasted / imported listings ────────────────────────────────────

    def load_listings(self) -> list[SyntheticListing]:
        """Load encrypted user-pasted or imported listings from the vault."""
        raw = self._get_record("listings")
        if not isinstance(raw, list):
            return []
        return [SyntheticListing.model_validate(item) for item in raw]

    def save_listings(self, listings: list[SyntheticListing]) -> list[SyntheticListing]:
        """Save user-pasted or imported listings to the encrypted vault."""
        self._put_record(
            "listings",
            [item.model_dump(mode="json") for item in listings],
        )
        return listings

    def add_listing(self, listing: SyntheticListing) -> list[SyntheticListing]:
        """Append or update a single user-pasted listing by URL."""
        current = [item for item in self.load_listings() if item.url != listing.url]
        current.append(listing)
        return self.save_listings(current)

    # ── Pipeline State persistence ─────────────────────────────────────────

    def load_state(self) -> PipelineState | None:
        """Load the encrypted pipeline state snapshot if stored."""
        raw = self._get_record("pipeline_state")
        if not isinstance(raw, dict):
            return None
        return PipelineState.model_validate(raw)

    def save_state(self, state: PipelineState) -> PipelineState:
        """Encrypt and persist the full pipeline state (exposures, drafts, tracking)."""
        self._put_record("pipeline_state", state.model_dump(mode="json"))
        self.save_family(state.family)
        return state

    # ── Cryptographic Wipe ─────────────────────────────────────────────────

    def wipe(self) -> None:
        """Irreversibly shred keys and delete all encrypted vault data."""
        if self.db_path.exists():
            try:
                with self._connect() as conn:
                    conn.execute("DELETE FROM vault_records")
                    conn.execute("VACUUM")
                    conn.commit()
            except Exception:
                pass

        scope_user = f"{_KEYRING_USERNAME}:{self.db_path.resolve()}"
        _keyring_delete(_KEYRING_SERVICE, scope_user)

        for path in (
            self.key_path,
            self.salt_path,
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            if path.exists():
                try:
                    size = max(64, path.stat().st_size)
                    path.write_bytes(secrets.token_bytes(size))
                    path.unlink()
                except OSError:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

        # Rotate in-memory Fernet key so the wiped instance cannot decrypt anything old
        self._fernet = Fernet(Fernet.generate_key())
        self._init_schema()
