#!/usr/bin/env python3
import hashlib, hmac, json, secrets, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

SEED = b"VantaManifestVault_2026_taurikas_x7"
ROOT = Path(__file__).resolve().parent

def keys():
    aes = hashlib.sha256(SEED).digest()
    hk = hashlib.sha256(aes + b"hmac").digest()
    return aes, hk

def encrypt_file(src, dst):
    plain = src.read_text(encoding="utf-8")
    json.loads(plain)
    aes, hk = keys()
    iv = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(aes), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    tag = hmac.new(hk, iv + ct, hashlib.sha256).digest()
    dst.write_bytes(b"VNTM" + iv + tag + ct)
    print("Wrote {} ({} bytes)".format(dst, dst.stat().st_size))

def main():
    src = ROOT / "manifest.plain.json"
    if len(sys.argv) > 1:
        data = json.loads(src.read_text(encoding="utf-8"))
        data["latest"] = sys.argv[1]
        src.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        (ROOT / "VERSION").write_text(sys.argv[1] + "\n", encoding="utf-8")
    encrypt_file(src, ROOT / "manifest.enc")

if __name__ == "__main__":
    main()