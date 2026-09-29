import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional
from cryptography.fernet import Fernet
from app.config import get_settings

settings = get_settings()


def get_fernet_cipher() -> Fernet:
    key = settings.FERNET_KEY.encode()
    return Fernet(key)


def encrypt_token(plain_text: str) -> str:
    if not plain_text:
        return ""
    cipher = get_fernet_cipher()
    return cipher.encrypt(plain_text.encode()).decode()


def decrypt_token(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        cipher = get_fernet_cipher()
        return cipher.decrypt(cipher_text.encode()).decode()
    except Exception:
        return ""


def hash_passcode(passcode: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        passcode.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    )
    return f"{salt}${key.hex()}"


def verify_passcode(passcode: str, hashed: str) -> bool:
    if not hashed or "$" not in hashed:
        return False
    try:
        salt, expected_hex = hashed.split("$", 1)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            passcode.encode("utf-8"),
            salt.encode("utf-8"),
            100000
        )
        return hmac.compare_digest(key.hex(), expected_hex)
    except Exception:
        return False


def create_dj_session_token(station_slug: str, expires_in_seconds: int = 86400) -> str:
    expires_at = int(time.time()) + expires_in_seconds
    raw_payload = f"{station_slug}:{expires_at}"
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    combined = f"{raw_payload}:{signature}"
    return base64.urlsafe_b64encode(combined.encode("utf-8")).decode("utf-8")


def verify_dj_session_token(token: str, expected_slug: str) -> bool:
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        parts = decoded.split(":")
        if len(parts) != 3:
            return False
        slug, exp_str, signature = parts
        if slug != expected_slug:
            return False
        expires_at = int(exp_str)
        if time.time() > expires_at:
            return False
        raw_payload = f"{slug}:{expires_at}"
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            raw_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected_sig)
    except Exception:
        return False


def create_oauth_state(station_slug: str, expires_in_seconds: int = 600) -> str:
    expires_at = int(time.time()) + expires_in_seconds
    nonce = secrets.token_hex(8)
    raw_payload = f"{station_slug}:{expires_at}:{nonce}"
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    combined = f"{raw_payload}:{signature}"
    return base64.urlsafe_b64encode(combined.encode("utf-8")).decode("utf-8")


def verify_oauth_state(state: str, expected_slug: str) -> bool:
    if not state:
        return False
    try:
        decoded = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        parts = decoded.split(":")
        if len(parts) != 4:
            return False
        slug, exp_str, nonce, signature = parts
        if slug != expected_slug:
            return False
        expires_at = int(exp_str)
        if time.time() > expires_at:
            return False
        raw_payload = f"{slug}:{expires_at}:{nonce}"
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            raw_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected_sig)
    except Exception:
        return False
