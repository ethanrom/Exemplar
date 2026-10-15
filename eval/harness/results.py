"""`$EXEMPLAR_DATA_DIR/eval/results.json`: the `EvalResults` document of `contracts/api.yaml`.

Rows are merged by (concept, method, k, q, seed), so partial runs accumulate and a re-run replaces its own rows only.
The document is validated against the schema embedded in api.yaml before every write.  Fields outside the contract
(`tau`, `n_test_neg`, CI bounds, ...) are allowed by the schema and are what the plots use.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

ROW_KEY = ("concept", "method", "k", "q", "seed")
API_YAML = Path(__file__).resolve().parents[2] / "engine" / "exemplar" / "contracts" / "api.yaml"


def results_path(base: Optional[Path] = None) -> Path:
    from .dataset import eval_dir
    return eval_dir(base) / "results.json"


def row_key(row: dict[str, Any]) -> tuple:
    return tuple(row[f] for f in ROW_KEY)


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """Drop None / NaN / inf values (JSON has no NaN and the schema types are plain numbers) and numpy scalars."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
            v = v.item()
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            continue
        out[k] = v
    return out


def eval_results_schema() -> dict[str, Any]:
    spec = yaml.safe_load(API_YAML.read_text(encoding="utf-8"))
    return spec["components"]["schemas"]["EvalResults"]


def validate(doc: dict[str, Any]) -> None:
    """Raise `jsonschema.ValidationError` unless `doc` matches api.yaml's EvalResults."""
    import jsonschema
    jsonschema.Draft202012Validator(eval_results_schema()).validate(doc)


def load_results(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path) if path else results_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"generated_at": "", "alpha": None, "rows": []}


def merge_rows(rows: Iterable[dict[str, Any]], *, alpha: Optional[float] = None, path: Optional[Path] = None,
               now: Optional[datetime] = None) -> dict[str, Any]:
    """Merge `rows` into results.json (replace on equal key), validate, write atomically, return the document."""
    p = Path(path) if path else results_path()
    doc = load_results(p)
    by_key = {row_key(r): r for r in doc.get("rows", [])}
    for r in rows:
        r = clean_row(r)
        by_key[row_key(r)] = r
    doc["rows"] = [by_key[k] for k in sorted(by_key, key=lambda t: (str(t[0]), str(t[1]), t[2], t[3], t[4]))]
    doc["generated_at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    if alpha is not None:
        doc["alpha"] = alpha
    if doc.get("alpha") is None:
        doc.pop("alpha", None)
    validate(doc)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return doc
