"use strict";

const MAX_AST_DEPTH = 128;
const MAX_AST_NODES = 65536;
const MAX_RESULTS = 1000;
const MAX_OUTPUT_CHARACTERS = 1048576;

const limitError = () =>
  new RangeError("Bounded braces resource limit exceeded");

// Follow children and parent links without recursive traversal. Parsed ASTs
// legitimately retain detached parent links when invalid blocks are flattened.
const assertAst = (ast) => {
  const pending = [{ node: ast, depth: 0 }];
  const seen = new WeakSet();
  let characters = 0;
  let nodes = 0;
  while (pending.length) {
    const { node, depth } = pending.pop();
    if (!node || typeof node !== "object" || seen.has(node)) {
      throw new TypeError("Bounded braces requires an acyclic AST");
    }
    seen.add(node);
    if (++nodes > MAX_AST_NODES || depth > MAX_AST_DEPTH) throw limitError();
    if (node.value !== undefined) {
      if (typeof node.value !== "string")
        throw new TypeError("Invalid AST text");
      characters += node.value.length;
      if (characters > MAX_OUTPUT_CHARACTERS) throw limitError();
    }
    const parents = new WeakSet([node]);
    let parent = node.parent;
    let parentDepth = 0;
    while (parent !== undefined) {
      if (!parent || typeof parent !== "object" || parents.has(parent)) {
        throw new TypeError("Bounded braces requires acyclic parent links");
      }
      if (++parentDepth > MAX_AST_DEPTH) throw limitError();
      parents.add(parent);
      parent = parent.parent;
    }
    if (node.nodes !== undefined) {
      if (!Array.isArray(node.nodes))
        throw new TypeError("Invalid AST children");
      if (pending.length + node.nodes.length > MAX_AST_NODES)
        throw limitError();
      for (const child of node.nodes)
        pending.push({ node: child, depth: depth + 1 });
    }
  }
};

const assertOutput = (values) => {
  if (values.length > MAX_RESULTS) throw limitError();
  let characters = 0;
  for (const value of values) {
    characters += String(value).length;
    if (characters > MAX_OUTPUT_CHARACTERS) throw limitError();
  }
  return values;
};

const assertRange = (args, options, requestedLimit) => {
  const [from, to] = args;
  if (typeof from !== "string" || typeof to !== "string" || !from || !to)
    return;
  // Match fill-range's numeric dispatch, including exponent, hex and plus signs.
  const numeric =
    Number.isInteger(Number(from)) && Number.isInteger(Number(to));
  const letters =
    (Number.isInteger(Number(from)) || from.length === 1) &&
    (Number.isInteger(Number(to)) || to.length === 1);
  if (!numeric && !letters) return;
  const min = numeric ? Number(from) : from.charCodeAt(0);
  const max = numeric ? Number(to) : to.charCodeAt(0);
  const step = Math.max(Math.abs(Number(args[2] || options.step || 1)), 1);
  if (
    !Number.isSafeInteger(min) ||
    !Number.isSafeInteger(max) ||
    !Number.isSafeInteger(step)
  ) {
    throw limitError();
  }
  const limit = Number.isFinite(requestedLimit)
    ? Math.min(requestedLimit, MAX_RESULTS)
    : MAX_RESULTS;
  // Both ascending and descending ranges are checked before fill-range allocates.
  const count = Math.floor(Math.abs(max - min) / step) + 1;
  if (count > limit) throw limitError();
  const width = Math.max(
    from.length,
    to.length,
    String(args[2] || options.step || 1).length,
  );
  if (numeric && count * width > MAX_OUTPUT_CHARACTERS) throw limitError();
};

module.exports = {
  MAX_AST_DEPTH,
  MAX_AST_NODES,
  MAX_RESULTS,
  MAX_OUTPUT_CHARACTERS,
  limitError,
  assertAst,
  assertOutput,
  assertRange,
};
