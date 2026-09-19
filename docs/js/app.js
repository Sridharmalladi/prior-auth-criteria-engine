// Wires the three panes together.
//
// One rule governs this file: every visible number comes from evaluator.js,
// evaluated in the browser on the facts currently shown. Nothing is read from a
// precomputed result, so an edited chip and the verdict can never disagree.

import { evaluate, formatValue } from './evaluator.js';
import { renderTree, pathToNode } from './render-tree.js';
import { initLiveMode } from './live.js';

const REPO_URL = 'https://github.com/Sridharmalladi/prior-auth-criteria-engine';

const dom = {
  status: document.getElementById('status'),
  panes: document.getElementById('panes'),
  caseSelect: document.getElementById('case-select'),
  resetButton: document.getElementById('reset-case'),
  policyBadge: document.getElementById('policy-badge'),
  editedBadge: document.getElementById('edited-badge'),
  tree: document.getElementById('tree'),
  nodeDetail: document.getElementById('node-detail'),
  note: document.getElementById('note'),
  chips: document.getElementById('chips'),
  verdict: document.getElementById('verdict'),
  blocking: document.getElementById('blocking'),
  criteria: document.getElementById('criteria'),
  repoLink: document.getElementById('repo-link'),
};

const state = {
  manifest: null,
  policy: null,
  case: null,
  facts: new Map(),      // fact key -> fact object; absent key means UNKNOWN
  originalFacts: new Map(),
  selectedNode: null,
  hoveredKey: null,
  result: null,
};

const cacheOfPolicies = new Map();

async function loadJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// policy introspection: what can this key hold, and which leaves use it
// ---------------------------------------------------------------------------

function leafOrder(policy) {
  const order = [];
  const walk = (nodeId) => {
    const node = policy.nodes[nodeId];
    if (!node) return;
    if (node.type === 'LEAF') order.push(nodeId);
    else (node.children || []).forEach(walk);
  };
  walk(policy.root);
  return order;
}

function keyProfiles(policy) {
  // One entry per fact key the policy can consume, in tree order, carrying the
  // predicates that read it so the editor can offer the right control.
  const profiles = new Map();
  for (const nodeId of leafOrder(policy)) {
    const node = policy.nodes[nodeId];
    const key = node.predicate.key;
    if (!profiles.has(key)) {
      profiles.set(key, { key, leaves: [], unit: node.predicate.unit, kind: null, options: new Set() });
    }
    const profile = profiles.get(key);
    profile.leaves.push(nodeId);
    profile.unit = profile.unit || node.predicate.unit;

    const { op, value } = node.predicate;
    if (op === '>=' || op === '<=') profile.kind = profile.kind || 'number';
    else if (typeof value === 'boolean') profile.kind = profile.kind || 'boolean';
    else if (Array.isArray(value)) {
      profile.kind = 'list';
      value.forEach((item) => profile.options.add(item));
    } else if (typeof value === 'number') profile.kind = profile.kind || 'number';
    else {
      profile.kind = profile.kind === 'list' ? 'list' : 'string';
      profile.options.add(value);
    }
  }
  return profiles;
}

function defaultValueFor(profile, policy) {
  // Used when a reviewer documents a fact that the note left out. The default is
  // whatever the first predicate reading this key asks for, so "document this"
  // starts from the satisfying value rather than an arbitrary one.
  const node = policy.nodes[profile.leaves[0]];
  const { op, value } = node.predicate;
  if (op === '>=' || op === '<=') return value;
  if (Array.isArray(value)) return value.slice();
  return value;
}

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------

function factList() {
  return Array.from(state.facts.values());
}

function recompute() {
  state.result = evaluate(state.policy, factList());
}

function linkedNodesForKey(key) {
  const linked = new Set();
  if (!key) return linked;
  for (const [nodeId, node] of Object.entries(state.policy.nodes)) {
    if (node.type === 'LEAF' && node.predicate.key === key) linked.add(nodeId);
  }
  return linked;
}

