import json
from pathlib import Path

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "providers"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())
