// A table-driven LALR(1) parser with a contextual lexer: a faithful port of the parts of Lark
// (lark/parsers/lalr_parser.py, lark/lexer.py, lark/parse_tree_builder.py) that the DSL parser uses.
//
// The tables come from the engine's own Lark grammar (parser-tables.ts, generated), so this driver is
// grammar-agnostic. It reproduces, step for step:
//   * the contextual lexer (per-parser-state terminal sets; ordered regex alternation; keyword/regex
//     "unless" conversion; the root-lexer fallback that turns lexer errors into UnexpectedToken),
//   * the LALR shift/reduce loop, including that a failing token can leave earlier reductions applied,
//   * InteractiveParser.accepts() (the exact set of terminals the parser could take next),
//   * the parse-tree builder (filtered tokens, inlined `_rules`, `?rule` single-child expansion).

export interface RuleDef {
  readonly origin: string;
  readonly len: number;
  /** Per expansion symbol: is its value passed to the rule's callback (anonymous string tokens are not). */
  readonly keep: readonly boolean[];
  /** Per expansion symbol: is it an inlined `_rule` whose children are spliced into this rule's children. */
  readonly expand: readonly boolean[];
  readonly alias: string | null;
  /** `?rule`: a single remaining child replaces the node (not applied when an alias is set). */
  readonly expand1: boolean;
}

export interface LexerDef {
  /** Terminal names in scanner order (priority, then width, ...); ignored terminals included. */
  readonly terms: readonly string[];
  /** Regex-terminal name -> { exact literal text -> terminal type it is converted to }. */
  readonly unless: Readonly<Record<string, Readonly<Record<string, string>>>>;
}

export type TerminalDef =
  | { readonly kind: "str"; readonly value: string }
  | { readonly kind: "re"; readonly value: string };

/** [0, nextState] = shift/goto, [1, ruleIndex] = reduce. */
export type Action = readonly [number, number];

export interface ParserTables {
  readonly grammar_sha256: string;
  readonly lark_version: string;
  readonly start: number;
  readonly end: number;
  readonly terminals: readonly string[];
  readonly ignore: readonly string[];
  readonly rules: readonly RuleDef[];
  readonly states: readonly Readonly<Record<string, Action>>[];
  readonly lexer_of_state: readonly number[];
  readonly lexers: readonly LexerDef[];
  readonly root: number;
  readonly defs: Readonly<Record<string, TerminalDef>>;
}

export class Token {
  type: string;
  readonly value: string;
  /** Offset in UTF-16 code units. */
  readonly pos: number;
  constructor(type: string, value: string, pos: number) {
    this.type = type;
    this.value = value;
    this.pos = pos;
  }
}

export interface Tree {
  readonly data: string;
  readonly children: readonly TreeChild[];
}
export type TreeChild = Tree | Token | null;

export function isToken(x: TreeChild): x is Token {
  return x instanceof Token;
}

/** The token at `pos` does not fit the grammar (raised by the parser, or by the lexer's root-lexer fallback). */
export class UnexpectedToken extends Error {
  readonly token: Token;
  /** Terminals the parser could take next (InteractiveParser.accepts()). */
  readonly accepts: ReadonlySet<string>;
  /** Fallback when accepts() is empty: the lexer's allowed set / the failing state's keys. */
  readonly expected: ReadonlySet<string>;
  constructor(token: Token, accepts: ReadonlySet<string>, expected: ReadonlySet<string>) {
    super(`unexpected token ${token.type} ${JSON.stringify(token.value)}`);
    this.name = "UnexpectedToken";
    this.token = token;
    this.accepts = accepts;
    this.expected = expected;
  }
}

/** No terminal of the current lexer state matches at `pos` (and neither does any terminal at all). */
export class UnexpectedCharacters extends Error {
  readonly pos: number;
  readonly char: string;
  readonly allowed: ReadonlySet<string>;
  constructor(pos: number, char: string, allowed: ReadonlySet<string>) {
    super(`unexpected character at ${pos}`);
    this.name = "UnexpectedCharacters";
    this.pos = pos;
    this.char = char;
    this.allowed = allowed;
  }
}

