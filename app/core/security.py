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


# Fixed, hardcoded hash -- not a real credential, its plaintext is never
# used to authenticate anything. Exists purely so a caller with no real
# password hash to check against (an unknown email, or a locked-out
# account short-circuiting before ever loading one) still pays the same
# bcrypt cost as a real check, instead of skipping it and leaking which
# branch it took through response timing (see authenticate_user()).
_DUMMY_HASH = "$2b$12$ZoFguZiZsaUrpkwWZ3Y6ZeeOaZSldWoIleo1ShL0PbIHq9O2ou3s6"


def verify_password_or_dummy(plain: str, hashed: str | None) -> bool:
    """
    Same cost as verify_password() regardless of whether a real hash
    exists — checks against _DUMMY_HASH when hashed is None, and always
    returns False on that path (the dummy hash's real plaintext is
    neither known to nor derivable by a caller of this function).
    """
    if hashed is None:
        verify_password(plain, _DUMMY_HASH)
        return False
    return verify_password(plain, hashed)
