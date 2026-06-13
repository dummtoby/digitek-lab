import importlib
import importlib.util
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.request
import zipfile

from . import macros

PLUGIN_EXT = ".dgtkplgn"
PLUGIN_MANIFEST = "plugin.json"
PLUGINS_DIR = os.path.join(macros.DATA_DIR, "plugins")
PLUGIN_PACKAGES_DIR = os.path.join(macros.DATA_DIR, "plugin-packages")
PINNED_PLUGINS_FILE = os.path.join(macros.DATA_DIR, "pinned_plugins.json")
MARKETPLACE_MANIFEST_URL = "https://raw.githubusercontent.com/dummtoby/digitek-lab/plugins/manifest.json"
MARKETPLACE_RAW_BASE_URL = "https://raw.githubusercontent.com/dummtoby/digitek-lab/plugins"

_MODULE_CACHE = {}


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _slugify(value, fallback="plugin"):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def ensure_dirs():
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    os.makedirs(PLUGIN_PACKAGES_DIR, exist_ok=True)
    _add_plugin_packages_path()


def plugins_dir():
    ensure_dirs()
    return PLUGINS_DIR


def get_pinned_plugins():
    try:
        data = _read_json(PINNED_PLUGINS_FILE)
        if isinstance(data, list):
            return _normalize_plugin_id_list(data)
    except Exception:
        pass
    return []


def set_pinned_plugins(plugin_ids):
    ensure_dirs()
    ids = _normalize_plugin_id_list(plugin_ids if isinstance(plugin_ids, list) else [])
    _write_json(PINNED_PLUGINS_FILE, ids)
    return ids


def _normalize_plugin_id_list(plugin_ids):
    seen = set()
    out = []
    for plugin_id in plugin_ids or []:
        pid = _slugify(plugin_id, "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def _add_plugin_packages_path():
    if PLUGIN_PACKAGES_DIR not in sys.path:
        sys.path.insert(0, PLUGIN_PACKAGES_DIR)


def _safe_join(base, *parts):
    base_abs = os.path.abspath(base)
    path = os.path.abspath(os.path.join(base_abs, *parts))
    if path != base_abs and not path.startswith(base_abs + os.sep):
        raise ValueError("Plugin archive contains an unsafe path.")
    return path


def _path_within(path, root):
    try:
        path_abs = os.path.abspath(path or "")
        root_abs = os.path.abspath(root or "")
        return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)
    except Exception:
        return False


def _plugin_module_name(plugin_id):
    return "dgt_plugin_" + re.sub(r"[^a-zA-Z0-9_]", "_", _slugify(plugin_id))


def _remove_pycache(root):
    if not root or not os.path.isdir(root):
        return
    for dirpath, dirnames, _files in os.walk(root):
        for dirname in list(dirnames):
            if dirname == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, dirname), ignore_errors=True)


def _clear_plugin_runtime(plugin):
    plugin_id = plugin.get("id") if isinstance(plugin, dict) else _slugify(plugin)
    root = plugin.get("path", "") if isinstance(plugin, dict) else ""
    if plugin_id:
        _MODULE_CACHE.pop(plugin_id, None)
    prefix = _plugin_module_name(plugin_id) if plugin_id else ""
    root_abs = os.path.abspath(root) if root else ""
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", "") or ""
        if (prefix and name == prefix) or (root_abs and module_file and _path_within(module_file, root_abs)):
            sys.modules.pop(name, None)
    _remove_pycache(root_abs)
    importlib.invalidate_caches()


def _plugin_fingerprint(plugin):
    root = plugin.get("path", "")
    latest = 0.0
    for rel in (PLUGIN_MANIFEST, "properties.config"):
        path = os.path.join(root, rel)
        if os.path.exists(path):
            latest = max(latest, os.path.getmtime(path))
    for sub in ("server", "public", "private"):
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in filenames:
                if filename.endswith(".py"):
                    latest = max(latest, os.path.getmtime(os.path.join(dirpath, filename)))
    return latest


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _manifest_path(root):
    direct = os.path.join(root, PLUGIN_MANIFEST)
    if os.path.exists(direct):
        return direct
    config = os.path.join(root, "properties.config")
    if os.path.exists(config):
        return config
    return direct


