"""Record/replay for `Transport`, so CI grades v1.5 and v2 without a key or a live call.

Keyed by a hash of the request payload (model, messages, tools, ...), not call order, so replay
works regardless of which tickets a run happens to process first.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from triage.llm.client import LlmError, Transport

CassetteMode = Literal["record", "replay", "replay_or_record"]


def _key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


class CassetteTransport:
    """record: always calls `inner`, overwrites the cassette.
    replay: never calls `inner`; raises LlmError if nothing was recorded for this request.
    replay_or_record: replays a cassette if one exists, else calls `inner` and saves it.
    """

    def __init__(self, inner: Transport, cassette_dir: Path, mode: CassetteMode) -> None:
        self._inner = inner
        self._dir = cassette_dir
        self._mode = mode
        cassette_dir.mkdir(parents=True, exist_ok=True)

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        path = self._dir / f"{_key(payload)}.json"
        if self._mode != "record" and path.is_file():
            recorded = json.loads(path.read_text(encoding="utf-8"))
            return dict(recorded["response"])
        if self._mode == "replay":
            raise LlmError(
                f"no cassette recorded for this request ({path.name}); "
                f"run with --llm-mode replay_or_record to record it"
            )
        response = self._inner.send(payload, timeout_seconds)
        path.write_text(
            json.dumps({"request": payload, "response": response}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return response
