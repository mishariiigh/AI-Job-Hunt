import json
import os


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "sources.json")


def _normalize_board(item):
    if isinstance(item, str):
        return {"token": item, "enabled": True, "status": "unknown", "last_retrieved": 0, "last_checked": ""}
    if isinstance(item, dict):
        return {
            "token": item.get("token") or item.get("board") or "",
            "enabled": bool(item.get("enabled", True)),
            "status": item.get("status", "unknown"),
            "last_retrieved": item.get("last_retrieved", 0),
            "last_checked": item.get("last_checked", ""),
        }
    return None


def _normalize_config(config):
    gh = [_normalize_board(x) for x in (config.get("greenhouse_boards") or [])]
    lv = [_normalize_board(x) for x in (config.get("lever_boards") or [])]
    gh = [x for x in gh if x and x["token"]]
    lv = [x for x in lv if x and x["token"]]
    return {"greenhouse_boards": gh, "lever_boards": lv}


def load_sources():
    if not os.path.exists(CONFIG_PATH):
        save_sources({"greenhouse_boards": [], "lever_boards": []})
    with open(CONFIG_PATH, 'r') as f:
        raw = json.load(f)
    return _normalize_config(raw)


def save_sources(config):
    norm = _normalize_config(config)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(norm, f, indent=2)
    return norm


def enabled_tokens(config, key):
    return [b["token"] for b in (config.get(key) or []) if b.get("enabled")]
