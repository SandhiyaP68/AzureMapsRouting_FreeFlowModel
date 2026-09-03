import jwt
from datetime import datetime, timedelta
from jose import JWTError
 
# JWT Configuration
JWT_SECRET = "7b8e8008df3e9cdbecfc18f8f38a6a1477a68fd696a9e05d03315f345851bb6d"
JWT_ALGORITHM = "HS256"
# JWT_EXPIRATION = timedelta(minutes=30)  # Adjust expiration as needed
 
# Create JWT token for a user
def create_jwt_token(user_id: str):
    payload = {
        "user_id": user_id
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token
 
# Verify JWT token
def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
