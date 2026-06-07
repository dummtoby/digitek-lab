import json
import os
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RELEASE = os.path.join(ROOT, "release")


def build():
    with open(os.path.join(ROOT, "plugin.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    out = os.path.join(RELEASE, f"{manifest['id']}-{manifest['version']}.dgtkplgn")
    os.makedirs(RELEASE, exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in {"release", "__pycache__", ".git"}]
            for name in files:
                if name.endswith((".pyc", ".pyo", ".tmp")):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, ROOT)
                if rel.split(os.sep, 1)[0] == "release":
                    continue
                zf.write(path, rel.replace(os.sep, "/"))
    print("Built", out)
    return out


if __name__ == "__main__":
    build()
