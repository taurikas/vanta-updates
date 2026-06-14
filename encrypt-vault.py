#!/usr/bin/env python3
import hashlib, hmac, json, secrets, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

ROOT = Path(__file__).resolve().parent

def encrypt_bytes(plain: bytes, seed: bytes) -> bytes:
    aes = hashlib.sha256(seed).digest()
    hk = hashlib.sha256(aes + b"hmac").digest()
    iv = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(aes), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    tag = hmac.new(hk, iv + ct, hashlib.sha256).digest()
    return b"VNTM" + iv + tag + ct

def encrypt_file(src: Path, dst: Path, seed: bytes) -> None:
    plain = src.read_text(encoding="utf-8")
    blob = encrypt_bytes(plain.encode("utf-8"), seed)
    dst.write_bytes(blob)
    print("Wrote {} ({} bytes)".format(dst, len(blob)))

def main():
    if len(sys.argv) < 4:
        print("Usage: encrypt-vault.py <plain.txt> <out.enc> <seed>")
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    seed = sys.argv[3].encode("utf-8")
    encrypt_file(src, dst, seed)

if __name__ == "__main__":
    main()