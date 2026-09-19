// The evaluation page: four inline-SVG charts and a failure table.
//
// No chart library. Everything is drawn from data/eval/metrics.json, which is
// written by pipeline/run_eval.py. Where the baseline has not been run, the
// chart says so rather than showing a placeholder number.

const SVG_NS = 'http://www.w3.org/2000/svg';

const COLOURS = { structured: 'bar-structured', baseline: 'bar-baseline' };

function el(name, attrs, text) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgRoot(width, height) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'xMidYMid meet' });
  svg.setAttribute('role', 'img');
  return svg;
}

function percentAxis(svg, box) {
  const axis = el('g', { class: 'axis' });
  const grid = el('g', { class: 'grid' });
  for (let value = 0; value <= 100; value += 25) {
    const y = box.top + box.height * (1 - value / 100);
    grid.appendChild(el('line', { x1: box.left, x2: box.left + box.width, y1: y, y2: y }));
    axis.appendChild(el('text', { x: box.left - 8, y: y + 3.5, 'text-anchor': 'end' }, `${value}%`));
  }
  axis.appendChild(el('line', {
    x1: box.left, x2: box.left + box.width,
    y1: box.top + box.height, y2: box.top + box.height,
  }));
  svg.appendChild(grid);
  svg.appendChild(axis);
}

// Grouped bars: one group per metric, one bar per system.
export function groupedBar(container, { groups, systems, label }) {
  const width = 460;
  const height = 240;
  const box = { left: 46, top: 14, width: 390, height: 168 };
  const svg = svgRoot(width, height);
  svg.setAttribute('aria-label', label);
  percentAxis(svg, box);

  const groupWidth = box.width / groups.length;
  const barWidth = Math.min(46, (groupWidth - 18) / Math.max(systems.length, 1));

  groups.forEach((group, groupIndex) => {
    const centre = box.left + groupWidth * (groupIndex + 0.5);
    systems.forEach((system, systemIndex) => {
      const value = group.values[system.key];
      const x = centre - (systems.length * barWidth) / 2 + systemIndex * barWidth;
      if (value === null || value === undefined) {
        svg.appendChild(el('text', {
          x: x + barWidth / 2, y: box.top + box.height - 6,
          'text-anchor': 'middle', class: 'series-label',
        }, 'not run'));
        return;
      }
      const barHeight = box.height * value;
      svg.appendChild(el('rect', {
        x, y: box.top + box.height - barHeight,
        width: barWidth - 4, height: barHeight,
        class: COLOURS[system.key] || 'bar-structured',
      }));
      svg.appendChild(el('text', {
        x: x + (barWidth - 4) / 2, y: box.top + box.height - barHeight - 5,
        'text-anchor': 'middle', class: 'bar-value',
      }, `${Math.round(value * 100)}%`));
      if (group.counts && group.counts[system.key]) {
        svg.appendChild(el('text', {
          x: x + (barWidth - 4) / 2, y: box.top + box.height + 26,
          'text-anchor': 'middle', class: 'series-label',
        }, group.counts[system.key]));
      }
    });
    svg.appendChild(el('text', {
      x: centre, y: box.top + box.height + 15,
      'text-anchor': 'middle', class: 'series-label',
    }, group.label));
  });

  legend(svg, systems, box);
  container.appendChild(svg);
}

function legend(svg, systems, box) {
  const group = el('g', {});
  systems.forEach((system, index) => {
    const x = box.left + index * 118;
    const y = box.top + box.height + 44;
    group.appendChild(el('rect', { x, y: y - 8, width: 10, height: 10, class: COLOURS[system.key] }));
    group.appendChild(el('text', { x: x + 15, y, class: 'series-label' }, system.label));
  });
  svg.appendChild(group);
}

// Calibration: predicted confidence against observed accuracy, plus the diagonal.
export function calibrationChart(container, { systems, label }) {
  const width = 460;
  const height = 260;
  const box = { left: 46, top: 14, width: 380, height: 180 };
  const svg = svgRoot(width, height);
  svg.setAttribute('aria-label', label);
  percentAxis(svg, box);

  const toX = (value) => box.left + box.width * value;
  const toY = (value) => box.top + box.height * (1 - value);

  svg.appendChild(el('path', {
    d: `M ${toX(0)} ${toY(0)} L ${toX(1)} ${toY(1)}`,
    class: 'line-diagonal',
  }));

  for (const system of systems) {
    const points = (system.bins || [])
      .filter((bin) => bin.count > 0 && bin.observed_accuracy !== null)
      .map((bin) => [toX(bin.mean_confidence), toY(bin.observed_accuracy)]);
    if (!points.length) continue;
    svg.appendChild(el('path', {
      d: points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' '),
      class: system.key === 'baseline' ? 'line-baseline' : 'line-structured',
    }));
    for (const [x, y] of points) {
      svg.appendChild(el('circle', { cx: x, cy: y, r: 3.5, class: COLOURS[system.key] }));
    }
  }

  svg.appendChild(el('text', {
    x: box.left + box.width / 2, y: box.top + box.height + 30,
    'text-anchor': 'middle', class: 'series-label',
  }, 'predicted confidence'));

  legend(svg, systems, box);
  container.appendChild(svg);
}

function card(title, note) {
  const section = document.createElement('section');
  section.className = 'chart-card';
  const heading = document.createElement('h3');
  heading.textContent = title;
  section.appendChild(heading);
  if (note) {
    const line = document.createElement('p');
    line.className = 'note-line';
    line.textContent = note;
    section.appendChild(line);
  }
  return section;
}

