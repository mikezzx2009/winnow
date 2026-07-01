"""Winnow Web 控制台入口（FastAPI）。

- 会话认证：Starlette SessionMiddleware（签名 HttpOnly Cookie）。
- API 挂载在 /api。
- 前端：托管 web/dist 的 React 构建产物；SPA 路由回退到 index.html。

启动：uv run winnow web   （或 uvicorn app.web.main:app）
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import PROJECT_ROOT, settings
from app.db import init_db
from app.web.api import router as api_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Winnow 控制台", docs_url="/api/docs", openapi_url="/api/openapi.json")

_secret = settings.session_secret or settings.fernet_key or "winnow-dev-secret-change-me"
if _secret == "winnow-dev-secret-change-me":
    logger.warning("未设置 SESSION_SECRET，使用开发默认值；生产请在 .env 配置 SESSION_SECRET。")
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret,
    same_site="lax",
    https_only=False,  # 阿里云若配了 HTTPS 可改为 True
)

app.include_router(api_router, prefix="/api")

_DIST = PROJECT_ROOT / "web" / "dist"


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "frontend_built": (_DIST / "index.html").exists()}


if (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


@app.get("/{full_path:path}")
def spa(full_path: str):
    """SPA 回退：任意非 /api 路径都返回前端首页，交给前端路由处理。"""
    index = _DIST / "index.html"
    if not index.exists():
        return JSONResponse(
            {"detail": "前端尚未构建。请在 web/ 下执行 `pnpm install && pnpm build`。"},
            status_code=503,
        )
    return FileResponse(str(index))
