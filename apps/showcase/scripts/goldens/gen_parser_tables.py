"""Generate apps/showcase/lib/dsl/parser-tables.ts from the engine's Lark grammar.

The TypeScript parser is a table-driven LALR(1) driver with Lark's contextual lexer. It does not
reimplement the grammar: it executes the tables Lark builds from `GRAMMAR` in
`engine/exemplar/contracts/dsl_ast.py`, so accept/reject decisions, the AST, error positions and the
"expected ..." sets of syntax errors come out exactly as in Python.

Run:  PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/goldens/gen_parser_tables.py
      (add --check to fail instead of writing when the committed file is stale)

State numbers are renumbered breadth-first from the start state so the output does not depend on Python's
hash randomisation.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import deque
from pathlib import Path

import lark
from lark.parsers.lalr_analysis import Shift

from exemplar.contracts.dsl_ast import GRAMMAR
from exemplar.dsl.parser import _parser

OUT = Path(__file__).resolve().parents[2] / "lib" / "dsl" / "parser-tables.ts"

# Python's `\s` (str patterns) matches exactly the characters for which str.isspace() is true. JavaScript's `\s`
# differs (it has U+FEFF, lacks U+001C-U+001F and U+0085), so spell the class out.
_SPACE_CLASS = "".join(f"\\u{c:04x}" for c in range(0x10000) if chr(c).isspace())


def js_regex(src: str) -> str:
    return src.replace("\\s", f"[{_SPACE_CLASS}]")


def lexer_def(lexer) -> dict:
    sc = lexer.scanner
    unless = {}
    for name, cb in lexer.callback.items():
        assert hasattr(cb, "scanner"), f"unexpected user callback on {name}"
        unless[name] = {t.pattern.value: t.name for t in cb.scanner.terminals}
    return {"terms": [t.name for t in sc.terminals], "unless": unless}


def build() -> dict:
    front = _parser().parser
    lalr = front.parser
    table = lalr.parser.parse_table
    conf = front.parser_conf
    lexer = front.lexer

    rules = list(conf.rules)
    rule_index = {r: i for i, r in enumerate(rules)}

    # ---- canonical state numbering (BFS from the start state, symbols in sorted order)
    start_old = table.start_states["start"]
    end_old = table.end_states["start"]
    order: dict[int, int] = {start_old: 0}
    queue = deque([start_old])
    while queue:
        s = queue.popleft()
        for sym in sorted(table.states[s]):
            act, arg = table.states[s][sym]
            if act is Shift and arg not in order:
                order[arg] = len(order)
                queue.append(arg)
    assert len(order) == len(table.states), "unreachable parser states"
    inv = {new: old for old, new in order.items()}

    terminals = {name for name in lexer.root_lexer.terminals_by_name} | {"$END"}
    lexer_ids: dict[int, int] = {}
    lexer_defs: list[dict] = []
    lexer_of_state: list[int] = []
    states_out: list[dict] = []
    for new in range(len(order)):
        old = inv[new]
        row = {}
        for sym, (act, arg) in table.states[old].items():
            row[sym] = [0, order[arg]] if act is Shift else [1, rule_index[arg]]
        states_out.append(dict(sorted(row.items())))
        lx = lexer.lexers[old]
        if id(lx) not in lexer_ids:
            lexer_ids[id(lx)] = len(lexer_defs)
            lexer_defs.append(lexer_def(lx))
        lexer_of_state.append(lexer_ids[id(lx)])
    # dedupe structurally identical lexers (Lark caches by accepted set; ours is by id so they already differ
    # only when the accepted sets differ), keep order stable
    root = len(lexer_defs)
    lexer_defs.append(lexer_def(lexer.root_lexer))

    rules_out = []
    for r in rules:
        assert not r.options.keep_all_tokens
        exp = r.expansion
        keep = [not (s.is_term and getattr(s, "filter_out", False)) for s in exp]
        expand = [(not s.is_term) and s.name.startswith("_") for s in exp]
        empty = r.options.empty_indices
        if empty:
            assert r.origin.name == "atom"  # `present()` placeholder: the AST callback ignores None children
        rules_out.append({"origin": r.origin.name, "len": len(exp), "keep": keep, "expand": expand,
                          "alias": r.alias, "expand1": bool(r.options.expand1)})

    defs = {}
    for name, t in sorted(lexer.root_lexer.terminals_by_name.items()):
        p = t.pattern
        assert not p.flags, f"{name} has regex flags"
        if p.type == "str":
            defs[name] = {"kind": "str", "value": p.value}
        else:
            defs[name] = {"kind": "re", "value": js_regex(p.value)}

    return {
        "grammar_sha256": hashlib.sha256(GRAMMAR.encode("utf-8")).hexdigest(),
        "lark_version": lark.__version__,
        "start": 0,
        "end": order[end_old],
        "terminals": sorted(terminals),
        "ignore": sorted(lexer.root_lexer.ignore_types),
        "rules": rules_out,
        "states": states_out,
        "lexer_of_state": lexer_of_state,
        "lexers": lexer_defs,
        "root": root,
        "defs": defs,
    }


def render(data: dict) -> str:
    head = (
        "// GENERATED by apps/showcase/scripts/goldens/gen_parser_tables.py from GRAMMAR in\n"
        "// engine/exemplar/contracts/dsl_ast.py. Do not edit; rerun the script when the grammar changes.\n"
        "// These are the LALR(1) tables and contextual-lexer tables that Lark builds from that grammar; lalr.ts\n"
        "// executes them, so the TypeScript parser accepts, rejects and reports errors exactly like the engine's.\n"
        'import type { ParserTables } from "./lalr.ts";\n\n'
    )
    lines = ["export const PARSER_TABLES: ParserTables = {"]
    for key in ("grammar_sha256", "lark_version", "start", "end", "terminals", "ignore", "rules", "lexer_of_state",
                "lexers", "root", "defs"):
        lines.append(f"  {key}: {json.dumps(data[key], ensure_ascii=True, sort_keys=True)},")
    lines.append("  states: [")
    for row in data["states"]:
        lines.append(f"    {json.dumps(row, ensure_ascii=True, sort_keys=True)},")
    lines.append("  ],")
    lines.append("};")
    return head + "\n".join(lines) + "\n"


def main() -> int:
    text = render(build())
    if "--check" in sys.argv:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur != text:
            print(f"STALE: {OUT}", file=sys.stderr)
            return 1
        print("parser tables are up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
