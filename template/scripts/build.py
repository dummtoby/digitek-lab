import json
import os
import shutil
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RELEASE = os.path.join(ROOT, "release")
MANIFEST = os.path.join(ROOT, "plugin.json")


def read_manifest():
    with open(MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def should_include(rel):
    first = rel.split(os.sep, 1)[0]
    if first in {"release", "__pycache__", ".git"}:
        return False
    if rel.endswith((".pyc", ".pyo", ".tmp")):
        return False
    return True


def build():
    manifest = read_manifest()
    plugin_id = manifest.get("id") or "plugin"
    version = manifest.get("version") or "1.0.0"
    os.makedirs(RELEASE, exist_ok=True)
    out = os.path.join(RELEASE, f"{plugin_id}-{version}.dgtkplgn")
    if os.path.exists(out):
        os.remove(out)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if should_include(os.path.relpath(os.path.join(root, d), ROOT))]
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, ROOT)
                if should_include(rel):
                    zf.write(path, rel.replace(os.sep, "/"))

    print("Built", out)
    return out


if __name__ == "__main__":
    build()
