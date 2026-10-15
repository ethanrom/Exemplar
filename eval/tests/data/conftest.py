"""Make `import eval.data...` work when pytest is started from anywhere (the repo root holds the `eval` package)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
