// DSL text -> AST (`parse`). Port of engine/exemplar/dsl/parser.py.
//
// The grammar is the engine's Lark grammar, executed from generated tables (parser-tables.ts, driver in
// lalr.ts), so the accepted language, the AST, error positions and error messages match the engine's
// parser. The tree-to-AST step below is the port of the `_ToAST` transformer.

import type { And, Bound, Ctx, Hole, Node, Or, Phi, Rule, VarDecl } from "./ast.ts";
import { DSLSyntaxError } from "./errors.ts";
import { isToken, LalrParser, Token, UnexpectedCharacters, UnexpectedToken } from "./lalr.ts";
import type { Tree, TreeChild } from "./lalr.ts";
import { SUB_TYPE_SET, SUB_TYPES } from "./ontology.ts";
import type { SubType, VarType } from "./ontology.ts";
import { PARSER_TABLES } from "./parser-tables.ts";
import { codePointLength, pyReprStr, pySplitlines, spaces } from "./pycompat.ts";

// --------------------------------------------------------------------------- readable token names
const KEYWORDS = new Set([
  "EXISTS", "WHEN", "AND", "OR", "NOT", "THEN", "EVENTUALLY", "ALWAYS", "HOLDS_FOR", "HOUR", "IN", "SUBTYPE",
  "__ANON_1",
]);
const TOKEN_NAMES: Readonly<Record<string, string>> = {
  LPAR: "'('", RPAR: "')'", LSQB: "'['", RSQB: "']'", COMMA: "','", COLON: "':'", EQUAL: "'='",
  __ANON_0: "'>='", __ANON_1: "'device'", NAME: "a lower-case name", ARG: "a variable, zone or label",
  PRED: "a predicate name", NUMBER: "a number", HOLE: "a hole like ?b", DEVICE: "a device id",
  VARTYPE: "a type (Entity, Person, Vehicle, Package, Animal, Object or Carryable)", $END: "end of input",
};
const FORMULA_START = ["NOT", "EVENTUALLY", "ALWAYS", "HOLDS_FOR", "PRED", "LPAR"];

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function describeExpected(namesIn: Iterable<string>): string {
  let names = new Set(namesIn);
  let items: string[] = [];
  if (FORMULA_START.every((n) => names.has(n))) {
    names = new Set([...names].filter((n) => !FORMULA_START.includes(n)));
    items.push("a formula (an atom like present(p), or not / eventually[a, b] / always[a, b] / holds_for >= d, or '(')");
  }
  for (const n of [...names].sort(cmp)) {
    const known = Object.prototype.hasOwnProperty.call(TOKEN_NAMES, n) ? TOKEN_NAMES[n] : "";
    items.push(known || (KEYWORDS.has(n) ? `'${n.toLowerCase()}'` : n.toLowerCase()));
  }
  items = [...new Set(items)].sort((x, y) => {
    const fx = x.startsWith("a formula") ? 0 : 1;
    const fy = y.startsWith("a formula") ? 0 : 1;
    return fx - fy || cmp(x, y);
  });
  if (items.length > 8) items = [...items.slice(0, 8), "..."];
  if (items.length <= 2) return items.join(" or ");
  return items.slice(0, -1).join(", ") + " or " + items[items.length - 1];
}

/** Line and column (both 1-based, columns counted in Unicode code points) of a UTF-16 offset. */
function lineCol(text: string, pos: number): [number, number] {
  let line = 1;
  let lineStart = 0;
  for (let i = 0; i < pos; i++) {
    if (text.charCodeAt(i) === 10) {
      line += 1;
      lineStart = i + 1;
    }
  }
  return [line, codePointLength(text.slice(lineStart, pos)) + 1];
}

function context(text: string, line: number, column: number): string {
  const lines = pySplitlines(text);
  if (lines.length === 0) lines.push("");
  const src = lines[Math.min(Math.max(line, 1), lines.length) - 1];
  return `${src}\n${spaces(Math.max(column, 1) - 1)}^`;
}

function syntaxError(exc: UnexpectedToken | UnexpectedCharacters, text: string): DSLSyntaxError {
  let line: number;
  let col: number;
  let msg: string;
  if (exc instanceof UnexpectedToken) {
    const names = exc.accepts.size > 0 ? exc.accepts : exc.expected;
    if (exc.token.type === "$END") {
      const lines = pySplitlines(text);
      if (lines.length === 0) lines.push("");
      line = lines.length;
      col = codePointLength(lines[lines.length - 1]) + 1;
      msg = `unexpected end of input; expected ${describeExpected(names)}`;
    } else {
      [line, col] = lineCol(text, exc.token.pos);
      msg = `unexpected '${exc.token.value}'; expected ${describeExpected(names)}`;
    }
  } else {
    [line, col] = lineCol(text, exc.pos);
    msg = `unexpected character ${pyReprStr(exc.char)}`;
    if (exc.allowed.size > 0) msg += `; expected ${describeExpected(exc.allowed)}`;
  }
  if (line < 1) {
    line = 1;
    col = 1;
  }
  return new DSLSyntaxError(msg, line, col, context(text, line, col));
}

