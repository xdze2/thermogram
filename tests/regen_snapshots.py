"""Regenerate the golden RCModelOut JSON snapshots.

Run intentionally — and review the resulting git diff — only when a behaviour change
is deliberate (e.g. the Stage 2 alpha_eff fix). Stage 2's whole point is that these
do NOT change for a behaviour-preserving refactor.

    uv run python tests/regen_snapshots.py
"""

import json
from pathlib import Path

from thermal.api_models import Room
from thermal.priors import build_priors

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = Path(__file__).parent / "snapshots"


def main() -> None:
    SNAPSHOTS.mkdir(exist_ok=True)
    for fx in sorted(FIXTURES.glob("*.json")):
        room = Room(**json.loads(fx.read_text()))
        out = build_priors(room)
        text = json.dumps(out.model_dump(), indent=2, sort_keys=True) + "\n"
        (SNAPSHOTS / fx.name).write_text(text)
        print("wrote", fx.name)


if __name__ == "__main__":
    main()