def _parse_properties(path):
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def _load_manifest(root):
    path = _manifest_path(root)
    if not os.path.exists(path):
        raise ValueError("Plugin is missing plugin.json or properties.config.")
    if path.endswith(".json"):
        data = _read_json(path)
    else:
        props = _parse_properties(path)
        data = {
            "id": props.get("PLUGIN_ID") or props.get("ID"),
            "name": props.get("TITLE") or props.get("NAME"),
            "version": props.get("VERSION", "1.0.0"),
            "author": props.get("AUTHOR", ""),
            "description": props.get("DESCRIPTION", ""),
            "entry": props.get("MAIN_PAGE", "ui/index.html"),
        }
    data = dict(data or {})
    data["id"] = _slugify(data.get("id") or data.get("name"))
    data.setdefault("name", data["id"])
    data.setdefault("version", "1.0.0")
    data.setdefault("author", "")
    data.setdefault("description", "")
    data.setdefault("entry", "ui/index.html")
    return data


def _summary(root):
    data = _load_manifest(root)
    data["path"] = root
    data["installedAt"] = data.get("installedAt", "")
    data["hasUi"] = os.path.exists(os.path.join(root, data.get("entry", "ui/index.html")))
    data["hasServer"] = os.path.exists(os.path.join(root, "server", "api.py"))
    data["iconDataUri"] = _icon_data_uri(root, data)
    data["iconPath"] = _native_icon_path(root, data)
    return data


def _version_key(value):
    parts = []
    for part in re.split(r"[^0-9A-Za-z]+", str(value or "0")):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    while len(parts) > 1 and parts[-1] == (0, 0):
        parts.pop()
    return parts or [(0, 0)]


def _is_newer_version(latest, current):
    return _version_key(latest) > _version_key(current)


def _icon_data_uri(root, manifest):
    icon = str(manifest.get("icon") or "").strip()
    if not icon:
        return ""
    try:
        path = _safe_join(root, *icon.replace("\\", "/").split("/"))
        if not os.path.isfile(path):
            return ""
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return ""


def _native_icon_path(root, manifest):
    icon = str(manifest.get("icon") or "").strip()
    if not icon:
        return ""
    try:
        path = _safe_join(root, *icon.replace("\\", "/").split("/"))
        if not os.path.isfile(path):
            return ""
        if path.lower().endswith(".ico"):
            return path
        cache_dir = os.path.join(root, ".digitek")
        ico_path = os.path.join(cache_dir, "icon.ico")
        if os.path.exists(ico_path) and os.path.getmtime(ico_path) >= os.path.getmtime(path):
            return ico_path
        try:
            from PIL import Image
            os.makedirs(cache_dir, exist_ok=True)
            img = Image.open(path).convert("RGBA")
            img.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128)])
            return ico_path
        except Exception:
            return ""
    except Exception:
        return ""


def list_plugins():
    ensure_dirs()
    out = []
    for name in sorted(os.listdir(PLUGINS_DIR)):
        root = os.path.join(PLUGINS_DIR, name)
        if not os.path.isdir(root):
            continue
        try:
            out.append(_summary(root))
        except Exception:
            continue
    return out


def get_plugin(plugin_id):
    ensure_dirs()
    root = _safe_join(PLUGINS_DIR, _slugify(plugin_id))
    if not os.path.isdir(root):
        raise ValueError("Plugin is not installed: " + str(plugin_id))
    return _summary(root)


def import_plugin(path):
    ensure_dirs()
    if not path:
        return {"cancelled": True}
    if not os.path.isfile(path):
        raise ValueError("Plugin file not found.")
    if not path.lower().endswith(PLUGIN_EXT):
        raise ValueError("Expected a .dgtkplgn file.")

    temp = os.path.join(PLUGINS_DIR, "_import_" + str(int(time.time() * 1000)))
    os.makedirs(temp, exist_ok=True)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest = _safe_join(temp, info.filename)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        root = _normalize_extracted_root(temp)
        manifest = _load_manifest(root)
        manifest["installedAt"] = _now_iso()
        dest = _safe_join(PLUGINS_DIR, manifest["id"])
        if os.path.exists(dest):
            _clear_plugin_runtime({"id": manifest["id"], "path": dest})
            shutil.rmtree(dest)
        if root == temp:
            os.replace(temp, dest)
            temp = None
        else:
            shutil.move(root, dest)
        _write_json(os.path.join(dest, PLUGIN_MANIFEST), manifest)
        _clear_plugin_runtime({"id": manifest["id"], "path": dest})
        installed = _summary(dest)
        ensure_plugin_requirements(installed)
        return _summary(dest)
    finally:
        if temp and os.path.exists(temp):
            shutil.rmtree(temp, ignore_errors=True)


