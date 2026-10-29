"""Load the existing pharma engine. The token stays inside that file."""

import importlib.util
import sys

from assistant.config import ROOT

_PATH = ROOT / "research" / "pharma_dasrl.py"
_spec = importlib.util.spec_from_file_location("pharma_dasrl", _PATH)
engine = importlib.util.module_from_spec(_spec)
sys.modules["pharma_dasrl"] = engine
_spec.loader.exec_module(engine)
