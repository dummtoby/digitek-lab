# DigiTek Lab Plugin SDK

Plugins are packaged as `.dgtkplgn` zip archives. A plugin folder can contain:

- `plugin.json`: plugin manifest read by DigiTek Lab.
- `ui/`: frontend files. `ui/index.html` is the default entry.
- `server/`: Python backend. Expose `handle_message(message_str)` from `server/api.py`.
- `public/`: Python helper modules intended for public/plugin API use.
- `private/`: Python helper modules for internal implementation.
- `scripts/`: build, test, and dev scripts.
- `release/`: generated plugin packages.

Build the template with:

```bash
python template/scripts/build.py
```

Import the generated `.dgtkplgn` in DigiTek Lab from `Plugins > Import plugin`.
