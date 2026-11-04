import time, json, os, signal, sys
from datetime import datetime
from agents.discovery_agent import DiscoveryAgent
from config.source_config import load_sources, enabled_tokens

RUNS_PATH = os.path.join("storage", "discovery_runs.json")
INTERVAL = int(os.getenv("DISCOVERY_INTERVAL_HOURS", "6")) * 3600

running = True
def stop(sig, frame):
    global running
    running = False
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def load_runs():
    if os.path.exists(RUNS_PATH):
        try:
            return json.load(open(RUNS_PATH))
        except Exception:
            return []
    return []

def save_runs(runs):
    os.makedirs(os.path.dirname(RUNS_PATH), exist_ok=True)
    with open(RUNS_PATH, "w") as f:
        json.dump(runs, f, indent=2)

def run_once():
    start = datetime.now().isoformat()
    cfg = load_sources()
    gh = enabled_tokens(cfg, "greenhouse_boards")
    lv = enabled_tokens(cfg, "lever_boards")
    agent = DiscoveryAgent()
    discovered = []
    stats = {}
    try:
        discovered, stats = agent.discover(greenhouse_boards=gh, lever_boards=lv)
        errors = stats.get("errors", [])
        status = "partial" if errors and stats.get("retrieved") else ("error" if errors else "success")
        error = "; ".join(
            str(item.get("error") or item.get("warning") or "Source error")
            for item in errors
        ) or None
    except Exception as e:
        status = "error"
        error = str(e)
        stats = {}
    run = {
        "run_id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "start": start,
        "finish": datetime.now().isoformat(),
        "sources": gh + lv + ["remotive"],
        "retrieved": stats.get("retrieved", 0),
        "new_saved": stats.get("new_saved", 0),
        "duplicates": stats.get("duplicates_skipped", 0),
        "previously_known": stats.get("previously_known", 0),
        "possible_repost_groups": stats.get("possible_repost_groups", 0),
        "status": status,
        "error": error,
    }
    runs = load_runs()
    runs.insert(0, run)
    runs = runs[:50]
    save_runs(runs)
    return run

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        print(json.dumps(run_once(), indent=2))
        sys.exit(0)
    print("Starting discovery worker")
    while running:
        run_once()
        # sleep in chunks
        for _ in range(INTERVAL // 10):
            if not running:
                break
            time.sleep(10)
    print("Worker stopped")