interface ParserState {
  stack: number[];
  values: unknown[];
}

interface Scanner {
  readonly names: readonly string[];
  readonly matchers: readonly ((text: string, pos: number) => string | null)[];
  readonly unless: ReadonlyMap<string, ReadonlyMap<string, string>>;
  readonly allowed: ReadonlySet<string>;
}

function makeMatcher(def: TerminalDef): (text: string, pos: number) => string | null {
  if (def.kind === "str") {
    const v = def.value;
    return (text, pos) => (text.startsWith(v, pos) ? v : null);
  }
  const re = new RegExp(def.value, "y");
  return (text, pos) => {
    re.lastIndex = pos;
    const m = re.exec(text);
    return m === null ? null : m[0];
  };
}

export class LalrParser {
  readonly tables: ParserTables;
  private readonly scanners: Scanner[];
  private readonly terminalNames: ReadonlySet<string>;
  private readonly ignore: ReadonlySet<string>;

  constructor(tables: ParserTables) {
    this.tables = tables;
    this.terminalNames = new Set(tables.terminals);
    this.ignore = new Set(tables.ignore);
    const matcherCache = new Map<string, (text: string, pos: number) => string | null>();
    const matcherFor = (name: string): ((text: string, pos: number) => string | null) => {
      let m = matcherCache.get(name);
      if (m === undefined) {
        m = makeMatcher(tables.defs[name]);
        matcherCache.set(name, m);
      }
      return m;
    };
    this.scanners = tables.lexers.map((lx) => ({
      names: lx.terms,
      matchers: lx.terms.map(matcherFor),
      unless: new Map(Object.entries(lx.unless).map(([k, v]) => [k, new Map(Object.entries(v))])),
      allowed: new Set(lx.terms.filter((t) => !this.ignore.has(t))),
    }));
  }

  // ------------------------------------------------------------------ lexing
  /**
   * BasicLexer.next_token: the next non-ignored token at or after `pos`, or null at end of input.
   * Returns the new position through `out`.
   */
  private nextToken(scanner: Scanner, text: string, start: number, out: { pos: number }): Token | null {
    let pos = start;
    while (pos < text.length) {
      let value: string | null = null;
      let type = "";
      for (let i = 0; i < scanner.names.length; i++) {
        const m = scanner.matchers[i](text, pos);
        if (m !== null) {
          value = m;
          type = scanner.names[i];
          break;
        }
      }
      if (value === null) {
        const cp = text.codePointAt(pos) as number;
        throw new UnexpectedCharacters(pos, String.fromCodePoint(cp), scanner.allowed);
      }
      const conv = scanner.unless.get(type);
      if (conv !== undefined) {
        const to = conv.get(value);
        if (to !== undefined) type = to;
      }
      const ignored = this.ignore.has(type);
      const at = pos;
      pos += value.length;
      if (!ignored) {
        out.pos = pos;
        return new Token(type, value, at);
      }
    }
    out.pos = pos;
    return null;
  }

  // ------------------------------------------------------------------ parsing
  private top(st: ParserState): number {
    return st.stack[st.stack.length - 1];
  }

  /** ParserState.feed_token. On failure the reductions already applied stay applied, as in Lark. */
  private feed(st: ParserState, token: Token, isEnd: boolean): unknown {
    const t = this.tables;
    for (;;) {
      const state = this.top(st);
      const act = t.states[state][token.type];
      if (act === undefined) {
        const keys = new Set(Object.keys(t.states[state]).filter((k) => this.terminalNames.has(k)));
        throw new FeedFailure(token, keys);
      }
      if (act[0] === 0) {
        st.stack.push(act[1]);
        st.values.push(token);
        return undefined;
      }
      const rule = t.rules[act[1]];
      const size = rule.len;
      let vals: unknown[] = [];
      if (size > 0) {
        vals = st.values.splice(st.values.length - size, size);
        st.stack.length -= size;
      }
      const value = this.build(rule, vals);
      const goto = t.states[this.top(st)][rule.origin];
      st.stack.push(goto[1]);
      st.values.push(value);
      if (isEnd && this.top(st) === t.end) return st.values[st.values.length - 1];
    }
  }

