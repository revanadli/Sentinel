"""
Keamanan identitas peserta JKN Sentinel.

- Pseudonim  : HMAC-SHA256(kunci rahasia, ID peserta). Tanpa kunci, pseudonim tidak bisa
               ditebak/dibuat ulang (lebih kuat daripada hash + salt biasa).
- Brankas    : tabel pseudonim -> ID asli, DIENKRIPSI (Fernet/AES). Hanya bisa dibuka dengan
               kunci brankas, lewat server dan hanya untuk peran berwenang; setiap pembukaan
               dicatat di log audit (lihat server.py).
- Kunci      : dibaca dari environment (SENTINEL_HMAC_KEY, SENTINEL_VAULT_KEY). Bila belum ada,
               dibuat otomatis di folder .secrets/ (tidak masuk git). Produksi: secrets manager.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

SECRETS = Path(__file__).resolve().parent / ".secrets"
VAULT_FILE = SECRETS / "vault.enc"


def _load_key(env_name, filename, maker):
    val = os.environ.get(env_name)
    if val:
        return val.encode()
    SECRETS.mkdir(exist_ok=True)
    f = SECRETS / filename
    if not f.exists():
        f.write_bytes(maker())
    return f.read_bytes().strip()


def hmac_key():
    return _load_key("SENTINEL_HMAC_KEY", "hmac.key", lambda: base64.urlsafe_b64encode(os.urandom(32)))


def vault_key():
    return _load_key("SENTINEL_VAULT_KEY", "vault.key", Fernet.generate_key)


def pseudonim(val):
    """ID peserta -> kode 16 heksadesimal (HMAC-SHA256)."""
    return hmac.new(hmac_key(), str(val).encode(), hashlib.sha256).hexdigest()[:16]


def buat_vault(mapping):
    """mapping: {pseudonim: id_asli}. Disimpan terenkripsi."""
    token = Fernet(vault_key()).encrypt(json.dumps(mapping).encode())
    SECRETS.mkdir(exist_ok=True)
    VAULT_FILE.write_bytes(token)


def buka_identitas(pseudo):
    """Kembalikan ID asli untuk satu pseudonim, atau None. Panggil hanya setelah otorisasi + audit."""
    if not VAULT_FILE.exists():
        return None
    data = json.loads(Fernet(vault_key()).decrypt(VAULT_FILE.read_bytes()))
    return data.get(pseudo)
