# from cryptography.fernet import Fernet, InvalidToken # Removed
from passlib.context import CryptContext

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# --- Fernet Symmetric Encryption (REMOVED as pgcrypto is used for credentials) ---

# Ensure the secret key is the correct format (32 url-safe base64 bytes)
# try:
#     _key = base64.urlsafe_b64decode(settings.APP_SECRET_KEY)
#     if len(_key) != 32:
#         raise ValueError("APP_SECRET_KEY must be 32 url-safe base64-encoded bytes.")
#     fernet = Fernet(_key)
# except (TypeError, ValueError) as e:
#     # Handle case where key might be missing or invalid during import
#     print(f"ERROR: Invalid APP_SECRET_KEY: {e}. Encryption/decryption will fail.")
#     # Assign a dummy Fernet instance or handle appropriately
#     # In a real app, you might want to raise a critical configuration error
#     fernet = None  # Or raise ConfigurationError("Invalid APP_SECRET_KEY")

# def encrypt_data(data: str) -> bytes:
#     """Encrypts a string and returns bytes."""
#     if fernet is None:
#         raise ValueError("Encryption key is not configured correctly.")
#     return fernet.encrypt(data.encode("utf-8"))

# def decrypt_data(encrypted_data: bytes) -> str:
#     """Decrypts bytes and returns the original string."""
#     if fernet is None:
#         raise ValueError("Encryption key is not configured correctly.")
#     try:
#         decrypted_bytes = fernet.decrypt(encrypted_data)
#         return decrypted_bytes.decode("utf-8")
#     except InvalidToken:
#         # Handle cases where the token is invalid or corrupt
#         # Log this securely
#         raise ValueError("Invalid or corrupt encrypted data")
#     except Exception as e:
#         # Catch other potential errors during decryption
#         # Log this securely
#         print(f"Error decrypting data: {e}")
#         raise
