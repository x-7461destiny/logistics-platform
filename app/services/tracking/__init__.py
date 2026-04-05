from jose import JWTError, jwt

from .driver_tracking import driver_tracker
from .location_update import update_driver_locations


def verify_token(token: str, driver_id: str) -> bool:
    if not token:
        return False
    try:
        payload = jwt.decode(token, "your-secret-key", algorithms=["HS256"])
        return str(payload.get("user_id")) == str(driver_id)
    except JWTError:
        return False


__all__ = ["update_driver_locations", "driver_tracker", "verify_token"]
