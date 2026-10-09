import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pluginPath = require.resolve("@next/eslint-plugin-next/package.json");
const pluginRequire = createRequire(pluginPath);
const globPath = pluginRequire.resolve("fast-glob/package.json");
const globRequire = createRequire(globPath);
const matchPath = globRequire.resolve("micromatch/package.json");
const matchRequire = createRequire(matchPath);
const braces = matchRequire("braces");
const localBraces = require("../vendor/bounded-braces");
const { getRootDirs } = pluginRequire("./dist/utils/get-root-dirs.js");
const { ESLint } = require("eslint");
const plugin = pluginRequire("./dist/index.js");
const fixture = mkdtempSync(join(tmpdir(), "manaai-next-glob-"));
after(() => rmSync(fixture, { recursive: true, force: true }));

for (const name of ["alpha", "beta", "01", "02", "with space", ".hidden"]) {
  mkdirSync(join(fixture, "apps", name, "pages"), { recursive: true });
  writeFileSync(
    join(fixture, "apps", name, "pages", "home.js"),
    "export default null;\n",
  );
}
writeFileSync(
  join(fixture, "apps", "not-a-directory.js"),
  "export default null;\n",
);

test("the pinned Next lint chain resolves the guarded local fork", () => {
  assert.equal(pluginRequire("./package.json").version, "16.3.8");
  assert.equal(globRequire("./package.json").version, "3.3.1");
  assert.equal(matchRequire("./package.json").version, "4.0.8");
  assert.equal(
    matchRequire("braces/package.json").name,
    "@manaai/bounded-braces",
  );
  assert.equal(braces, localBraces);
  const lock = JSON.parse(readFileSync(join(projectRoot, "package-lock.json")));
  const consumers = Object.entries(lock.packages)
    .filter(([, metadata]) => metadata.dependencies?.braces)
    .map(([path]) => path);
  assert.deepEqual(consumers, ["node_modules/micromatch"]);
  assert.equal(
    lock.packages["node_modules/braces"].resolved,
    "vendor/bounded-braces",
  );
  assert.equal(lock.packages["node_modules/braces"].link, true);
});

const expansions = [
  ["apps/{a,b}", ["apps/a", "apps/b"]],
  ["apps/{01..03}", ["apps/01", "apps/02", "apps/03"]],
  ["apps/{3..1}", ["apps/3", "apps/2", "apps/1"]],
  ["apps/{a,{b,c}}", ["apps/a", "apps/b", "apps/c"]],
  ["apps/\\{a,b\\}", ["apps/{a,b}"]],
  ["apps/{,a}", ["apps/", "apps/a"]],
  ["apps/${a,b}", ["apps/${a,b}"]],
  ["{a}", ["{a}"]],
  ["{{a}}", ["{{a}}"]],
  ["apps/{a,}", ["apps/a", "apps/"]],
  ["apps/[{a,b}]", ["apps/[{a,b}]"]],
  ['apps/"{a,b}"', ["apps/{a,b}"]],
  ["apps/'{a,b}'", ["apps/{a,b}"]],
  ["apps/{a,b}[{1,2}]", ["apps/a[{1,2}]", "apps/b[{1,2}]"]],
  ["apps/{1..3..0}", ["apps/1", "apps/2", "apps/3"]],
  ["apps/{a,,b}", ["apps/a", "apps/", "apps/b"]],
  ["apps/[abc{d,e}]", ["apps/[abc{d,e}]"]],
  ["apps/\\[{a,b}\\]", ["apps/[a]", "apps/[b]"]],
  ["apps/{a},b}", ["apps/{a},b}"]],
  ["{1..3}{a,b}", ["1a", "1b", "2a", "2b", "3a", "3b"]],
  ["{+1..+3}", ["1", "2", "3"]],
  ["{1e1..11}", ["10", "11"]],
];

for (const [pattern, expected] of expansions) {
  test(`upstream-compatible bounded expansion: ${pattern}`, () => {
    assert.deepEqual(localBraces.expand(pattern), expected);
  });
}