  /** ParseTreeBuilder: filter tokens, splice inlined rules, expand single children, build a Tree. */
  private build(rule: RuleDef, values: unknown[]): unknown {
    const kids: TreeChild[] = [];
    for (let i = 0; i < rule.len; i++) {
      if (!rule.keep[i]) continue;
      const v = values[i] as TreeChild;
      if (rule.expand[i]) kids.push(...(v as Tree).children);
      else kids.push(v);
    }
    if (rule.expand1 && rule.alias === null && kids.length === 1) return kids[0];
    return { data: rule.alias ?? rule.origin, children: kids } satisfies Tree;
  }

  /** InteractiveParser.accepts(): terminals the parser could take next from this (possibly reduced) state. */
  private accepts(st: ParserState): Set<string> {
    const t = this.tables;
    const out = new Set<string>();
    for (const sym of Object.keys(t.states[this.top(st)])) {
      if (!this.terminalNames.has(sym)) continue;
      if (this.canFeed(st.stack, sym)) out.add(sym);
    }
    return out;
  }

  private canFeed(stack0: readonly number[], term: string): boolean {
    const t = this.tables;
    const stack = stack0.slice();
    for (;;) {
      const act = t.states[stack[stack.length - 1]][term];
      if (act === undefined) return false;
      if (act[0] === 0) return true;
      const rule = t.rules[act[1]];
      stack.length -= rule.len;
      stack.push(t.states[stack[stack.length - 1]][rule.origin][1]);
      if (term === "$END" && stack[stack.length - 1] === t.end) return true;
    }
  }

  /**
   * Parse `text` into a raw parse tree (rule alias or name as `Tree.data`). Throws UnexpectedToken or
   * UnexpectedCharacters, with the information the DSL's error formatter needs.
   */
  parseTree(text: string): Tree {
    const t = this.tables;
    const st: ParserState = { stack: [t.start], values: [] };
    const out = { pos: 0 };
    let pos = 0;
    try {
      for (;;) {
        const scanner = this.scanners[t.lexer_of_state[this.top(st)]];
        let tok: Token | null;
        try {
          tok = this.nextToken(scanner, text, pos, out);
        } catch (e) {
          if (!(e instanceof UnexpectedCharacters)) throw e;
          // ContextualLexer.lex: retry with the root lexer so a valid-but-misplaced token reads nicely.
          let rootTok: Token | null = null;
          try {
            rootTok = this.nextToken(this.scanners[t.root], text, e.pos, { pos: 0 });
          } catch (e2) {
            if (!(e2 instanceof UnexpectedCharacters)) throw e2;
          }
          if (rootTok === null) throw e;
          throw new UnexpectedToken(rootTok, new Set(), e.allowed);
        }
        if (tok === null) break;
        pos = out.pos;
        this.feed(st, tok, false);
      }
      const end = new Token("$END", "", text.length);
      return this.feed(st, end, true) as Tree;
    } catch (e) {
      if (e instanceof FeedFailure) throw new UnexpectedToken(e.token, this.accepts(st), e.expected);
      if (e instanceof UnexpectedToken) {
        throw new UnexpectedToken(e.token, this.accepts(st), e.expected);
      }
      if (e instanceof UnexpectedCharacters) throw e;
      throw e;
    }
  }
}

/** Internal: feed() failed; converted to UnexpectedToken once the parser state is final. */
class FeedFailure extends Error {
  readonly token: Token;
  readonly expected: ReadonlySet<string>;
  constructor(token: Token, expected: ReadonlySet<string>) {
    super("feed failure");
    this.token = token;
    this.expected = expected;
  }
}
