"""Frozen evaluator of the crypto perp research loop. functions/ml goes on sys.path for flybrain.config."""
import sys
from pathlib import Path

_ML = str(Path(__file__).resolve().parents[3])
if _ML not in sys.path:
    sys.path.append(_ML)
