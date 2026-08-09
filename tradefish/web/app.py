"""FastAPI app: serves the UI and starts the scheduler in the same process."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from tradefish import config, db, log
from tradefish.web.routes import auth, dashboard, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.setup()
    db.init_db()
    if os.environ.get("DISABLE_SCHEDULER") != "1":
        from tradefish import scheduler
        app.state.scheduler = scheduler.start()
    yield


app = FastAPI(title="trade-fish", lifespan=lifespan)


@app.middleware("http")
async def require_login(request: Request, call_next):
    open_path = request.url.path == "/login" or request.url.path.startswith("/static")
    if not open_path and not request.session.get("authed"):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# added after require_login so sessions are available inside it
app.add_middleware(SessionMiddleware, secret_key=config.get("SECRET_KEY", "dev-secret"))

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