function renderNote() {
  const note = state.case.note_text;
  // Highlights come from the case's own spans. Edited values keep the span they
  // were extracted from; a fact added by hand has no span and no highlight.
  const spans = [];
  for (const fact of state.originalFacts.values()) {
    if (!fact.source_span) continue;
    if (!state.facts.has(fact.key)) continue;
    spans.push({ start: fact.source_span[0], end: fact.source_span[1], key: fact.key });
  }
  spans.sort((a, b) => a.start - b.start);

  dom.note.textContent = '';
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // overlapping evidence: keep the first
    dom.note.appendChild(document.createTextNode(note.slice(cursor, span.start)));
    const mark = document.createElement('mark');
    mark.textContent = note.slice(span.start, span.end);
    const leafId = (state.policy.nodes[linkedNodesForKey(span.key).values().next().value] || {}).id;
    const leafState = leafId ? state.result.states[leafId] : 'UNKNOWN';
    mark.className = `state-${leafState}${state.hoveredKey === span.key ? ' linked' : ''}`;
    mark.title = span.key;
    mark.addEventListener('mouseenter', () => setHovered(span.key));
    mark.addEventListener('mouseleave', () => setHovered(null));
    dom.note.appendChild(mark);
    cursor = span.end;
  }
  dom.note.appendChild(document.createTextNode(note.slice(cursor)));
}

function chipStateFor(profile) {
  // A key can feed several leaves; show the state of the first one that is not
  // satisfied, since that is the one a reviewer cares about.
  const states = profile.leaves.map((leafId) => state.result.states[leafId]);
  if (states.includes('FALSE')) return 'FALSE';
  if (states.includes('UNKNOWN')) return 'UNKNOWN';
  return 'TRUE';
}

function renderChips() {
  const profiles = keyProfiles(state.policy);
  dom.chips.textContent = '';

  for (const profile of profiles.values()) {
    const fact = state.facts.get(profile.key);
    const original = state.originalFacts.get(profile.key);
    const chip = document.createElement('div');
    const chipState = chipStateFor(profile);
    chip.className = `chip state-${chipState}${fact ? '' : ' missing'}${state.hoveredKey === profile.key ? ' linked' : ''}`;
    chip.addEventListener('mouseenter', () => setHovered(profile.key));
    chip.addEventListener('mouseleave', () => setHovered(null));

    const keyLine = document.createElement('div');
    keyLine.className = 'key';
    keyLine.textContent = profile.key + (profile.unit ? ` (${profile.unit})` : '');
    chip.appendChild(keyLine);

    const row = document.createElement('div');
    row.className = 'row';

    if (!fact) {
      const missing = document.createElement('span');
      missing.textContent = 'not documented';
      row.appendChild(missing);
      const document_it = document.createElement('button');
      document_it.type = 'button';
      document_it.textContent = 'Document this';
      document_it.addEventListener('click', () => {
        setFact(profile.key, defaultValueFor(profile, state.policy), profile.unit, original);
      });
      row.appendChild(document_it);
    } else {
      row.appendChild(buildEditor(profile, fact));
      const unknownButton = document.createElement('button');
      unknownButton.type = 'button';
      unknownButton.textContent = 'Mark unknown';
      unknownButton.addEventListener('click', () => {
        state.facts.delete(profile.key);
        render();
      });
      row.appendChild(unknownButton);
    }

    if (original && fact && JSON.stringify(original.value) !== JSON.stringify(fact.value)) {
      const edited = document.createElement('span');
      edited.className = 'edited';
      edited.textContent = `edited from ${formatValue(original.value, original.unit)}`;
      row.appendChild(edited);
    } else if (original && !fact) {
      const edited = document.createElement('span');
      edited.className = 'edited';
      edited.textContent = 'cleared';
      row.appendChild(edited);
    }

    chip.appendChild(row);
    dom.chips.appendChild(chip);
  }
}

