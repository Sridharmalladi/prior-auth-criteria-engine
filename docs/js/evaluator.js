// Three-valued criteria-tree evaluator.
//
// This file and pipeline/evaluate.py are two implementations of one contract.
// They are held together by data/parity/fixtures.json and the parity CI job.
// Any change here must be mirrored there in the same commit.
//
// No dependencies. Runs in the browser as an ES module and under Node for the
// parity harness.

export const TRUE = 'TRUE';
export const FALSE = 'FALSE';
export const UNKNOWN = 'UNKNOWN';

// Sentinel used when a candidate blocking node has no meaningful numeric gap
// (booleans, set membership, missing facts). Keeps ordering total and stable.
export const NO_DELTA = Infinity;

// Half-up rounding to 4 dp. Defined explicitly because Python's round() is
// half-to-even and JS's toFixed() is neither; parity needs one rule.
function round4(value) {
  const scaled = value * 10000;
  return scaled >= 0
    ? Math.floor(scaled + 0.5) / 10000
    : -(Math.floor(-scaled + 0.5) / 10000);
}

// ---------------------------------------------------------------------------
// predicates
// ---------------------------------------------------------------------------

function asList(value) {
  return Array.isArray(value) ? value : [value];
}

function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

// Apply one predicate to one observed value. Never returns UNKNOWN: absence is
// handled by the caller, not here.
export function applyPredicate(predicate, factValue) {
  const op = predicate.op;
  const target = predicate.value;

  if (op === '>=') {
    if (!isNumber(factValue)) return FALSE;
    return factValue >= target ? TRUE : FALSE;
  }
  if (op === '<=') {
    if (!isNumber(factValue)) return FALSE;
    return factValue <= target ? TRUE : FALSE;
  }
  if (op === '==') return equalValues(factValue, target) ? TRUE : FALSE;
  if (op === '!=') return equalValues(factValue, target) ? FALSE : TRUE;
  if (op === 'includes') {
    const observed = asList(factValue);
    return asList(target).every((item) => observed.includes(item)) ? TRUE : FALSE;
  }
  if (op === 'excludes') {
    const observed = asList(factValue);
    return asList(target).every((item) => !observed.includes(item)) ? TRUE : FALSE;
  }
  throw new Error(`unknown operator ${op}`);
}

// Python compares lists element-wise; JS === on arrays compares identity, so
// == / != need an explicit structural comparison to stay in parity.
function equalValues(left, right) {
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right)) return false;
    return left.length === right.length && left.every((item, i) => item === right[i]);
  }
  return left === right;
}

// How far the documented value is from clearing this predicate. Used only as
// the final tie-break between equally shallow blocking candidates.
export function requiredDelta(predicate, factValue) {
  const op = predicate.op;
  if (op !== '>=' && op !== '<=') return NO_DELTA;
  if (!isNumber(factValue)) return NO_DELTA;
  if (op === '>=') return Math.max(0, predicate.value - factValue);
  return Math.max(0, factValue - predicate.value);
}

// ---------------------------------------------------------------------------
// tree walk
// ---------------------------------------------------------------------------

function combine(nodeType, childStates, n) {
  if (nodeType === 'AND') {
    if (childStates.includes(FALSE)) return FALSE;
    if (childStates.includes(UNKNOWN)) return UNKNOWN;
    return TRUE;
  }
  if (nodeType === 'OR') {
    if (childStates.includes(TRUE)) return TRUE;
    if (childStates.includes(UNKNOWN)) return UNKNOWN;
    return FALSE;
  }
  if (nodeType === 'NOT') {
    const child = childStates[0];
    if (child === TRUE) return FALSE;
    if (child === FALSE) return TRUE;
    return UNKNOWN;
  }
  if (nodeType === 'N_OF') {
    const threshold = n || 0;
    const trueCount = childStates.filter((state) => state === TRUE).length;
    const unknownCount = childStates.filter((state) => state === UNKNOWN).length;
    if (trueCount >= threshold) return TRUE;
    if (trueCount + unknownCount < threshold) return FALSE;
    return UNKNOWN;
  }
  throw new Error(`unknown node type ${nodeType}`);
}

// Shortest distance from the root, breadth-first.
export function depths(nodes, root) {
  const result = { [root]: 0 };
  const queue = [root];
  while (queue.length) {
    const current = queue.shift();
    for (const child of nodes[current].children || []) {
      if (child in result || !(child in nodes)) continue;
      result[child] = result[current] + 1;
      queue.push(child);
    }
  }
  return result;
}