test("all public entry points retain supported compile/AST/options behavior", () => {
  assert.deepEqual(localBraces("apps/{a,b}"), ["apps/(a|b)"]);
  assert.equal(
    localBraces.compile(localBraces.parse("apps/{a,b}")),
    "apps/(a|b)",
  );
  assert.equal(
    localBraces.stringify(localBraces.parse("apps/{a,b}")),
    "apps/{a,b}",
  );
  assert.deepEqual(localBraces.expand(localBraces.parse("apps/{a,b}")), [
    "apps/a",
    "apps/b",
  ]);
  assert.deepEqual(localBraces(["{a,b}", "{c,d}"], { expand: true }), [
    "a",
    "b",
    "c",
    "d",
  ]);
  assert.deepEqual(
    localBraces.expand("{,a,a}", { noempty: true, nodupes: true }),
    ["a"],
  );
  assert.deepEqual(localBraces.expand("{1..10}", { step: 3 }), [
    "1",
    "4",
    "7",
    "10",
  ]);
  assert.equal(localBraces.expand("{1..1000}").length, 1000);
});

const resourceError = (error) =>
  error instanceof RangeError && /resource limit/.test(error.message);
for (const [opening, closing] of [
  ["{", "}"],
  ["(", ")"],
]) {
  for (const closed of [true, false]) {
    test(`deep ${opening} input is rejected before recursive walkers (closed=${closed})`, () => {
      const pattern =
        opening.repeat(3000) + "a,b" + (closed ? closing.repeat(3000) : "");
      for (const entry of [
        localBraces,
        localBraces.parse,
        localBraces.expand,
        localBraces.compile,
        localBraces.stringify,
        localBraces.create,
      ]) {
        assert.throws(() => entry(pattern), resourceError);
      }
    });
  }
}

test("pre-parsed deep/cyclic ASTs cannot bypass the depth guard", () => {
  const root = { type: "root", nodes: [] };
  let node = root;
  for (let i = 0; i < 5000; i++) {
    const child = { type: "brace", parent: node, nodes: [] };
    node.nodes.push(child);
    node = child;
  }
  for (const entry of [
    localBraces.compile,
    localBraces.expand,
    localBraces.stringify,
  ]) {
    assert.throws(() => entry(root), resourceError);
    const cyclic = { type: "root", nodes: [] };
    cyclic.nodes.push(cyclic);
    assert.throws(() => entry(cyclic), TypeError);
    const parentCycle = { type: "root", nodes: [] };
    parentCycle.parent = parentCycle;
    assert.throws(() => entry(parentCycle), TypeError);
  }
});

test("huge/unsafe ranges and rangeLimit overrides are rejected before allocation", () => {
  for (const pattern of [
    "{1..1000000000}",
    "{1000000000..1}",
    "{1..1000000000..2}",
    "{+1..+1000000000}",
    "{1e1..1e9}",
    "{0x01..0xFFFFFFF}",
    "{9007199254740992..9007199254741000}",
  ]) {
    for (const rangeLimit of [false, Infinity, NaN, 1000000000]) {
      assert.throws(
        () => localBraces.expand(pattern, { rangeLimit }),
        resourceError,
      );
    }
    assert.throws(() => localBraces.compile(pattern), resourceError);
  }
  assert.throws(() => localBraces.expand("{1..1001}"), resourceError);
  assert.throws(() => localBraces.expand("{1..100}{1..100}"), resourceError);
  assert.throws(
    () => localBraces.expand(`{${"0".repeat(9000)}1..200}`),
    resourceError,
  );
  assert.throws(
    () =>
      localBraces.expand(`{${"a".repeat(1500)},${"b".repeat(1500)}}{1..500}`),
    resourceError,
  );
  assert.throws(() => localBraces(Array(1001).fill("a")), resourceError);
  assert.throws(() => localBraces.parse("a".repeat(10001)), SyntaxError);
  assert.throws(
    () => localBraces.parse("a".repeat(10001), { maxLength: NaN }),
    SyntaxError,
  );
  assert.throws(
    () => localBraces.parse("a".repeat(10001), { maxLength: Infinity }),
    SyntaxError,
  );
});