function buildEditor(profile, fact) {
  const wrapper = document.createElement('span');
  wrapper.className = 'row';

  if (profile.kind === 'number') {
    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.value = String(fact.value);
    input.setAttribute('aria-label', profile.key);
    input.addEventListener('input', () => {
      const parsed = Number(input.value);
      if (Number.isFinite(parsed)) setFact(profile.key, parsed, fact.unit, fact, true);
    });
    wrapper.appendChild(input);
  } else if (profile.kind === 'boolean') {
    const select = document.createElement('select');
    select.setAttribute('aria-label', profile.key);
    for (const [label, value] of [['yes', true], ['no', false]]) {
      const option = document.createElement('option');
      option.value = String(value);
      option.textContent = label;
      option.selected = fact.value === value;
      select.appendChild(option);
    }
    select.addEventListener('change', () => setFact(profile.key, select.value === 'true', fact.unit, fact));
    wrapper.appendChild(select);
  } else if (profile.kind === 'list') {
    const options = new Set([...profile.options, ...(Array.isArray(fact.value) ? fact.value : [])]);
    for (const item of options) {
      const label = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = Array.isArray(fact.value) && fact.value.includes(item);
      checkbox.addEventListener('change', () => {
        const current = new Set(Array.isArray(fact.value) ? fact.value : []);
        if (checkbox.checked) current.add(item); else current.delete(item);
        setFact(profile.key, Array.from(current), fact.unit, fact);
      });
      label.appendChild(checkbox);
      label.appendChild(document.createTextNode(` ${item}`));
      wrapper.appendChild(label);
    }
  } else {
    const select = document.createElement('select');
    select.setAttribute('aria-label', profile.key);
    const options = new Set([...profile.options, fact.value]);
    for (const item of options) {
      const option = document.createElement('option');
      option.value = String(item);
      option.textContent = String(item);
      option.selected = fact.value === item;
      select.appendChild(option);
    }
    select.addEventListener('change', () => setFact(profile.key, select.value, fact.unit, fact));
    wrapper.appendChild(select);
  }

  return wrapper;
}

function setFact(key, value, unit, source, keepFocus) {
  const previous = state.facts.get(key) || source || {};
  state.facts.set(key, {
    key,
    value,
    unit: unit === undefined ? previous.unit : unit,
    confidence: previous.confidence === undefined ? 1 : previous.confidence,
    source_span: previous.source_span,
    evidence_text: previous.evidence_text,
  });
  render(keepFocus);
}

function renderVerdict() {
  const result = state.result;
  dom.verdict.className = `verdict ${result.decision}`;
  dom.verdict.textContent = '';

  const decision = document.createElement('div');
  decision.className = 'decision';
  decision.textContent = {
    APPROVE: 'Criteria satisfied',
    DENY: 'Criteria not satisfied',
    INDETERMINATE: 'Cannot determine',
  }[result.decision];
  dom.verdict.appendChild(decision);

  const confidence = document.createElement('div');
  confidence.className = 'confidence';
  confidence.textContent =
    `Rule-derived confidence ${(result.confidence * 100).toFixed(0)}% · ` +
    `criteria satisfaction ${(result.satisfaction * 100).toFixed(0)}% · ` +
    `${(result.weight_unknown * 100).toFixed(0)}% of criteria weight undocumented`;
  dom.verdict.appendChild(confidence);

  const caveat = document.createElement('div');
  caveat.className = 'confidence';
  caveat.textContent = 'Not a probability of denial. Derived from the tree by a published formula.';
  dom.verdict.appendChild(caveat);

  renderBlocking();
  renderCriteriaList();
}

function deltaSentence(nodeId) {
  const node = state.policy.nodes[nodeId];
  const predicate = node.predicate;
  const fact = state.facts.get(predicate.key);
  const required = formatValue(predicate.value, predicate.unit);
  if (!fact) return `Requires ${required}; not documented.`;
  const documented = formatValue(fact.value, fact.unit || predicate.unit);
  if (predicate.op === '>=') return `Requires ≥ ${required}; documented ${documented}.`;
  if (predicate.op === '<=') return `Requires ≤ ${required}; documented ${documented}.`;
  if (predicate.op === '==') return `Requires ${required}; documented ${documented}.`;
  if (predicate.op === '!=') return `Must not be ${required}; documented ${documented}.`;
  if (predicate.op === 'includes') return `Must include ${required}; documented ${documented}.`;
  return `Must exclude ${required}; documented ${documented}.`;
}

