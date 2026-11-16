"""Where the project's folders are. Every module asks here instead of counting parent directories."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # the repository
DATA = ROOT / "data"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
INSTANCE = ROOT / "instance"                        # accounts database and encryption key (not in git)
