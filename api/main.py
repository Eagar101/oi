"""FastAPI应用入口"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db
from .routes import router

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    app = FastAPI(
        title="自动化深度研究智能体",
        description="4-Agent协作的深度研究后端：Planner→Search→Summary→Write",
        version="1.0.0",
    )

    # 初始化数据库
    db.init_db()

    # 挂载静态文件
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Jinja2模板
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # 注册API路由
    app.include_router(router, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ---------- 页面路由 ----------
    def _get_current_user(request: Request):
        """从cookie或Authorization头解析当前用户"""
        token = request.cookies.get("token")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
        if not token:
            return None
        result = auth.verify_token(token, auth.APIConfig())
        if not result.success:
            return None
        user = db.get_user_by_id(result.user_id)
        return user

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        user = _get_current_user(request)
        if user:
            return RedirectResponse(url="/dashboard", status_code=302)
        return RedirectResponse(url="/login", status_code=302)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        user = _get_current_user(request)
        if user:
            return RedirectResponse(url="/dashboard", status_code=302)
        return templates.TemplateResponse(request, "login.html", {"current_user": None})

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        user = _get_current_user(request)
        if user:
            return RedirectResponse(url="/dashboard", status_code=302)
        return templates.TemplateResponse(request, "register.html", {"current_user": None})

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        user = _get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return templates.TemplateResponse(request, "dashboard.html", {"current_user": user})

    @app.get("/report", response_class=HTMLResponse)
    async def report_page(request: Request):
        user = _get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return templates.TemplateResponse(request, "report.html", {"current_user": user})

    @app.get("/chat", response_class=HTMLResponse)
    async def chat_page(request: Request):
        user = _get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return templates.TemplateResponse(request, "chat.html", {"current_user": user})

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