function renderBlocking() {
  const result = state.result;
  dom.blocking.textContent = '';
  if (!result.blocking_node) {
    dom.blocking.textContent = 'Every criterion in this policy is satisfied by the documented facts.';
    return;
  }
  const node = state.policy.nodes[result.blocking_node];
  const heading = document.createElement('div');
  heading.innerHTML = '<strong>Blocking clause</strong>';
  dom.blocking.appendChild(heading);

  const label = document.createElement('div');
  label.textContent = node.label;
  dom.blocking.appendChild(label);

  const delta = document.createElement('div');
  delta.className = 'delta';
  delta.textContent = deltaSentence(result.blocking_node);
  dom.blocking.appendChild(delta);

  const source = document.createElement('div');
  const link = document.createElement('a');
  link.href = node.source_ref.url;
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = node.source_ref.section;
  source.appendChild(document.createTextNode('Source: '));
  source.appendChild(link);
  dom.blocking.appendChild(source);
}

function renderCriteriaList() {
  dom.criteria.textContent = '';
  const bindingByNode = new Map(state.result.bindings.map((binding) => [binding.node_id, binding]));
  for (const nodeId of leafOrder(state.policy)) {
    const node = state.policy.nodes[nodeId];
    const binding = bindingByNode.get(nodeId);
    const item = document.createElement('li');

    const dot = document.createElement('span');
    dot.className = `dot state-${state.result.states[nodeId]}`;
    item.appendChild(dot);

    const text = document.createElement('div');
    const label = document.createElement('div');
    label.textContent = node.label;
    text.appendChild(label);
    const reason = document.createElement('div');
    reason.className = 'reason';
    reason.textContent = binding ? binding.reason : '';
    text.appendChild(reason);
    item.appendChild(text);

    item.addEventListener('mouseenter', () => setHovered(node.predicate.key));
    item.addEventListener('mouseleave', () => setHovered(null));
    dom.criteria.appendChild(item);
  }
}

function renderNodeDetail() {
  dom.nodeDetail.textContent = '';
  const nodeId = state.selectedNode;
  if (!nodeId) {
    const hint = document.createElement('span');
    hint.className = 'muted';
    hint.textContent = 'Select a node to see the clause it came from.';
    dom.nodeDetail.appendChild(hint);
    return;
  }
  const node = state.policy.nodes[nodeId];
  const title = document.createElement('div');
  title.innerHTML = `<strong>${escapeHTML(node.label)}</strong> — ${state.result.states[nodeId]}`;
  dom.nodeDetail.appendChild(title);

  const detail = document.createElement('div');
  detail.className = 'muted';
  detail.textContent = node.type === 'LEAF'
    ? `${node.predicate.key} ${node.predicate.op} ${formatValue(node.predicate.value, node.predicate.unit)}`
    : `${node.type} over ${node.children.length} child criteria${node.type === 'N_OF' ? `, ${node.n} required` : ''}`;
  dom.nodeDetail.appendChild(detail);

  const source = document.createElement('div');
  source.className = 'muted';
  const link = document.createElement('a');
  link.href = node.source_ref.url;
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = `${node.source_ref.section} — view on CMS`;
  source.appendChild(link);
  dom.nodeDetail.appendChild(source);
}

