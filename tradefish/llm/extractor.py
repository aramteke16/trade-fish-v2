"""Provider-agnostic extraction entrypoint (plan §Stream 3a).

extract() resolves the provider at runtime, checks the disk cache, validates
the response, retries with the parse error appended, and falls back to a
neutral extraction marked failed rather than crashing the weekly run.
Adding a provider = one adapter module + one PROVIDERS entry, nothing else.
"""

import hashlib
import json
import logging
import time

from pydantic import ValidationError

from tradefish import config, db
from tradefish.llm import cache, deepseek, prompt
from tradefish.llm.schema import NEUTRAL, Extraction, ExtractionResult

logger = logging.getLogger(__name__)

PROVIDERS = {
    "deepseek": (deepseek.complete, deepseek.DEFAULT_MODEL),
    # "anthropic": added later, same (complete_fn, default_model) shape
}


def extract(text_bundle: str, ticker: str, as_of: str) -> ExtractionResult:
    provider_name = config.get("LLM_PROVIDER", "deepseek")
    complete, default_model = PROVIDERS[provider_name]
    model = config.get("LLM_MODEL") or default_model

    key = hashlib.sha256(f"{prompt.PROMPT_VERSION}|{model}|{text_bundle}".encode()).hexdigest()
    if cached := cache.get(key):
        logger.debug("%s: cache hit", ticker)
        return ExtractionResult(**{**json.loads(cached), "cached": True})

    full_prompt = prompt.build(text_bundle, ticker, as_of)
    retries = int(config.get("LLM_MAX_RETRIES", "3"))
    start = time.monotonic()
    extraction, tokens, failed = None, 0, False

    for attempt in range(1, retries + 1):
        try:
            text, used = complete(full_prompt, model)
            tokens += used
            extraction = Extraction.model_validate_json(text)
            break
        except ValidationError as e:
            logger.warning("%s attempt %d/%d: response failed validation", ticker, attempt, retries)
            full_prompt = prompt.build(text_bundle, ticker, as_of) + (
                f"\n\nYour previous reply failed validation:\n{e}\nReturn only the corrected JSON."
            )
        except Exception as e:
            logger.warning("%s attempt %d/%d: %r", ticker, attempt, retries, e)
            time.sleep(1)
    if extraction is None:
        extraction, failed = NEUTRAL, True
        logger.error("%s: all %d attempts failed, using neutral fallback", ticker, retries)

    result = ExtractionResult(
        extraction=extraction,
        extraction_failed=failed,
        provider=provider_name,
        model=model,
        prompt_version=prompt.PROMPT_VERSION,
        tokens_used=tokens,
        latency_ms=int((time.monotonic() - start) * 1000),
    )
    if not failed:
        cache.put(key, result.model_dump_json(exclude={"cached"}))
    _record(result, ticker, as_of)
    return result


def _record(result: ExtractionResult, ticker: str, as_of: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO extractions (ticker, as_of, provider, model, prompt_version,"
            " tokens_used, latency_ms, failed, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, as_of, result.provider, result.model, result.prompt_version,
             result.tokens_used, result.latency_ms, int(result.extraction_failed),
             result.extraction.model_dump_json()),
        )