function systemsPresent(metrics) {
  const systems = [{ key: 'structured', label: 'Criteria graph' }];
  if (metrics.systems.baseline) systems.push({ key: 'baseline', label: 'Flat RAG baseline' });
  return systems;
}

function fraction(system, path) {
  if (!system) return null;
  const node = path === 'decision' ? system.decision : system.attribution;
  return node ? node.accuracy : null;
}

function counts(system, path) {
  if (!system) return null;
  const node = path === 'decision' ? system.decision : system.attribution;
  if (!node || node.total === 0) return null;
  return `${node.correct}/${node.total}`;
}

async function loadJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

function renderFailures(container, failures, metrics) {
  const table = document.createElement('table');
  table.className = 'failures';
  const head = document.createElement('thead');
  head.innerHTML =
    '<tr><th>Case</th><th>Kind</th><th>Expected</th><th>Produced</th><th>Diagnosis</th></tr>';
  table.appendChild(head);
  const body = document.createElement('tbody');

  if (!failures.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 5;
    cell.textContent = 'No failures recorded in this run.';
    row.appendChild(cell);
    body.appendChild(row);
  }

  for (const failure of failures) {
    const row = document.createElement('tr');
    const expected = failure.kind === 'decision' ? failure.gold_decision : failure.gold_blocking_node;
    const produced = failure.kind === 'decision' ? failure.predicted_decision : failure.predicted_blocking_node;
    for (const value of [failure.title, failure.kind, expected, produced]) {
      const cell = document.createElement('td');
      const code = document.createElement('code');
      code.textContent = value === null || value === undefined ? '—' : String(value);
      cell.appendChild(code);
      row.appendChild(cell);
    }
    const diagnosis = document.createElement('td');
    diagnosis.textContent = failure.diagnosis;
    row.appendChild(diagnosis);
    body.appendChild(row);
  }

  table.appendChild(body);
  container.appendChild(table);

  const line = document.createElement('p');
  line.className = 'note-line';
  line.textContent =
    `${failures.length} of ${metrics.n_cases} cases produced a wrong decision or cited the wrong clause. ` +
    'The full records are in data/eval/failures.json.';
  container.appendChild(line);
}

async function main() {
  const status = document.getElementById('status');
  let metrics;
  let failures;
  try {
    metrics = await loadJSON('data/eval/metrics.json');
    failures = await loadJSON('data/eval/failures.json');
  } catch (error) {
    status.className = 'status error';
    status.textContent =
      `Could not load the evaluation data (${error.message}). ` +
      'Run python3 pipeline/run_eval.py, then python3 pipeline/sync_docs_data.py, and serve this directory over HTTP.';
    return;
  }

  const charts = document.getElementById('charts');
  const systems = systemsPresent(metrics);
  const structured = metrics.systems.structured;
  const baseline = metrics.systems.baseline;

  const decisionCard = card(
    'Decision accuracy',
    `Three classes, n = ${metrics.n_cases}. Computed on hand-labelled gold facts, so this measures the tree logic, not extraction.`);
  groupedBar(decisionCard, {
    label: 'Decision accuracy by system',
    systems,
    groups: [{
      label: 'all cases',
      values: { structured: fraction(structured, 'decision'), baseline: fraction(baseline, 'decision') },
      counts: { structured: counts(structured, 'decision'), baseline: counts(baseline, 'decision') },
    }],
  });
  charts.appendChild(decisionCard);

  const attributionCard = card(
    'Clause attribution accuracy',
    'Of the cases correctly denied, the share naming the clause a reviewer would cite. The baseline’s free-text citation is mapped to a node by token overlap, which favours the baseline.');
  groupedBar(attributionCard, {
    label: 'Clause attribution accuracy by system',
    systems,
    groups: [{
      label: 'correctly denied cases',
      values: { structured: fraction(structured, 'attribution'), baseline: fraction(baseline, 'attribution') },
      counts: { structured: counts(structured, 'attribution'), baseline: counts(baseline, 'attribution') },
    }],
  });
  charts.appendChild(attributionCard);

  const calibrationCard = card(
    'Calibration',
    'Ten bins of predicted confidence against observed correctness. The diagonal is perfect calibration. With n = 20 most bins are empty or hold a single case.');
  calibrationChart(calibrationCard, {
    label: 'Calibration curves',
    systems: systems.map((system) => Object.assign({}, system, {
      bins: (metrics.systems[system.key] || {}).calibration,
    })),
  });
  charts.appendChild(calibrationCard);

  const abstentionCard = card(
    'Abstention quality',
    'Precision and recall on the INDETERMINATE class alone — whether the system declines to decide exactly when the record is incomplete.');
  groupedBar(abstentionCard, {
    label: 'Abstention precision and recall',
    systems,
    groups: [
      {
        label: 'precision',
        values: {
          structured: structured.abstention.precision,
          baseline: baseline ? baseline.abstention.precision : null,
        },
      },
      {
        label: 'recall',
        values: {
          structured: structured.abstention.recall,
          baseline: baseline ? baseline.abstention.recall : null,
        },
      },
    ],
  });
  charts.appendChild(abstentionCard);

  if (!baseline) {
    const warning = document.getElementById('baseline-status');
    warning.textContent =
      `Baseline: ${metrics.baseline_status}. The comparison charts show the criteria graph alone until ` +
      'pipeline/baseline_rag.py has been run with an API key.';
  }

  renderFailures(document.getElementById('failures'), failures, metrics);

  const notes = document.getElementById('metric-notes');
  for (const note of metrics.notes || []) {
    const item = document.createElement('li');
    item.textContent = note;
    notes.appendChild(item);
  }

  status.hidden = true;
}

main();