function escapeHTML(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function setHovered(key) {
  state.hoveredKey = key;
  renderNote();
  renderChips();
  renderTreePane();
}

function renderTreePane() {
  renderTree(dom.tree, state.policy, state.result, {
    selectedNode: state.selectedNode,
    linkedNodes: linkedNodesForKey(state.hoveredKey),
    pathToBlocking: state.result.blocking_node ? pathToNode(state.policy, state.result.blocking_node) : new Set(),
    onSelect: (nodeId) => {
      state.selectedNode = nodeId;
      renderTreePane();
      renderNodeDetail();
    },
    onHover: (nodeId) => {
      const node = nodeId ? state.policy.nodes[nodeId] : null;
      setHovered(node && node.type === 'LEAF' ? node.predicate.key : null);
    },
  });
}

function renderEditedBadge() {
  let changed = 0;
  const keys = new Set([...state.facts.keys(), ...state.originalFacts.keys()]);
  for (const key of keys) {
    const before = state.originalFacts.get(key);
    const after = state.facts.get(key);
    if (JSON.stringify(before && before.value) !== JSON.stringify(after && after.value)) changed += 1;
  }
  dom.editedBadge.textContent = '';
  if (changed) {
    const badge = document.createElement('span');
    badge.className = 'badge warn';
    badge.textContent = `${changed} fact${changed === 1 ? '' : 's'} edited`;
    dom.editedBadge.appendChild(badge);
  }
}

// A full redraw on every edit. The trees are small enough that this is well
// inside a frame, which is why there is no loading state anywhere in the UI.
function render(keepFocus) {
  const active = keepFocus ? document.activeElement : null;
  const activeKey = active && active.getAttribute ? active.getAttribute('aria-label') : null;
  const selectionStart = active && active.selectionStart;

  recompute();
  renderNote();
  renderChips();
  renderTreePane();
  renderVerdict();
  renderNodeDetail();
  renderEditedBadge();

  if (activeKey) {
    const restored = dom.chips.querySelector(`[aria-label="${CSS.escape(activeKey)}"]`);
    if (restored) {
      restored.focus();
      if (selectionStart !== null && restored.setSelectionRange) {
        try { restored.setSelectionRange(selectionStart, selectionStart); } catch (error) { /* non-text input */ }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// loading
// ---------------------------------------------------------------------------

async function loadPolicy(policyId) {
  if (!cacheOfPolicies.has(policyId)) {
    cacheOfPolicies.set(policyId, await loadJSON(`data/policies/${policyId}.json`));
  }
  return cacheOfPolicies.get(policyId);
}

async function selectCase(caseId) {
  const caseData = await loadJSON(`data/cases/${caseId}.json`);
  const policy = await loadPolicy(caseData.policy_id);
  state.case = caseData;
  state.policy = policy;
  state.selectedNode = null;
  state.hoveredKey = null;
  state.originalFacts = new Map(caseData.facts.map((fact) => [fact.key, fact]));
  state.facts = new Map(caseData.facts.map((fact) => [fact.key, Object.assign({}, fact)]));

  dom.policyBadge.textContent = '';
  const badge = document.createElement('span');
  badge.className = `badge${policy.verification === 'unverified-paraphrase' ? ' warn' : ''}`;
  badge.textContent = `${policy.source_type} · ${policy.title}`;
  badge.title = policy.verification === 'unverified-paraphrase'
    ? 'Paraphrased from a licence-gated LCD; thresholds are illustrative and unverified.'
    : 'Written from the fetched NCD text.';
  dom.policyBadge.appendChild(badge);

  render();
}

async function main() {
  dom.repoLink.href = REPO_URL;
  try {
    state.manifest = await loadJSON('data/manifest.json');
  } catch (error) {
    dom.status.className = 'status error';
    dom.status.textContent =
      `Could not load data/manifest.json (${error.message}). ` +
      'Serve this directory over HTTP — for example "python3 -m http.server" from docs/ — rather than opening the file directly.';
    return;
  }

  for (const entry of state.manifest.cases) {
    const option = document.createElement('option');
    option.value = entry.case_id;
    option.textContent = `${entry.title} — expected ${entry.gold_decision.toLowerCase()}`;
    dom.caseSelect.appendChild(option);
  }

  dom.caseSelect.addEventListener('change', () => selectCase(dom.caseSelect.value));
  dom.resetButton.addEventListener('click', () => selectCase(state.case.case_id));

  await selectCase(state.manifest.cases[0].case_id);
  dom.status.hidden = true;
  dom.panes.hidden = false;

  initLiveMode({
    container: document.getElementById('live-body'),
    manifest: state.manifest,
    loadPolicy,
    onResult: ({ policy, facts, note, title }) => {
      state.policy = policy;
      state.case = { case_id: 'live', policy_id: policy.policy_id, title, note_text: note, facts };
      state.originalFacts = new Map(facts.map((fact) => [fact.key, fact]));
      state.facts = new Map(facts.map((fact) => [fact.key, Object.assign({}, fact)]));
      state.selectedNode = null;
      render();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },
  });
}

main();
