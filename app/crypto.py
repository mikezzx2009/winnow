"""凭据加解密：126 授权码用 Fernet 加密后入库，密钥从环境变量 FERNET_KEY 读取。

生成密钥：
    python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.config import settings


def _fernet() -> Fernet:
    if not settings.fernet_key:
        raise RuntimeError(
            "FERNET_KEY 未配置，无法加解密凭据。请在 .env 设置 FERNET_KEY（见 .env.example）。"
        )
    return Fernet(settings.fernet_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
