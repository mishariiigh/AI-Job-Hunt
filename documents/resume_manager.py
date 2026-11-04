import os, json, uuid, datetime

INDEX = os.path.join("storage", "resumes", "index.json")
PARSED_DIR = os.path.join("storage", "resumes", "parsed")


def _ensure_dirs():
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    os.makedirs(PARSED_DIR, exist_ok=True)


def _load():
    if os.path.exists(INDEX):
        try:
            with open(INDEX) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save(items):
    _ensure_dirs()
    with open(INDEX, "w") as f:
        json.dump(items, f, indent=2)


def add_resume(filename, path, text, name=None, parsed_json=None, import_sha256=None):
    _ensure_dirs()
    items = _load()
    rid = str(uuid.uuid4())
    resume_entry = {
        "id": rid,
        "name": name or filename,
        "filename": filename,
        "path": path,
        "text": text,
        "uploaded_at": datetime.datetime.now().isoformat(),
        "default": len(items) == 0,
    }
    if import_sha256:
        resume_entry["import_sha256"] = import_sha256
    if parsed_json is not None:
        resume_entry["parsed_json"] = parsed_json
        # Save parsed JSON to file
        parsed_path = os.path.join(PARSED_DIR, f"{rid}.json")
        try:
            if isinstance(parsed_json, str):
                parsed_data = json.loads(parsed_json)
            else:
                parsed_data = parsed_json
            with open(parsed_path, "w") as f:
                json.dump(parsed_data, f, indent=2)
            resume_entry["parsed_path"] = parsed_path
        except Exception:
            pass
    items.append(resume_entry)
    _save(items)
    return rid


def list_resumes():
    items = _load()
    upload_dir = os.path.join("storage", "resumes")
    os.makedirs(upload_dir, exist_ok=True)
    known = {r.get("filename") for r in items}
    changed = False
    for name in os.listdir(upload_dir):
        if name == "index.json":
            continue
        if name in known:
            continue
        path = os.path.join(upload_dir, name)
        if not os.path.isfile(path):
            continue
        text = ""
        try:
            from documents.resume_parser import extract_text
            text = extract_text(path) or ""
        except Exception:
            text = ""
        items.append({
            "id": str(uuid.uuid4()),
            "name": name,
            "filename": name,
            "path": path,
            "text": text,
            "uploaded_at": datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            "default": len(items) == 0,
        })
        changed = True
    if changed:
        _save(items)
    return items



def set_default(rid):
    items = _load()
    for r in items:
        r["default"] = (r["id"] == rid)
    _save(items)


def get_default():
    for r in _load():
        if r.get("default"):
            return r
    items = _load()
    return items[0] if items else None


def rename_resume(rid, new_name):
    new_name = (new_name or '').strip()
    if not new_name:
        return False
    items = _load()
    for r in items:
        if r['id'] == rid:
            r['name'] = new_name
            _save(items)
            return True
    return False


def update_resume(rid, **updates):
    items = _load()
    for r in items:
        if r['id'] == rid:
            r.update(updates)
            _save(items)
            return True
    return False


def get_resume(rid):
    for r in _load():
        if r['id'] == rid:
            return r
    return None


def save_parsed_json(rid, parsed_data):
    _ensure_dirs()
    items = _load()
    for r in items:
        if r['id'] == rid:
            if isinstance(parsed_data, str):
                parsed_data = json.loads(parsed_data)
            r['parsed_json'] = json.dumps(parsed_data) if not isinstance(r.get('parsed_json'), dict) else json.dumps(parsed_data)
            # Also store as dict form
            parsed_path = os.path.join(PARSED_DIR, f"{rid}.json")
            with open(parsed_path, "w") as f:
                json.dump(parsed_data, f, indent=2)
            r['parsed_path'] = parsed_path
            _save(items)
            return True
    return False


def get_parsed_json(rid):
    r = get_resume(rid)
    if not r:
        return None
    if r.get('parsed_json'):
        try:
            if isinstance(r['parsed_json'], str):
                return json.loads(r['parsed_json'])
            return r['parsed_json']
        except Exception:
            pass
    # Try from file
    parsed_path = os.path.join(PARSED_DIR, f"{rid}.json")
    if os.path.exists(parsed_path):
        try:
            with open(parsed_path) as f:
                return json.load(f)
        except Exception:
            pass
    return None