// Children before parents, iteratively.
function postOrder(nodes, root) {
  const order = [];
  const seen = new Set();
  const stack = [[root, false]];
  while (stack.length) {
    const [nodeId, expanded] = stack.pop();
    if (expanded) {
      order.push(nodeId);
      continue;
    }
    if (seen.has(nodeId) || !(nodeId in nodes)) continue;
    seen.add(nodeId);
    stack.push([nodeId, true]);
    const children = nodes[nodeId].children || [];
    for (let i = children.length - 1; i >= 0; i -= 1) stack.push([children[i], false]);
  }
  return order;
}

export function formatValue(value, unit) {
  let text;
  if (typeof value === 'boolean') text = value ? 'yes' : 'no';
  else if (Array.isArray(value)) text = value.join(', ');
  else text = String(value);
  return unit ? `${text} ${unit}` : text;
}

const OP_WORDS = {
  '>=': 'at least',
  '<=': 'at most',
  '==': 'exactly',
  '!=': 'anything other than',
  includes: 'must include',
  excludes: 'must not include',
};

function reasonText(predicate, fact) {
  const needed = `${OP_WORDS[predicate.op]} ${formatValue(predicate.value, predicate.unit)}`;
  if (!fact) return `not documented; policy requires ${needed}`;
  const observed = formatValue(fact.value, fact.unit || predicate.unit);
  return `documented ${observed}; policy requires ${needed}`;
}

// Walk the tree once and return node states plus leaf bindings. `overrides`
// forces a node into a given state before it propagates upward; that is how the
// counterfactual flips behind blocking-clause selection are done. Selection
// lives in evaluate(), never here, so a flip cannot re-enter selection.
export function propagate(policy, facts, overrides) {
  const nodes = policy.nodes;
  const root = policy.root;
  const forced = overrides || {};
  const factsByKey = {};
  for (const fact of facts) factsByKey[fact.key] = fact;

  const states = {};
  const bindings = [];

  for (const nodeId of postOrder(nodes, root)) {
    const node = nodes[nodeId];
    let state;
    if (node.type === 'LEAF') {
      const fact = factsByKey[node.predicate.key];
      state = fact === undefined ? UNKNOWN : applyPredicate(node.predicate, fact.value);
      bindings.push({
        node_id: nodeId,
        fact_key: node.predicate.key,
        state,
        reason: reasonText(node.predicate, fact),
      });
    } else {
      state = combine(node.type, node.children.map((child) => states[child]), node.n);
    }
    if (nodeId in forced) state = forced[nodeId];
    states[nodeId] = state;
  }

  return { states, bindings, root_state: states[root] };
}

// Full evaluation: states, bindings, decision, blocking clause, confidence.
export function evaluate(policy, facts) {
  const root = policy.root;
  const nodeDepths = depths(policy.nodes, root);
  const walk = propagate(policy, facts);
  const states = walk.states;
  const rootState = walk.root_state;

  const decision = { TRUE: 'APPROVE', FALSE: 'DENY', UNKNOWN: 'INDETERMINATE' }[rootState];
  const blockingNode = selectBlockingNode(policy, facts, states, nodeDepths);
  const scores = confidence(policy, states, nodeDepths, decision);

  return {
    policy_id: policy.policy_id,
    decision,
    root_state: rootState,
    states,
    depths: nodeDepths,
    bindings: walk.bindings.slice().sort((a, b) => (a.node_id < b.node_id ? -1 : a.node_id > b.node_id ? 1 : 0)),
    blocking_node: blockingNode,
    satisfaction: scores.satisfaction,
    confidence: scores.confidence,
    weight_true: scores.weight_true,
    weight_false: scores.weight_false,
    weight_unknown: scores.weight_unknown,
  };
}

// ---------------------------------------------------------------------------
// blocking clause selection
// ---------------------------------------------------------------------------