def marketplace_manifest():
    with urllib.request.urlopen(MARKETPLACE_MANIFEST_URL, timeout=12) as res:
        data = json.loads(res.read().decode("utf-8"))
    installed = {p["id"]: p for p in list_plugins()}
    out = []
    for plugin_id, item in sorted((data or {}).items()):
        meta = dict(item or {})
        meta["id"] = _slugify(plugin_id)
        meta.setdefault("name", plugin_id)
        meta.setdefault("version", "1.0.0")
        package = meta.get("package") or _infer_package_path(meta["id"], meta.get("version"))
        meta["package"] = package
        local = installed.get(meta["id"])
        meta["installed"] = bool(local)
        meta["installedVersion"] = local.get("version", "") if local else ""
        meta["latestVersion"] = meta.get("version", "1.0.0")
        meta["updateAvailable"] = bool(local and _is_newer_version(meta["latestVersion"], local.get("version", "")))
        out.append(meta)
    return out


def plugin_update_status(plugin_id=None):
    installed = {p["id"]: p for p in list_plugins()}
    market = {p["id"]: p for p in marketplace_manifest()}
    ids = [_slugify(plugin_id)] if plugin_id else sorted(installed)
    out = {}
    for pid in ids:
        local = installed.get(pid)
        remote = market.get(pid)
        if not local:
            out[pid] = {"installed": False, "updateAvailable": False}
            continue
        if not remote:
            out[pid] = {
                "installed": True,
                "updateAvailable": False,
                "installedVersion": local.get("version", ""),
                "latestVersion": "",
            }
            continue
        out[pid] = {
            "installed": True,
            "updateAvailable": bool(remote.get("updateAvailable")),
            "installedVersion": local.get("version", ""),
            "latestVersion": remote.get("latestVersion") or remote.get("version", ""),
            "name": remote.get("name") or local.get("name") or pid,
            "package": remote.get("package", ""),
        }
    return out.get(_slugify(plugin_id), {}) if plugin_id else out


def _infer_package_path(plugin_id, version):
    normalized_version = str(version or "1.0.0")
    if normalized_version.count(".") == 1:
        normalized_version += ".0"
    return f"/{plugin_id}/release/{plugin_id}-{normalized_version}.dgtkplgn"


def install_marketplace_plugin(plugin_id):
    plugin_id = _slugify(plugin_id)
    matches = [p for p in marketplace_manifest() if p["id"] == plugin_id]
    if not matches:
        raise ValueError("Marketplace plugin not found: " + plugin_id)
    meta = matches[0]
    package = str(meta.get("package") or "")
    if package.startswith("http://") or package.startswith("https://"):
        url = package
    else:
        url = MARKETPLACE_RAW_BASE_URL + "/" + package.lstrip("/")

    fd, path = tempfile.mkstemp(suffix=PLUGIN_EXT)
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, path)
        return import_plugin(path)
    finally:
        if os.path.exists(path):
            os.remove(path)


def _normalize_extracted_root(temp):
    entries = [e for e in os.listdir(temp) if not e.startswith("__MACOSX")]
    if len(entries) == 1:
        only = os.path.join(temp, entries[0])
        if os.path.isdir(only) and (os.path.exists(os.path.join(only, PLUGIN_MANIFEST)) or os.path.exists(os.path.join(only, "properties.config"))):
            return only
    return temp


def _plugin_requirements(plugin):
    reqs = plugin.get("pythonRequirements") or plugin.get("requirements") or []
    out = []
    for req in reqs:
        if isinstance(req, str):
            out.append({"package": req, "import": _package_import_name(req), "optional": False})
        elif isinstance(req, dict):
            package = str(req.get("package") or req.get("name") or "").strip()
            if not package:
                continue
            out.append({
                "package": package,
                "import": str(req.get("import") or req.get("module") or _package_import_name(package)).strip(),
                "optional": bool(req.get("optional")),
            })
    return out


