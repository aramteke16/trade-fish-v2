"""Extraction prompt. Same template for every provider — never diverge per provider."""

PROMPT_VERSION = "v1"

TEMPLATE = """You are an information extractor for Indian equity filings and news.
Describe the documents below for {ticker}. Score the information itself — never
predict price moves or give a directional call.

Return only a JSON object with exactly these fields:
- catalyst: one of "earnings", "guidance", "order_win", "mgmt_change", "regulatory", "rating", "none"
- sentiment: -1.0 to 1.0, tone of the information itself
- surprise: -1.0 to 1.0, how unexpected vs prior expectations (0 if no expectations exist)
- guidance_delta: -1.0 to 1.0, change in management's forward guidance (0 if none given)
- magnitude: 0.0 to 1.0, business impact size relative to the company
- novelty: 0.0 to 1.0, how new this is vs already-public information
- uncertainty: 0.0 to 1.0, how ambiguous or conditional the information is
- persistence: 0 to 4, how many weeks the effect plausibly matters
- evidence: one short quote or paraphrase supporting the scores

Calibration example — a mid-cap winning an order worth ~8% of annual revenue:
{{"catalyst": "order_win", "sentiment": 0.6, "surprise": 0.5, "guidance_delta": 0.0,
"magnitude": 0.4, "novelty": 0.9, "uncertainty": 0.2, "persistence": 3,
"evidence": "order valued at Rs 850 crore against FY revenue of Rs 10,400 crore"}}

Documents (as of {as_of}):
{text_bundle}"""


def build(text_bundle: str, ticker: str, as_of: str) -> str:
    return TEMPLATE.format(ticker=ticker, as_of=as_of, text_bundle=text_bundle)
