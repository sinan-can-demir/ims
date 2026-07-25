# app/core/security.py

import bcrypt

# bcrypt silently truncates anything past 72 bytes rather than erroring —
# two different passwords sharing a 72-byte prefix would then hash
# identically. Reject up front instead of inheriting that footgun.
_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    encoded = plain.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
