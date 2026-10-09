"use strict";

const fill = require("fill-range");
const utils = require("./utils");
const guards = require("./guards");

const compile = (ast, options = {}) => {
  guards.assertAst(ast);
  const walk = (node, parent = {}) => {
    const invalidBlock = utils.isInvalidBrace(parent);
    const invalidNode = node.invalid === true && options.escapeInvalid === true;
    const invalid = invalidBlock === true || invalidNode === true;
    const prefix = options.escapeInvalid === true ? "\\" : "";
    let output = "";

    if (node.isOpen === true) {
      return prefix + node.value;
    }

    if (node.isClose === true) {
      return prefix + node.value;
    }

    if (node.type === "open") {
      return invalid ? prefix + node.value : "(";
    }

    if (node.type === "close") {
      return invalid ? prefix + node.value : ")";
    }

    if (node.type === "comma") {
      return node.prev.type === "comma" ? "" : invalid ? node.value : "|";
    }

    if (node.value) {
      return node.value;
    }

    if (node.nodes && node.ranges > 0) {
      const args = utils.reduce(node.nodes);
      guards.assertRange(args, options, guards.MAX_RESULTS);
      const range = fill(...args, {
        ...options,
        wrap: false,
        toRegex: true,
        strictZeros: true,
      });

      if (range.length !== 0) {
        return args.length > 1 && range.length > 1 ? `(${range})` : range;
      }
    }

    if (node.nodes) {
      for (const child of node.nodes) {
        output += walk(child, node);
      }
    }

    return output;
  };

  return guards.assertOutput([walk(ast)])[0];
};

module.exports = compile;
