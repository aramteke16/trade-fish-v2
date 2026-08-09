from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from tradefish import config, db
from tradefish.web.templating import templates

router = APIRouter()

SECRETS = ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "BROKER_API_KEY", "ADMIN_PASSWORD"]
LLM_PARAMS = ["LLM_PROVIDER", "LLM_MODEL", "LLM_TEMPERATURE", "LLM_MAX_RETRIES"]
STRATEGY_PARAMS = ["top_k", "train_window_weeks", "refit_weeks", "paper_capital"]  # barriers locked (plan §9)


@router.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {
        "secrets": {k: _mask(config.get(k)) for k in SECRETS},
        "llm_params": {k: config.get(k) or "" for k in LLM_PARAMS},
        "strategy_params": {k: config.strategy(k) for k in STRATEGY_PARAMS},
        "barriers": {"upper": config.strategy("upper_barrier"),
                     "lower": config.strategy("lower_barrier")},
        "saved": request.query_params.get("saved"),
    })


@router.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    for key in SECRETS:
        if value := form.get(key, "").strip():  # blank = leave unchanged
            db.set_setting(key, value, is_secret=True)
    for key in LLM_PARAMS:
        value = form.get(key, "").strip()
        if value != (config.get(key) or ""):
            db.set_setting(key, value)
    for key in STRATEGY_PARAMS:
        value = form.get(key, "").strip()
        if value and value != str(config.strategy(key)):
            db.set_setting(f"strategy.{key}", value)
    return RedirectResponse("/settings?saved=1", status_code=303)


def _mask(value: str | None) -> str:
    return f"••••{value[-4:]}" if value and len(value) > 4 else ("set" if value else "not set")
