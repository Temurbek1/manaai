# Bounded braces (private development dependency)

This is a reviewed local fork of `braces@3.0.3` from
[micromatch/braces](https://github.com/micromatch/braces/tree/3.0.3), retaining its
MIT license and parser syntax. The only current `braces` consumer is the pinned
Next ESLint plugin's `fast-glob`/`micromatch` chain. A root dev dependency and
`$braces` override keep npm's file dependency rooted in this repository. The
compatibility check rejects other consumers until reviewed. It is not published
and is not a patched upstream release. Do not call it `braces@3.0.4` or suppress
the advisory.

The fork guards AST depth/size and parent cycles before recursive walkers run,
including direct AST inputs. Parsing caps both parenthesis and brace nesting;
quote, character-class and escaped-brace handling stay in the upstream parser.
Array flattening and Cartesian concatenation are iterative. Expansion is limited
to 1,000 results and 1 MiB of intermediate/output text; oversized and unsafe
integer ranges are rejected before `fill-range` allocates. The guard cannot be
disabled with `rangeLimit: false`. Exceeding a limit throws; it does not silently
omit roots. The upstream input ceiling remains 10,000 characters, with a maximum
AST walk depth of 128 and 65,536 nodes. An upstream debugging log was removed.

This is a maintenance obligation, not a claim of universal security or equivalence
outside these explicit limits. The dependency gate remains unchanged. Compatibility,
real Next root discovery/rule behavior and denial-of-service regression tests must
run on every lint invocation. Remove the override/fork after a compatible,
audited upstream replacement is available and the same tests pass. Docker dependency
installation must copy this package before `npm ci`.
