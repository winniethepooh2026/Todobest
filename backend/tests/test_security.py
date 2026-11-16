from uuid import uuid4

import pytest
from jwt import InvalidTokenError

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_access_token_type_is_enforced() -> None:
    token = create_access_token(uuid4())
    assert decode_token(token, "access")["typ"] == "access"
    with pytest.raises(InvalidTokenError):
        decode_token(token, "refresh")
