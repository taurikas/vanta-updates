"""Shared license key database (plain + encrypted)."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parent
PLAIN = ROOT / "keys.plain.txt"
ENC = ROOT / "keys.enc"
SEED = b"VantaKeysVault_2026_taurikas_k9"

KEY_PATTERN = re.compile(r"^VNTA-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$")
EXPIRY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DURATION_PATTERN = re.compile(r"^\+(\d+)d$", re.IGNORECASE)


@dataclass
class KeyRecord:
    key: str
    expires: date
    discord_id: Optional[int] = None
    note: str = ""


def normalize_key(key: str) -> str:
    return key.strip().upper()


def parse_expiry_arg(arg: str) -> date:
    arg = arg.strip()
    m = DURATION_PATTERN.fullmatch(arg)
    if m:
        return date.today() + timedelta(days=int(m.group(1)))
    if EXPIRY_PATTERN.fullmatch(arg):
        y, mo, d = (int(x) for x in arg.split("-"))
        return date(y, mo, d)
    raise ValueError("Expiry must be YYYY-MM-DD or +Nd (example: +30d)")


def make_key() -> str:
    raw = secrets.token_hex(8).upper()
    return f"VNTA-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


def _parse_value(value: str):
    body = value.split("#", 1)[0].strip()
    note = value.split("#", 1)[1].strip() if "#" in value else ""
    discord_id = None
    if "|" in body:
        date_part, id_part = body.split("|", 1)
        body = date_part.strip()
        id_part = id_part.strip()
        if id_part.isdigit():
            discord_id = int(id_part)
    if not EXPIRY_PATTERN.fullmatch(body):
        raise ValueError(f"Invalid expiry date: {body}")
    y, mo, d = (int(x) for x in body.split("-"))
    return date(y, mo, d), discord_id, note


def _format_line(record: KeyRecord) -> str:
    line = f"{record.key}={record.expires.isoformat()}"
    if record.discord_id is not None:
        line += f"|{record.discord_id}"
    if record.note:
        line += f"  # {record.note}"
    return line + "\n"


def load_records():
    if not PLAIN.exists():
        return []
    records = []
    for raw_line in PLAIN.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq == -1:
            continue
        key = normalize_key(line[:eq])
        if not KEY_PATTERN.fullmatch(key):
            continue
        try:
            expires, discord_id, note = _parse_value(line[eq + 1:])
        except ValueError:
            continue
        records.append(KeyRecord(key=key, expires=expires, discord_id=discord_id, note=note))
    return records


def save_records(records):
    lines = ["# key=YYYY-MM-DD|discord_id (discord_id required for bot delivery)\n"]
    for record in records:
        lines.append(_format_line(record))
    PLAIN.write_text("".join(lines), encoding="utf-8")


def encrypt_keys():
    plain = PLAIN.read_text(encoding="utf-8").encode("utf-8")
    aes = hashlib.sha256(SEED).digest()
    hk = hashlib.sha256(aes + b"hmac").digest()
    iv = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(aes), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    tag = hmac.new(hk, iv + ct, hashlib.sha256).digest()
    ENC.write_bytes(b"VNTM" + iv + tag + ct)


def find_record(records, key):
    key = normalize_key(key)
    for record in records:
        if record.key == key:
            return record
    return None


def revoke_key(key):
    key = normalize_key(key)
    records = load_records()
    kept = [r for r in records if r.key != key]
    if len(kept) == len(records):
        return False
    save_records(kept)
    encrypt_keys()
    return True


def generate_for_user(discord_id, expiry, note=""):
    if discord_id <= 0:
        raise ValueError("Invalid Discord user id")
    records = load_records()
    for record in records:
        if record.discord_id == discord_id and not is_expired(record):
            raise ValueError("User already has an active key. Revoke it first.")
    record = KeyRecord(key=make_key(), expires=expiry, discord_id=discord_id, note=note)
    records.append(record)
    save_records(records)
    encrypt_keys()
    return record


def is_expired(record, today=None):
    today = today or date.today()
    return today > record.expires


def validate_for_discord(key, discord_id):
    key = normalize_key(key)
    if not KEY_PATTERN.fullmatch(key):
        return False, "Invalid license key format."
    record = find_record(load_records(), key)
    if record is None:
        return False, "Invalid license key."
    if is_expired(record):
        return False, f"This license expired on {record.expires.isoformat()}."
    if record.discord_id is None:
        return False, "This license is not linked to a Discord account."
    if record.discord_id != discord_id:
        return False, "This license key belongs to another Discord account."
    return True, "ok"