def _package_import_name(package):
    return re.split(r"[<>=!~\[]+", str(package), 1)[0].strip().replace("-", "_")


def ensure_plugin_requirements(plugin):
    ensure_dirs()
    _add_plugin_packages_path()
    missing = []
    optional_missing = []
    for req in _plugin_requirements(plugin):
        try:
            importlib.invalidate_caches()
            if importlib.util.find_spec(req["import"]) is None:
                raise ImportError(req["import"])
        except Exception:
            (optional_missing if req.get("optional") else missing).append(req)
    if not missing and not optional_missing:
        return {"ok": True, "installed": []}

    installed = []
    if missing:
        packages = [r["package"] for r in missing]
        errors = _install_python_packages(packages)
        importlib.invalidate_caches()
        still_missing = [r["package"] for r in missing if importlib.util.find_spec(r["import"]) is None]
        if still_missing:
            required = ", ".join(still_missing)
            raise RuntimeError("Plugin requires Python packages that could not be installed: " + required + ". " + " | ".join(errors))
        installed.extend(packages)

    for req in optional_missing:
        try:
            _install_python_packages([req["package"]])
            installed.append(req["package"])
        except Exception:
            pass
    return {"ok": True, "installed": installed}


def _install_python_packages(packages):
    errors = []
    for cmd in _python_install_commands(packages):
        try:
            _run_pip_install(cmd)
            return errors
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError(" | ".join(errors))
    raise RuntimeError("No Python executable was available for package installation.")


def _python_install_commands(packages):
    base = ["-m", "pip", "--disable-pip-version-check", "install", "--upgrade", "--no-input", "--target", PLUGIN_PACKAGES_DIR]
    yielded = set()
    candidates = [[sys.executable]] if sys.executable else []
    try:
        from . import input_driver
        candidates.append(input_driver._computer_python()["cmd"])
    except Exception:
        pass
    for cmd in candidates:
        key = tuple(cmd)
        if not cmd or key in yielded:
            continue
        yielded.add(key)
        yield cmd + base + packages


def _run_pip_install(args):
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=600,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "").strip() or ("Command failed: " + " ".join(args)))


def remove_plugin(plugin_id):
    plugin = get_plugin(plugin_id)
    _clear_plugin_runtime(plugin)
    shutil.rmtree(plugin["path"])
    return True


def open_plugins_folder():
    ensure_dirs()
    if os.name == "nt":
        os.startfile(PLUGINS_DIR)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", PLUGINS_DIR])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", PLUGINS_DIR])
    return {"path": PLUGINS_DIR}


def load_ui(plugin_id):
    plugin = get_plugin(plugin_id)
    entry = plugin.get("entry", "ui/index.html")
    path = _safe_join(plugin["path"], *entry.replace("\\", "/").split("/"))
    if not os.path.exists(path):
        raise ValueError("Plugin UI entry not found: " + entry)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return {"plugin": plugin, "html": html, "cacheBust": _plugin_fingerprint(plugin)}


def _load_module(plugin):
    ensure_plugin_requirements(plugin)
    plugin_id = plugin["id"]
    fingerprint = _plugin_fingerprint(plugin)
    cached = _MODULE_CACHE.get(plugin_id)
    if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint:
        return cached.get("module")
    if cached:
        _clear_plugin_runtime(plugin)
    api_path = os.path.join(plugin["path"], "server", "api.py")
    if not os.path.exists(api_path):
        raise ValueError("Plugin has no server/api.py")
    module_name = _plugin_module_name(plugin_id)
    spec = importlib.util.spec_from_file_location(module_name, api_path)
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    for sub in ("server", "public", "private", ""):
        p = os.path.join(plugin["path"], sub) if sub else plugin["path"]
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    _MODULE_CACHE[plugin_id] = {"module": module, "fingerprint": fingerprint}
    return module


def call_plugin(plugin_id, payload):
    plugin = get_plugin(plugin_id)
    module = _load_module(plugin)
    if not hasattr(module, "handle_message"):
        raise ValueError("Plugin server/api.py does not expose handle_message(payload).")
    payload = dict(payload or {})
    payload.setdefault("pluginId", plugin["id"])
    return module.handle_message(json.dumps(payload))
