// Port of engine/exemplar/contracts/ontology.py (ontology v1). Keep in sync with the Python file.
// Lookups that take user-controlled keys use Map / Set so that names such as "constructor" never hit Object.prototype.

export type EntityType = "person" | "vehicle" | "package" | "animal" | "object";
export const ENTITY_TYPES: readonly EntityType[] = ["person", "vehicle", "package", "animal", "object"];

export type Zone = "door" | "porch" | "steps" | "yard" | "driveway" | "sidewalk" | "street" | "dock";
export const ZONES: readonly Zone[] = ["door", "porch", "steps", "yard", "driveway", "sidewalk", "street", "dock"];
export const ZONE_SET: ReadonlySet<string> = new Set(ZONES);

export type Conf = "low" | "med" | "high";
export const CONF_VALUE: Readonly<Record<Conf, number>> = { low: 0.6, med: 0.8, high: 0.95 };
/** Signal value when a predicate is not asserted in a frame. */
export const ABSENT_VALUE = 0.05;
/** rho(atom, t) = s(t) - THRESHOLD (docs/DSL.md). */
export const THRESHOLD = 0.5;
/** C: robustness of empty windows / crisp context atoms is +-CLAMP. */
export const CLAMP = 0.5;

export type SubType = "human" | "vehicle" | "package_delivery" | "other_motion" | "motion" | "ding" | "on_demand";
export const SUB_TYPES: readonly SubType[] = [
  "human", "vehicle", "package_delivery", "other_motion", "motion", "ding", "on_demand",
];
export const SUB_TYPE_SET: ReadonlySet<string> = new Set(SUB_TYPES);

export type ArgKind =
  | "Entity" | "Person" | "Vehicle" | "Package" | "Animal" | "Object" | "Carryable" | "Zone" | "Label";

/** Predicate signatures in the engine's declaration order (the order is printed in typecheck messages). */
export const PREDICATES: ReadonlyMap<string, readonly ArgKind[]> = new Map<string, readonly ArgKind[]>([
  ["present", ["Entity"]],
  ["in_zone", ["Entity", "Zone"]],
  ["near", ["Entity", "Entity"]],
  ["carrying", ["Person", "Carryable"]],
  ["picks_up", ["Person", "Carryable"]],
  ["puts_down", ["Person", "Carryable"]],
  ["rings_bell", ["Person"]],
  ["enters", ["Entity", "Zone"]],
  ["leaves", ["Entity", "Zone"]],
  ["facing_camera", ["Person"]],
  ["attr", ["Entity", "Label"]],
]);

export type VarType = "Entity" | "Person" | "Vehicle" | "Package" | "Animal" | "Object" | "Carryable";
export const VAR_TYPE_NAMES: readonly VarType[] = [
  "Entity", "Person", "Vehicle", "Package", "Animal", "Object", "Carryable",
];

/** DSL variable types and the entity types each admits. */
export const VAR_TYPES: ReadonlyMap<string, readonly string[]> = new Map<string, readonly string[]>([
  ["Entity", ENTITY_TYPES],
  ["Person", ["person"]],
  ["Vehicle", ["vehicle"]],
  ["Package", ["package"]],
  ["Animal", ["animal"]],
  ["Object", ["object"]],
  ["Carryable", ["package", "object"]],
]);

/** True if an entity of `entityType` may fill an argument slot of `kind` (entity kinds only). */
export function kindAdmits(kind: string, entityType: string): boolean {
  const admitted = VAR_TYPES.get(kind);
  return admitted !== undefined && admitted.includes(entityType);
}
