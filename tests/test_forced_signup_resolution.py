import json
import re
import subprocess
from pathlib import Path


def _extract_resolve_forced_signup() -> str:
    source = Path("docs/index.html").read_text(encoding="utf-8")
    match = re.search(
        r"(function\s+resolveForcedSignup[\s\S]*?)\n\s*function\s+normalizeForcedSignup",
        source,
    )
    if not match:
        raise AssertionError("resolveForcedSignup() not found in docs/index.html")
    return match.group(1)


def test_forced_signup_fallback_to_canonical(tmp_path):
    func_src = _extract_resolve_forced_signup()

    payload = {
        "playersByCanon": {
            "bobbydybob": {
                "canon": "bobbydybob",
                "group": "A",
                "role": "Start",
                "has_forced_signup": True,
                "event_signup": {"source": "manual"},
            }
        },
        "row": {"PlayerName": "BobbydyBob", "Group": "A", "Role": "Start"},
    }

    script = (
        """
    const path = require('path');
    const { dsroShared } = require(path.resolve('docs/shared.js'));
    const canonicalNameJS = (global.dsroShared || dsroShared).canonicalNameJS;
    const resolveForcedSignup = (__FUNC_SRC__);

    const playersByCanon = __PLAYERS__;
    const row = __ROW__;

    const result = resolveForcedSignup({
      forcedLookup: new Map(),
      player: {},
      row,
      playersByCanon,
    });

    if (!result || result.commitment !== 'hard') {
      throw new Error('hard commitment not detected via canonical fallback');
    }
    """
        .replace("__FUNC_SRC__", func_src)
        .replace("__PLAYERS__", json.dumps(payload["playersByCanon"]))
        .replace("__ROW__", json.dumps(payload["row"]))
    )

    subprocess.run(["node", "-e", script], check=True)