test("iterative flattening preserves order and bounds cyclic internal arrays", () => {
  const { flatten } = require("../vendor/bounded-braces/lib/utils");
  assert.deepEqual(flatten(["a", ["b", ["c"]]], [], undefined, "d"), [
    "a",
    "b",
    "c",
    "d",
  ]);
  const cycle = [];
  cycle.push(cycle);
  assert.throws(() => flatten(cycle), resourceError);
});

const roots = (rootDir) =>
  getRootDirs({ cwd: fixture, settings: { next: { rootDir } } }).sort();
test("Next rootDir preserves literal, absolute, wildcard, brace and array behavior", () => {
  const alpha = join(fixture, "apps", "alpha");
  const beta = join(fixture, "apps", "beta");
  assert.deepEqual(roots(undefined), [fixture]);
  assert.deepEqual(roots(alpha), [alpha]);
  assert.deepEqual(roots(join(fixture, "apps", "{alpha,beta}")), [alpha, beta]);
  assert.deepEqual(roots(join(fixture, "apps", "{01..02}")), [
    join(fixture, "apps", "01"),
    join(fixture, "apps", "02"),
  ]);
  assert.deepEqual(roots([alpha, beta, false, null]), [alpha, beta]);
  assert.deepEqual(roots(join(fixture, "apps", "with space")), [
    join(fixture, "apps", "with space"),
  ]);
  assert.deepEqual(roots(alpha.replaceAll("/", "\\")), [alpha]);
  assert.deepEqual(roots(join(fixture, "apps", "not-a-directory.js")), []);
  const visible = ["01", "02", "alpha", "beta", "with space"].map((name) =>
    join(fixture, "apps", name),
  );
  assert.deepEqual(roots(join(fixture, "apps", "*")), visible);
  assert.deepEqual(
    roots(join(fixture, "apps", "*", "pages")),
    visible.map((dir) => join(dir, "pages")),
  );
  assert.deepEqual(roots(join(alpha, "**")), [join(alpha, "pages")]);
  assert.deepEqual(roots(join(fixture, "apps", "{alpha,{beta,with space}}")), [
    alpha,
    beta,
    join(fixture, "apps", "with space"),
  ]);
});

test("the real Next rule still rejects internal HTML links for globbed roots", async () => {
  const eslint = new ESLint({
    cwd: fixture,
    overrideConfigFile: true,
    overrideConfig: {
      files: ["**/*.jsx"],
      languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
      plugins: { "@next/next": plugin },
      settings: { next: { rootDir: join(fixture, "apps", "{alpha,beta}") } },
      rules: { "@next/next/no-html-link-for-pages": "error" },
    },
  });
  const [bad] = await eslint.lintText(
    'export default () => <a href="/home">Home</a>;',
    { filePath: join(fixture, "case.jsx") },
  );
  assert.equal(bad.errorCount, 1);
  assert.equal(bad.messages[0].ruleId, "@next/next/no-html-link-for-pages");
  const [good] = await eslint.lintText(
    'export default () => <a href="https://example.com">External</a>;',
    { filePath: join(fixture, "case.jsx") },
  );
  assert.equal(good.errorCount, 0);
});

test("the project still enables all recommended Next rules", async () => {
  const eslint = new ESLint({ cwd: projectRoot });
  const config = await eslint.calculateConfigForFile(
    join(projectRoot, "src/app/page.tsx"),
  );
  for (const rule of Object.keys(plugin.configs.recommended.rules)) {
    assert.ok(config.rules[rule][0] > 0, `${rule} must remain enabled`);
  }
  assert.equal(config.rules["@typescript-eslint/no-require-imports"][0], 2);
});
