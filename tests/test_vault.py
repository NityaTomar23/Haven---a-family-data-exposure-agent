"""Tests for the encrypted SQLite vault and conservative minor handling."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from haven.fixtures import SyntheticListing
from haven.seed import redact_high_sensitivity
from haven.vault import EncryptedVault, VaultDecryptionError


def test_vault_encrypts_at_rest_and_round_trips_family(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HAVEN_DISABLE_OS_KEYRING", "1")
    db_file = tmp_path / "vault.db"
    vault = EncryptedVault(db_file)

    vault.update_household(
        address="742 Evergreen Terrace",
        city="Springfield",
        state="OR",
        zip_code="97477",
        jurisdiction="OCPA",
    )
    family = vault.add_member(
        first_name="Alex",
        last_name="Exampleton",
        role="parent",
        age=39,
        email="alex.exampleton@example.com",
        phone="555-555-0133",
        aliases=["Al Exampleton"],
    )

    assert len(family.members) == 1
    assert family.members[0].first_name == "Alex"
    assert family.city == "Springfield"
    assert family.state == "OR"

    # Verify raw SQLite bytes do NOT contain plain-text identifiers
    conn = sqlite3.connect(str(db_file))
    rows = conn.execute("SELECT ciphertext FROM vault_records").fetchall()
    conn.close()
    assert rows
    raw_bytes = b"".join(bytes(r[0]) for r in rows)
    assert b"Exampleton" not in raw_bytes
    assert b"742 Evergreen Terrace" not in raw_bytes
    assert b"555-0133" not in raw_bytes

    # Re-open with same keyfile
    reopened = EncryptedVault(db_file)
    loaded = reopened.load_family()
    assert loaded is not None
    assert loaded.members[0].first_name == "Alex"
    assert loaded.address == "742 Evergreen Terrace"


def test_vault_rejects_wrong_decryption_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HAVEN_DISABLE_OS_KEYRING", "1")
    db_file = tmp_path / "vault.db"
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()

    v1 = EncryptedVault(db_file, key=key1)
    v1.add_member(first_name="Robin", last_name="Sample", role="parent", age=34)

    v2 = EncryptedVault(db_file, key=key2)
    with pytest.raises(VaultDecryptionError):
        v2.load_family()


def test_vault_supports_passphrase_derivation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HAVEN_DISABLE_OS_KEYRING", "1")
    monkeypatch.setenv("HAVEN_VAULT_KEY", "correct-horse-battery-staple-test-pass")
    db_file = tmp_path / "vault.db"

    v1 = EncryptedVault(db_file)
    v1.add_member(first_name="Sam", last_name="Passphrase", role="parent", age=45)

    v2 = EncryptedVault(db_file)
    loaded = v2.load_family()
    assert loaded is not None
    assert loaded.members[0].last_name == "Passphrase"


def test_vault_member_and_identifier_crud(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HAVEN_DISABLE_OS_KEYRING", "1")
    vault = EncryptedVault(tmp_path / "vault.db")
    fam = vault.add_member(
        first_name="Taylor",
        last_name="Testfamily",
        role="parent",
        age=38,
        email="taylor@example.com",
        city="Austin",
        state="TX",
    )
    mem_id = fam.members[0].member_id

    fam = vault.update_member(mem_id, first_name="Taylor-Updated", age=39)
    assert fam.members[0].first_name == "Taylor-Updated"
    assert fam.members[0].age == 39

    fam = vault.add_identifier(mem_id, kind="alias", value="T. Testfamily", sensitivity="low")
    assert any(i.value == "T. Testfamily" for i in fam.members[0].identifiers)

    fam = vault.delete_identifier(mem_id, kind="alias", value="T. Testfamily")
    assert not any(i.value == "T. Testfamily" for i in fam.members[0].identifiers)

    fam = vault.delete_member(mem_id)
    assert fam.members == []


def test_minor_requires_explicit_parental_consent_and_redacts_conservatively(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("HAVEN_DISABLE_OS_KEYRING", "1")
    vault = EncryptedVault(tmp_path / "vault.db")

    # Adding a child without parental_consent_confirmed raises ValueError
    with pytest.raises(ValueError, match="parental_consent_confirmed"):
        vault.add_member(
            first_name="Riley",
            last_name="Synthwell",
            role="child",
            age=12,
            parental_consent_confirmed=False,
        )

    # With explicit parental confirmation, all child identifiers are marked high sensitivity
    fam = vault.add_member(
        first_name="Riley",
        last_name="Synthwell",
        role="child",
        age=12,
        parental_consent_confirmed=True,
    )
    child = fam.members[0]
    assert child.is_minor is True
    assert all(i.sensitivity == "high" for i in child.identifiers)

    redacted = redact_high_sensitivity(fam)
    assert all(i.value == "[REDACTED]" for i in redacted.members[0].identifiers)


def test_vault_listings_and_wipe(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HAVEN_DISABLE_OS_KEYRING", "1")
    db_file = tmp_path / "vault.db"
    vault = EncryptedVault(db_file)
    vault.add_member(first_name="Avery", last_name="Synthwell", role="parent", age=41)
    vault.add_listing(
        SyntheticListing(
            broker="Spokeo",
            broker_type="people_search",
            url="https://spokeo.example/p/avery",
            location="Sampleville, CA",
            text="Avery Synthwell, Sampleville, CA",
        )
    )
    assert len(vault.load_listings()) == 1

    vault.wipe()
    assert vault.load_family() is None
    assert vault.load_listings() == []
    assert not vault.key_path.exists()