// Ordering key for one candidate leaf.
//   deltaFirst = false -> (state, depth, delta, id): the reported blocking
//     clause. Depth first, so a wrong indication outranks a therapy gap buried
//     three levels down.
//   deltaFirst = true  -> (state, delta, depth, id): choosing between the arms
//     of an OR, where depth is meaningless and the cheapest arm should win.
function leafKey(nodeId, nodes, states, nodeDepths, factsByKey, deltaFirst) {
  const node = nodes[nodeId];
  const state = states[nodeId];
  // Documented outcomes rank above documentation gaps. A leaf reached through a
  // NOT blocks while TRUE (the exclusion fired), so the test is "is this
  // documented", not "is this FALSE".
  const stateRank = state === UNKNOWN ? 1 : 0;
  const fact = factsByKey[node.predicate.key];
  const delta = fact ? requiredDelta(node.predicate, fact.value) : NO_DELTA;
  return deltaFirst
    ? [stateRank, delta, nodeDepths[nodeId] || 0, nodeId]
    : [stateRank, nodeDepths[nodeId] || 0, delta, nodeId];
}

// Lexicographic comparison of the tuple keys above, matching Python's tuple
// ordering (numbers numerically, the trailing id as a string).
function compareKeys(a, b) {
  for (let i = 0; i < a.length; i += 1) {
    const left = a[i];
    const right = b[i];
    if (left === right) continue;
    if (typeof left === 'string' || typeof right === 'string') {
      return String(left) < String(right) ? -1 : 1;
    }
    return left < right ? -1 : 1;
  }
  return 0;
}

// Leaves already satisfied inside a subtree — how much of this arm the note has
// already paid for.
function trueLeafCount(nodes, states, nodeId) {
  let count = 0;
  const stack = [nodeId];
  const seen = new Set();
  while (stack.length) {
    const current = stack.pop();
    if (seen.has(current) || !(current in nodes)) continue;
    seen.add(current);
    const node = nodes[current];
    if (node.type === 'LEAF') {
      if (states[current] === TRUE) count += 1;
    } else {
      stack.push(...(node.children || []));
    }
  }
  return count;
}

// Leaves that would have to change for nodeId to reach `want`.
//
// This walks down the failing paths instead of flipping leaves one at a time
// and asking whether the root moved. A flip test cannot see a case with two
// independent failures — neither flip alone changes the verdict — and those are
// precisely the cases that matter here.
//
// Where alternatives exist (OR, N_OF, and the child of a falsified AND) only the
// cheapest arm is descended into: fewer leaves to change, then more of the arm
// already satisfied, then the delta-first leaf key.
export function collectCandidates(policy, states, nodeDepths, factsByKey, nodeId, want) {
  const nodes = policy.nodes;
  if (states[nodeId] === want) return [];
  const node = nodes[nodeId];
  const nodeType = node.type;

  if (nodeType === 'LEAF') return [nodeId];

  const children = node.children || [];
  const descend = (childId, childWant) =>
    collectCandidates(policy, states, nodeDepths, factsByKey, childId, childWant);

  const branchCost = (childId, candidates) => {
    let best = [2, NO_DELTA, 0, ''];
    for (const leafId of candidates) {
      const key = leafKey(leafId, nodes, states, nodeDepths, factsByKey, true);
      if (compareKeys(key, best) < 0) best = key;
    }
    return [candidates.length, -trueLeafCount(nodes, states, childId), best, childId];
  };

  const compareCost = (a, b) => {
    if (a[0] !== b[0]) return a[0] - b[0];
    if (a[1] !== b[1]) return a[1] - b[1];
    const byKey = compareKeys(a[2], b[2]);
    if (byKey !== 0) return byKey;
    return a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0;
  };

  const cheapest = (pairs, take) => {
    const ranked = pairs
      .map((pair) => ({ pair, cost: branchCost(pair[0], pair[1]) }))
      .sort((a, b) => compareCost(a.cost, b.cost));
    const chosen = [];
    for (const entry of ranked.slice(0, Math.max(0, take))) {
      for (const leafId of entry.pair[1]) {
        if (!chosen.includes(leafId)) chosen.push(leafId);
      }
    }
    return chosen;
  };

  const union = (pairs) => cheapest(pairs, pairs.length);

  if (nodeType === 'NOT') return descend(children[0], want === TRUE ? FALSE : TRUE);

  if (nodeType === 'AND') {
    if (want === TRUE) {
      return union(children.filter((c) => states[c] !== TRUE).map((c) => [c, descend(c, TRUE)]));
    }
    return cheapest(children.filter((c) => states[c] !== FALSE).map((c) => [c, descend(c, FALSE)]), 1);
  }

  if (nodeType === 'OR') {
    if (want === TRUE) {
      return cheapest(children.filter((c) => states[c] !== TRUE).map((c) => [c, descend(c, TRUE)]), 1);
    }
    return union(children.filter((c) => states[c] !== FALSE).map((c) => [c, descend(c, FALSE)]));
  }

  if (nodeType === 'N_OF') {
    const n = node.n || 0;
    const trueCount = children.filter((c) => states[c] === TRUE).length;
    if (want === TRUE) {
      const pairs = children.filter((c) => states[c] !== TRUE).map((c) => [c, descend(c, TRUE)]);
      return cheapest(pairs, Math.max(0, n - trueCount));
    }
    const surplus = trueCount - (n - 1);
    if (surplus > 0) {
      const pairs = children.filter((c) => states[c] === TRUE).map((c) => [c, descend(c, FALSE)]);
      return cheapest(pairs, surplus);
    }
    return union(children.filter((c) => states[c] !== FALSE).map((c) => [c, descend(c, FALSE)]));
  }

  throw new Error(`unknown node type ${nodeType}`);
}

