#!/usr/bin/env python3
import re, secrets, sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAIN = ROOT / "keys.plain.txt"
ENC = ROOT / "keys.enc"
SEED = b"VantaKeysVault_2026_taurikas_k9"

def parse_expiry(arg):
    if re.fullmatch(r"\+\d+d", arg):
        days = int(arg[1:-1])
        return (date.today() + timedelta(days=days)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
        return arg
    raise ValueError("Expiry must be YYYY-MM-DD or +Nd (example: +30d)")

def make_key():
    raw = secrets.token_hex(8).upper()
    return "VNTA-{}-{}-{}-{}".format(raw[0:4], raw[4:8], raw[8:12], raw[12:16])

def load_lines():
    if not PLAIN.exists():
        return ["# key=YYYY-MM-DD (one per line)\n"]
    return PLAIN.read_text(encoding="utf-8").splitlines(keepends=True)

def save_lines(lines):
    PLAIN.write_text("".join(lines), encoding="utf-8")

def revoke(key):
    key = key.strip().upper()
    lines = load_lines()
    out = []
    removed = False
    for line in lines:
        body = line.strip()
        if not body or body.startswith("#"):
            out.append(line if line.endswith("\n") else line + "\n")
            continue
        if body.split("=", 1)[0].strip().upper() == key:
            removed = True
            continue
        out.append(line if line.endswith("\n") else line + "\n")
    if not removed:
        print("Key not found:", key)
        sys.exit(1)
    save_lines(out)
    print("Revoked", key)

def encrypt_keys():
    import hashlib, hmac, secrets
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
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
    print("Encrypted ->", ENC, "({} bytes)".format(ENC.stat().st_size))

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  generate-key.py 2026-12-31")
        print("  generate-key.py +30d")
        print("  generate-key.py --revoke VNTA-XXXX-XXXX-XXXX-XXXX")
        sys.exit(1)

    if sys.argv[1] == "--revoke":
        if len(sys.argv) < 3:
            print("Missing key to revoke")
            sys.exit(1)
        revoke(sys.argv[2])
    else:
        expiry = parse_expiry(sys.argv[1])
        note = " ".join(sys.argv[2:]).strip()
        key = make_key()
        lines = load_lines()
        suffix = ("  # " + note) if note else ""
        lines.append("{}={}{}\n".format(key, expiry, suffix))
        save_lines(lines)
        print("Generated:", key)
        print("Expires:", expiry)

    encrypt_keys()
    print("Push keys.enc to GitHub when ready.")

if __name__ == "__main__":
    main()