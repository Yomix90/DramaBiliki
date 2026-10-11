import pytest
from bridge.auth import create_access_token, decode_access_token, get_or_create_device_user
from bridge.database import SessionLocal, init_db
from bridge.models import User

def test_jwt_token_flow():
    token = create_access_token({"sub": "42", "device_id": "test_device_123"})
    assert isinstance(token, str)
    
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["device_id"] == "test_device_123"

def test_device_user_creation():
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_device_user(
            device_id="unique_device_xyz",
            platform_os="android",
            preferred_language="fr",
            db=db,
        )
        assert user.id is not None
        assert user.device_id == "unique_device_xyz"
        assert user.preferred_language == "fr"
    finally:
        db.close()
