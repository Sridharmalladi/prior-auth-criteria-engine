// Runs data/parity/fixtures.json through the JS evaluator and prints one JSON
// object per fixture on stdout. The Python side of the parity test compares
// this output field by field against its own run.
//
//   node pipeline/tests/parity_js.mjs [path/to/fixtures.json]

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { evaluate } from '../../docs/js/evaluator.js';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const fixturesPath = process.argv[2] || join(repoRoot, 'data', 'parity', 'fixtures.json');

const fixtures = JSON.parse(readFileSync(fixturesPath, 'utf8'));
const results = fixtures.map((fixture) => {
  const result = evaluate(fixture.tree, fixture.facts);
  return {
    name: fixture.name,
    root_state: result.root_state,
    decision: result.decision,
    blocking_node: result.blocking_node,
    satisfaction: result.satisfaction,
    confidence: result.confidence,
    states: result.states,
    bindings: result.bindings,
  };
});

process.stdout.write(JSON.stringify(results));
