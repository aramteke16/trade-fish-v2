import logging
import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from tradefish import config
from tradefish.web.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    client = request.client.host if request.client else "?"
    expected = config.get("ADMIN_PASSWORD") or ""
    if expected and secrets.compare_digest(password, expected):
        request.session["authed"] = True
        logger.info("login ok from %s", client)
        return RedirectResponse("/", status_code=303)
    logger.warning("failed login from %s", client)
    return templates.TemplateResponse(request, "login.html", {"error": "wrong password"})


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
