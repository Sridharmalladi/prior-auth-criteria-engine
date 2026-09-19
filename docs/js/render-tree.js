// Inline SVG rendering of a criteria tree.
//
// Layout is a plain tidy-tree: leaves take successive horizontal slots in
// depth-first order, an operator node sits at the mean x of its children, and
// depth sets the row. The trees here are tens of nodes, so nothing cleverer
// earns its complexity.

const SVG_NS = 'http://www.w3.org/2000/svg';

const NODE_W = 168;
const NODE_H = 46;
const SLOT_W = 184;
const ROW_H = 84;
const PAD = 16;
const CHARS_PER_LINE = 27;

function el(name, attrs, text) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

// Two lines maximum, broken on word boundaries, ellipsis if it still overflows.
function wrap(label) {
  const words = label.split(/\s+/);
  const lines = [];
  let current = '';
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > CHARS_PER_LINE && current) {
      lines.push(current);
      current = word;
      if (lines.length === 2) break;
    } else {
      current = candidate;
    }
  }
  if (lines.length < 2 && current) lines.push(current);
  if (lines.length === 2) {
    const consumed = lines.join(' ').length;
    if (consumed < label.length - 1) {
      lines[1] = `${lines[1].slice(0, CHARS_PER_LINE - 1)}…`;
    }
  }
  return lines;
}

function operatorCaption(node) {
  if (node.type === 'N_OF') return `${node.n} OF ${node.children.length}`;
  if (node.type === 'LEAF') return node.predicate.key;
  return node.type;
}

// Depth-first layout. Returns {positions, width, height}.
export function layout(policy) {
  const nodes = policy.nodes;
  const positions = {};
  let slot = 0;

  const place = (nodeId, depth) => {
    const node = nodes[nodeId];
    const children = node.children || [];
    let x;
    if (!children.length) {
      x = slot * SLOT_W + SLOT_W / 2;
      slot += 1;
    } else {
      const childXs = children.map((child) => place(child, depth + 1));
      x = (Math.min(...childXs) + Math.max(...childXs)) / 2;
    }
    positions[nodeId] = { x, y: depth * ROW_H, depth };
    return x;
  };

  place(policy.root, 0);
  const maxDepth = Math.max(...Object.values(positions).map((position) => position.depth));
  return {
    positions,
    width: slot * SLOT_W + PAD * 2,
    height: (maxDepth + 1) * ROW_H + PAD * 2,
  };
}

// Draw the tree. `options` carries the evaluation result and the interaction
// callbacks; everything visual is derived from it, so a re-render after an edit
// is a full redraw and there is no partial-update path to get out of sync.
export function renderTree(svg, policy, result, options) {
  const settings = options || {};
  const { positions, width, height } = layout(policy);
  const nodes = policy.nodes;

  svg.textContent = '';
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);

  const offset = (position) => ({ x: position.x + PAD, y: position.y + PAD });

  // edges first, so boxes sit on top
  const edgeLayer = el('g', {});
  svg.appendChild(edgeLayer);
  for (const [nodeId, node] of Object.entries(nodes)) {
    if (!positions[nodeId]) continue;
    const parent = offset(positions[nodeId]);
    for (const childId of node.children || []) {
      if (!positions[childId]) continue;
      const child = offset(positions[childId]);
      const midY = parent.y + NODE_H + (ROW_H - NODE_H) / 2;
      const path = `M ${parent.x} ${parent.y + NODE_H} V ${midY} H ${child.x} V ${child.y}`;
      const classes = ['edge'];
      // Mark the path down to the blocking clause so the eye lands on it.
      if (settings.pathToBlocking && settings.pathToBlocking.has(childId)) classes.push('on-path');
      edgeLayer.appendChild(el('path', { d: path, class: classes.join(' ') }));
    }
  }

  for (const [nodeId, node] of Object.entries(nodes)) {
    const position = positions[nodeId];
    if (!position) continue;
    const { x, y } = offset(position);
    const state = result.states[nodeId] || 'UNKNOWN';
    const classes = ['node-box', `state-${state}`];
    if (nodeId === result.blocking_node) classes.push('blocking');
    if (nodeId === settings.selectedNode) classes.push('selected');
    if (settings.linkedNodes && settings.linkedNodes.has(nodeId)) classes.push('linked');

    const group = el('g', {
      class: classes.join(' '),
      tabindex: '0',
      role: 'button',
      'aria-label': `${node.label}. State ${state}.`,
      transform: `translate(${x - NODE_W / 2}, ${y})`,
    });

    group.appendChild(el('rect', { width: NODE_W, height: NODE_H }));

    const lines = wrap(node.label);
    lines.forEach((line, index) => {
      group.appendChild(el('text', { x: 8, y: 15 + index * 12 }, line));
    });
    group.appendChild(el('text', {
      x: 8,
      y: NODE_H - 7,
      class: 'node-sub',
    }, operatorCaption(node)));

    const tooltip = el('title', {});
    tooltip.textContent = `${node.label} — ${state}`;
    group.appendChild(tooltip);

    if (settings.onSelect) {
      group.addEventListener('click', () => settings.onSelect(nodeId));
      group.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          settings.onSelect(nodeId);
        }
      });
    }
    if (settings.onHover) {
      group.addEventListener('mouseenter', () => settings.onHover(nodeId));
      group.addEventListener('mouseleave', () => settings.onHover(null));
    }

    svg.appendChild(group);
  }
}

// Every node on the path from the root down to the blocking clause.
export function pathToNode(policy, targetId) {
  const parents = {};
  for (const [nodeId, node] of Object.entries(policy.nodes)) {
    for (const child of node.children || []) parents[child] = nodeId;
  }
  const path = new Set();
  let current = targetId;
  while (current) {
    path.add(current);
    current = parents[current];
  }
  return path;
}
