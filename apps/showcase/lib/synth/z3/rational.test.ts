// Fraction arithmetic and the numerals Z3 prints, against Python's Fraction (reference values computed with CPython).
import { test } from "node:test";
import assert from "node:assert/strict";
import { Fraction, fromDouble, limitDenominator, parseSexpr, ratOf, ratioToNumber } from "./rational.ts";

const f = (n: number, d: number): string => new Fraction(BigInt(n), BigInt(d)).toString();

test("limit_denominator(10**9) of a double equals Python's Fraction(x).limit_denominator(10**9)", () => {
  const cases: [number, string][] = [
    [0.1, "1/10"], [0.45, "9/20"], [2.675, "107/40"], [0.30000000000000004, "3/10"], [1 / 3, "1/3"], [29.746, "14873/500"],
    [0.001, "1/1000"], [123456.789, "57323552811689/464320782"], [0.6, "3/5"], [0.95, "19/20"], [1e-7, "1/10000000"], [3.0, "3"],
    [0.0005, "1/2000"],
  ];
  for (const [x, want] of cases) assert.equal(ratOf(x).toString(), want, String(x));
});

test("fromDouble is exact and round-trips", () => {
  for (const x of [0.5, 0.1, -2.75, 1e-300, 123456.789, 2 ** 60, 3]) assert.equal(fromDouble(x).toNumber(), x);
  assert.equal(fromDouble(0.5).toString(), "1/2");
  assert.equal(limitDenominator(fromDouble(0.5), 3n).toString(), "1/2");
});

test("toNumber is the correctly rounded double (Python float(Fraction))", () => {
  assert.equal(new Fraction(29746n, 1000n).toNumber(), 29.746);
  assert.equal(ratioToNumber(2n ** 70n + 1n, 3n ** 20n), 338590370078.1789);
  assert.equal(ratioToNumber(10n ** 30n + 1n, 10n ** 15n + 3n), 999999999999997.0);
  assert.equal(ratioToNumber(-1n, 3n), -1 / 3);
  assert.equal(ratioToNumber(0n, 5n), 0);
});

test("arithmetic", () => {
  const a = new Fraction(1n, 3n);
  const b = new Fraction(1n, 6n);
  assert.equal(a.add(b).toString(), "1/2");
  assert.equal(a.sub(b).toString(), "1/6");
  assert.equal(a.mul(b).toString(), "1/18");
  assert.equal(a.div(b).toString(), "2");
  assert.equal(f(-4, -6), "2/3");
  assert.equal(a.cmp(b), 1);
  assert.ok(a.eq(new Fraction(2n, 6n)));
});

test("parseSexpr reads what Z3 prints, with epsilon = 0 (the closure)", () => {
  assert.equal(parseSexpr("2.0").toString(), "2");
  assert.equal(parseSexpr("(/ 1.0 3.0)").toString(), "1/3");
  assert.equal(parseSexpr("(/ 14873.0 500.0)").toNumber(), 29.746);
  assert.equal(parseSexpr("(+ 2.0 (* (- 1.0) epsilon))").toString(), "2");
  assert.equal(parseSexpr("(+ (/ 1.0 2.0) epsilon)").toString(), "1/2");
  assert.equal(parseSexpr("(- 1.5)").toString(), "-3/2");
  assert.equal(parseSexpr("(- 5.0 2.0 1.0)").toString(), "2");
  assert.equal(parseSexpr("7").toString(), "7");
  assert.equal(parseSexpr("-2.5").toString(), "-5/2");
  assert.equal(parseSexpr("0").toNumber(), 0);
  assert.throws(() => parseSexpr("(foo 1.0)"));
  assert.throws(() => parseSexpr("x"));
  assert.throws(() => parseSexpr("(+ 1.0"));
  assert.throws(() => parseSexpr("1.0 2.0"));
});
