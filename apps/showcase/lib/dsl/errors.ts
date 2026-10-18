// Port of engine/exemplar/dsl/errors.py.

export class DSLError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DSLError";
  }
}

/**
 * Text could not be parsed. `line` / `column` are 1-based.
 *
 * Python keeps the short text in `.message` and `str(err)` is "line L, column C: message". JavaScript's
 * `Error.message` is what `String(err)` prints, so here `message` is the full "line L, column C: ..."
 * text and the short LLM-readable text is `reason`. `context` is the offending source line with a caret.
 */
export class DSLSyntaxError extends DSLError {
  readonly reason: string;
  readonly line: number;
  readonly column: number;
  context: string;

  constructor(reason: string, line = 1, column = 1, context = "") {
    super(`line ${line}, column ${column}: ${reason}`);
    this.name = "DSLSyntaxError";
    this.reason = reason;
    this.line = line;
    this.column = column;
    this.context = context;
  }
}

/** An evaluator was given a rule that still has holes (`?name`) and no value for them. */
export class UnboundHoleError extends DSLError {
  readonly names: string[];

  constructor(names: readonly string[]) {
    super(
      "rule has unfilled holes: " + names.map((n) => "?" + n).join(", ") +
        " (pass holes={...} or fill_holes() first)",
    );
    this.name = "UnboundHoleError";
    this.names = [...names];
  }
}
