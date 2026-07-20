import jwt
import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("s3cr3t!")
    assert verify_password("s3cr3t!", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token = create_access_token(user_id=42, role="admin")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_tampered_token_is_rejected():
    token = create_access_token(user_id=1, role="engineer")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "x")