// Pick the single clause a reviewer should act on.
//
// Only leaves are candidates. An operator node is by construction shallower than
// every leaf beneath it, so allowing operator nodes would make the answer a
// depth-1 AND on every case — true, and useless to a reviewer.
//
// Ranking: FALSE before UNKNOWN, then shallowest, then smallest required delta,
// then node id for determinism.
export function selectBlockingNode(policy, facts, states, nodeDepths) {
  const root = policy.root;
  if (states[root] === TRUE) return null;

  const nodes = policy.nodes;
  const factsByKey = {};
  for (const fact of facts) factsByKey[fact.key] = fact;

  const candidates = collectCandidates(policy, states, nodeDepths, factsByKey, root, TRUE)
    .filter((leafId) => leafId in nodeDepths);
  if (!candidates.length) return null;

  let best = null;
  let bestKey = null;
  for (const leafId of candidates) {
    const key = leafKey(leafId, nodes, states, nodeDepths, factsByKey, false);
    if (bestKey === null || compareKeys(key, bestKey) < 0) {
      best = leafId;
      bestKey = key;
    }
  }
  return best;
}

// ---------------------------------------------------------------------------
// confidence — rule-derived, not calibrated against payer outcomes
// ---------------------------------------------------------------------------

// Each leaf carries weight w = 1 / (1 + depth), so a criterion that gates a
// whole branch counts for more than one buried inside an alternative. With
// S, F, U the shares of leaf weight that are TRUE, FALSE and UNKNOWN:
//
//   satisfaction = clamp(S - 0.5 * U, 0, 1)
//   APPROVE       -> satisfaction
//   DENY          -> 1 - U
//   INDETERMINATE -> 0.5 + 0.5 * U
export function confidence(policy, states, nodeDepths, decision) {
  const nodes = policy.nodes;
  let total = 0;
  let weightTrue = 0;
  let weightFalse = 0;
  let weightUnknown = 0;

  for (const nodeId of Object.keys(nodes)) {
    if (nodes[nodeId].type !== 'LEAF' || !(nodeId in nodeDepths)) continue;
    const weight = 1 / (1 + nodeDepths[nodeId]);
    total += weight;
    const state = states[nodeId];
    if (state === TRUE) weightTrue += weight;
    else if (state === FALSE) weightFalse += weight;
    else weightUnknown += weight;
  }

  if (total === 0) {
    return { satisfaction: 0, confidence: 0, weight_true: 0, weight_false: 0, weight_unknown: 0 };
  }

  const shareTrue = weightTrue / total;
  const shareFalse = weightFalse / total;
  const shareUnknown = weightUnknown / total;
  const satisfaction = Math.min(1, Math.max(0, shareTrue - 0.5 * shareUnknown));

  let value;
  if (decision === 'APPROVE') value = satisfaction;
  else if (decision === 'DENY') value = 1 - shareUnknown;
  else value = 0.5 + 0.5 * shareUnknown;

  return {
    satisfaction: round4(satisfaction),
    confidence: round4(Math.min(1, Math.max(0, value))),
    weight_true: round4(shareTrue),
    weight_false: round4(shareFalse),
    weight_unknown: round4(shareUnknown),
  };
}
