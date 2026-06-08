import base64
import hashlib
import os

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


KEY_FILE_ENV = "PRICONNE_CREDENTIAL_KEY_FILE"
KEY_ENV = "PRICONNE_CREDENTIAL_KEY"
PASSWORD_ENCRYPTED_FIELD = "password_encrypted"
TOKEN_PREFIX = "v1:"


class CredentialKeyError(Exception):
    pass


def _read_secret_material() -> bytes:
    key_file = os.getenv(KEY_FILE_ENV)
    if key_file:
        try:
            with open(key_file, "rb") as f:
                material = f.read().strip()
        except OSError as e:
            raise CredentialKeyError(f"无法读取 priconne 凭据密钥文件 {key_file}: {e}") from e
        if material:
            return material

    key = os.getenv(KEY_ENV)
    if key:
        return key.strip().encode("utf-8")

    raise CredentialKeyError(f"未配置 {KEY_FILE_ENV} 或 {KEY_ENV}，无法保存加密后的账号密码")


def _get_key() -> bytes:
    return hashlib.sha256(_read_secret_material()).digest()


def encrypt_password(password: str) -> str:
    if not password:
        raise ValueError("password is empty")

    nonce = get_random_bytes(12)
    cipher = AES.new(_get_key(), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(password.encode("utf-8"))
    payload = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")
    return TOKEN_PREFIX + payload


def decrypt_password(encrypted_password: str) -> str:
    if not encrypted_password or not encrypted_password.startswith(TOKEN_PREFIX):
        raise ValueError("不支持的 priconne 密码密文格式")

    payload = base64.urlsafe_b64decode(encrypted_password[len(TOKEN_PREFIX):].encode("ascii"))
    nonce = payload[:12]
    tag = payload[12:28]
    ciphertext = payload[28:]
    cipher = AES.new(_get_key(), AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")


def prepare_account_for_login(account_info: dict) -> dict:
    prepared = account_info.copy()
    if "password" not in prepared and PASSWORD_ENCRYPTED_FIELD in prepared:
        prepared["password"] = decrypt_password(prepared[PASSWORD_ENCRYPTED_FIELD])
    return prepared


def get_account_password(account_info: dict) -> str | None:
    if account_info.get("password"):
        return account_info["password"]
    if account_info.get(PASSWORD_ENCRYPTED_FIELD):
        return decrypt_password(account_info[PASSWORD_ENCRYPTED_FIELD])
    return None


def build_stored_account(account_info: dict, uid: str, access_key: str) -> dict:
    stored = account_info.copy()
    password = stored.pop("password", None)
    if password:
        stored[PASSWORD_ENCRYPTED_FIELD] = encrypt_password(password)
    elif PASSWORD_ENCRYPTED_FIELD not in stored:
        raise CredentialKeyError("账号缺少可保存的密码，请重新绑定账号")

    stored["uid"] = uid
    stored["access_key"] = access_key
    return stored


def should_update_stored_account(account_info: dict, uid: str, access_key: str) -> bool:
    return (
        "password" in account_info
        or account_info.get("uid") != uid
        or account_info.get("access_key") != access_key
    )
