"""集中配置：全部从项目根目录的 .env 读取（通过 pydantic-settings）。

设计要点：
- 密钥字段（授权码 / MiniMax Key / Fernet Key）设为 Optional，缺失时不会在导入期报错，
  而是由具体使用方通过 require() 给出友好提示后退出 —— 这样三个命脉脚本可以各自独立运行，
  只需填自己用到的那几个变量。
- env_file 指向项目根的绝对路径，无论从哪个工作目录运行脚本都能正确加载 .env。
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 同时尝试「源码根目录的 .env」和「当前工作目录的 .env」：
        # 前者适配本地开发/可编辑安装；后者适配 systemd(WorkingDirectory)/非可编辑安装。
        env_file=(PROJECT_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----- 126 邮箱 (IMAP 收信) -----
    email_126: Optional[str] = None          # EMAIL_126: 126 邮箱地址
    imap_auth_code: Optional[str] = None     # IMAP_AUTH_CODE: 客户端授权码(非登录密码)
    imap_host: str = "imap.126.com"
    imap_port: int = 993

    # ----- 126 邮箱 (SMTP 发信, 与 IMAP 共用授权码) -----
    smtp_host: str = "smtp.126.com"
    smtp_port: int = 465

    # ----- 转发 -----
    forward_to: Optional[str] = None   # FORWARD_TO: 转发目标邮箱（.env 或控制台配置）
    subject_prefix: str = "[Winnow] "

    # ----- MiniMax (可替换适配器: base_url/key/model 全部走配置) -----
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_api_key: Optional[str] = None
    minimax_model: str = "MiniMax-M2.5"

    # ----- 判断 / 限速 (Phase 1 就位, 后续管线使用) -----
    importance_threshold: float = 0.75
    forward_interval_seconds: int = 5
    daily_forward_limit: int = 200
    # 服务器不支持 IMAP IDLE 时(如网易 126/163)的轮询间隔秒数
    poll_interval_seconds: int = 30

    # ----- 存储 / 加密 (Phase 2 使用) -----
    database_url: str = "sqlite:///winnow.db"
    fernet_key: Optional[str] = None
    # Web 控制台 session Cookie 签名密钥（需稳定，否则重启后登录失效）
    session_secret: Optional[str] = None
    # 是否允许新用户自助注册
    allow_registration: bool = True
    # 邀请码：设置后注册必须提供匹配的邀请码（公开实例防滥用）；留空则开放注册
    registration_invite_code: Optional[str] = None


settings = Settings()


def require(value: Optional[str], env_name: str) -> str:
    """确保必填的密钥/配置已提供，否则给出友好提示并退出。"""
    if not value:
        raise SystemExit(
            f"❌ 缺少必填配置 {env_name}。\n"
            f"   请复制 .env.example 为 .env，填入真实值后重试。"
        )
    return value
