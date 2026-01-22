from cryptography.fernet import Fernet

from app import settings

fernet = Fernet(settings.FERNET_KEY.encode())

def encrypt(text: str) -> str:
    return fernet.encrypt(text.encode()).decode()

def decrypt(text: str) -> str:
    return fernet.decrypt(text.encode()).decode()
