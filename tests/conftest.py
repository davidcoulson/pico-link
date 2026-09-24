import sys
from pathlib import Path

# Make `custom_components.pico_link` importable without installing the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
