# i18n — Message Catalogs & Localization Convention

This directory holds the internationalization framework for the scripts in `scripts/`. If you add
or edit a script, follow the convention below so localization stays consistent and future languages
drop in without code changes.

The convention mirrors the fully-realized sibling repo
[`sample-aws-iot-device-management-learning-path-basics`](../../sample-aws-iot-device-management-learning-path-basics)
(all 9 languages shipped). The only intentional difference here: **English-only catalogs ship now**.

## 🗂️ What's in here

```
i18n/
├── loader.py            # load_messages(script_name, language) -> dict (merges common.json + <lang>/<script>.json)
├── language_selector.py # get_language(): AWS_IOT_LANG env var (9 locales) or interactive menu
├── confirm_input.py     # is_yes(text, language)        (certificate_manager lineage)
├── confirmation.py      # is_affirmative(text, language) (cleanup_script lineage)
├── common.json          # shared keys (account_id, region, press_enter, tagging.*, naming.* ...)
└── en/
    ├── <script_name>.json   # one nested catalog per script (script-scoped)
    └── ...
```

`load_messages` resolves paths relative to `loader.py`, so it is CWD-independent. A missing catalog
is **silent** — `get_message` returns the raw key — so English output only exists once
`i18n/en/<script>.json` is authored.

## 📐 Catalog convention

1. **Nested by category, dotted-key access.** Top-level keys are category objects (e.g. `warnings`,
   `prompts`, `status`, `errors`, `debug`, `ui`, `resources`, `learning_moments`); leaves are
   strings (or arrays for multi-line/list output). Code reads leaves with a **dotted key**, e.g.
   `get_message("warnings.debug_warning")`. This matches the basics reference shape.

2. **Positional `{}` placeholders**, formatted via `str.format(*args)`. Do **not** use
   `common.json`'s named-placeholder style in script catalogs.
   ```json
   { "status": { "ca_created": "✅ Created CA certificate: {}" } }
   ```
   ```python
   print(get_message("status.ca_created", cert_id))
   ```

3. **Catalog naming:** one file per script at `i18n/en/<script_name>.json` (script-scoped). Keys
   are `snake_case`, script-scoped, and descriptive of the line's purpose (`ca_created`,
   `connect_start`, `register_accepted`). Avoid collisions with `common.json` keys unless you are
   intentionally overriding one.

4. **Emoji live inside the catalog value** (`"✅ ..."`), so a translator sees the whole rendered
   line — don't split emoji from text across code and catalog.

## 🔌 Path wiring (top of each script)

Scripts add `i18n/` to `sys.path` and import the two framework entry points. Use the existing
idiom:

```python
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

from language_selector import get_language  # noqa: E402
from loader import load_messages            # noqa: E402
```

At entry, resolve the language and load the catalog once before the first print:

```python
messages = load_messages("<script_name>", get_language())
```

## 🧩 The `get_message` wrapper (per-script, NOT centralized)

Each script defines its **own** nested-key-capable `get_message` wrapper. This is intentional — it
is **not** centralized in `loader.py` (which exposes only `load_messages`), matching how the basics
repo does it. Replicate this wrapper (module-level function or class method — the form doesn't
matter, the nested lookup does):

```python
def get_message(key, *args):            # (or a method: def get_message(self, key, *args))
    if "." in key:                      # nested: "warnings.debug_warning"
        msg = messages
        for k in key.split("."):
            if isinstance(msg, dict) and k in msg:
                msg = msg[k]
            else:
                msg = key               # fallback to the key
                break
    else:
        msg = messages.get(key, key)
    if args and isinstance(msg, str):
        return msg.format(*args)
    return msg
```

> Note: `certificate_manager.py` historically shipped an older **flat-only** wrapper
> (`messages.get(key, key)`). New and migrated scripts use the nested-capable version above.

## 🚫 What is NOT localized

Keep these as literals in code — they are not human-readable prose:

- Reserved MQTT topics (e.g. `$aws/certificates/create/json`)
- AWS API parameters and JSON field names
- Resource names
- `--flag` / CLI argument names

Only human-readable console output and `input()` prompts move into catalogs.

## 🌍 Languages

The 9 workshop locales (`en`, `de`, `es`, `fr`, `it`, `ja`, `ko`, `pt`, `zh`) are all recognized by
`language_selector.py`. **Only `i18n/en/*` ships today**; the other 8 locales fall back to the key
(effectively English once the `en` catalog exists) and drop in later under `i18n/<lang>/` with the
same nested structure — no code changes required.
