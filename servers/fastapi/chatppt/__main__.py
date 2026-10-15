"""``python -m chatppt --reference`` prints the config reference; without flags, the
effective settings as JSON (secrets included, so don't paste it into a ticket)."""

import sys

from chatppt.settings import load_settings, render_reference

if __name__ == "__main__":
    if "--reference" in sys.argv:
        sys.stdout.write(render_reference())
    else:
        settings = load_settings()
        print(f"config file: {settings.source_path or '(none)'}")
        print(settings.model_dump_json(indent=2))