// --------------------------------------------------------------------------- tree -> AST
type Item = Tree | Token | null | Phi | Ctx | VarDecl | Rule | readonly [Bound, Bound];

function bound(tok: Token): Bound {
  if (tok.type === "HOLE") return { op: "hole", name: tok.value.slice(1) } satisfies Hole;
  return Number(tok.value);
}

function hourBound(text: string, tok: Token): number | Hole {
  if (tok.type === "HOLE") return { op: "hole", name: tok.value.slice(1) };
  const x = Number(tok.value);
  if (!Number.isFinite(x)) throw new Error("OverflowError: cannot convert float infinity to integer");
  if (!Number.isInteger(x)) {
    const [line, col] = lineCol(text, tok.pos);
    throw new DSLSyntaxError(`hour bounds must be whole numbers 0-23, got ${tok.value}`, line, col);
  }
  return x;
}

function flatten(op: "and" | "or", items: readonly Phi[]): And | Or {
  const flat: Phi[] = [];
  for (const c of items) {
    if (c.op === op) flat.push(...(c as And | Or).args);
    else flat.push(c);
  }
  return { op, args: flat };
}

function isVarDeclItem(x: Item): x is VarDecl {
  return typeof x === "object" && x !== null && !isToken(x as TreeChild) && !("op" in x) && "type" in x && "name" in x;
}

function isCtxItem(x: Item): x is Ctx {
  if (typeof x !== "object" || x === null || isToken(x as TreeChild) || !("op" in x)) return false;
  const op = (x as { op: string }).op;
  return op === "hour_in" || op === "subtype_eq" || op === "device_eq";
}

function transform(node: TreeChild, text: string): Item {
  if (node === null || isToken(node)) return node;
  const items: Item[] = node.children.map((c) => transform(c, text));
  const tok = (i: number): Token => items[i] as Token;
  switch (node.data) {
    case "rule": {
      const vars = items.filter(isVarDeclItem);
      const when = items.filter(isCtxItem);
      const rest = items.filter((i) => !isVarDeclItem(i) && !isCtxItem(i));
      if (rest.length !== 1) throw new Error("malformed rule");
      return { vars, body: rest[0] as Phi, when } satisfies Rule;
    }
    case "vardecl":
      return { name: tok(0).value, type: tok(1).value as VarType };
    case "atom":
      return {
        op: "atom",
        pred: tok(0).value,
        args: items.slice(1).filter((t) => t !== null).map((t) => (t as Token).value),
      };
    case "not_":
      return { op: "not", arg: items[0] as Phi };
    case "and_":
      return flatten("and", items as Phi[]);
    case "or_":
      return flatten("or", items as Phi[]);
    case "then_": {
      let left = items[0] as Phi;
      for (let k = 1; k < items.length; k += 2) {
        const [a, b] = items[k] as readonly [Bound, Bound];
        left = { op: "then", a, b, left, right: items[k + 1] as Phi };
      }
      return left;
    }
    case "eventually":
    case "always": {
      const [a, b] = items[0] as readonly [Bound, Bound];
      return { op: node.data, a, b, arg: items[1] as Phi };
    }
    case "holds_for":
      return { op: "holds_for", d: bound(tok(0)), arg: items[1] as Phi };
    case "window":
      return [bound(tok(0)), bound(tok(1))] as const;
    case "hour_in":
      return { op: "hour_in", h1: hourBound(text, tok(0)), h2: hourBound(text, tok(1)) };
    case "subtype_eq": {
      const t = tok(0);
      if (!SUB_TYPE_SET.has(t.value)) {
        const [line, col] = lineCol(text, t.pos);
        throw new DSLSyntaxError(`unknown subtype '${t.value}'; known: ${SUB_TYPES.join(", ")}`, line, col);
      }
      return { op: "subtype_eq", value: t.value as SubType };
    }
    case "device_eq":
      return { op: "device_eq", value: tok(0).value };
    default:
      return node;
  }
}

// --------------------------------------------------------------------------- public API
let parser: LalrParser | null = null;

/**
 * Parse DSL text into a `Rule`.
 *
 * Nested `and`/`or` are flattened into n-ary nodes, time bounds become numbers, hour bounds integers,
 * `?name` becomes a Hole. Throws `DSLSyntaxError` (with line/column) on bad text. Parsing does not
 * typecheck: unknown predicates and ill-typed arguments are `typecheck`'s job.
 */
export function parse(text: string): Rule {
  parser ??= new LalrParser(PARSER_TABLES);
  let tree: Tree;
  try {
    tree = parser.parseTree(text);
  } catch (e) {
    if (e instanceof UnexpectedToken || e instanceof UnexpectedCharacters) throw syntaxError(e, text);
    throw e;
  }
  try {
    return transform(tree, text) as Rule;
  } catch (e) {
    if (e instanceof DSLSyntaxError) {
      e.context = context(text, e.line, e.column);
      throw e;
    }
    throw e;
  }
}

export type { Node };
