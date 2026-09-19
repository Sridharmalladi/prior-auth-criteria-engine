// Optional live mode: run fact extraction on your own note, with your own key.
//
// The key is held in a closure variable for the lifetime of the page and is
// sent to exactly one place: api.openrouter.ai, in the Authorization header of
// the request you trigger. It is never written to localStorage, sessionStorage,
// a cookie, the URL, or any other host. Reloading the page discards it.
//
// Extraction happens remotely; the verdict does not. The model returns facts,
// and evaluator.js — the same code the demo runs — decides the outcome locally.

const ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions';
const MODEL = 'anthropic/claude-sonnet-4.5';

let apiKey = '';

function buildPrompt(policy, note) {
  const keys = [];
  for (const node of Object.values(policy.nodes)) {
    if (node.type !== 'LEAF') continue;
    const predicate = node.predicate;
    keys.push({
      key: predicate.key,
      expects: Array.isArray(predicate.value) ? 'array of strings'
        : typeof predicate.value === 'boolean' ? 'boolean'
        : typeof predicate.value === 'number' ? 'number' : 'string',
      unit: predicate.unit || null,
      used_by: node.label,
      compared_with: `${predicate.op} ${JSON.stringify(predicate.value)}`,
    });
  }

  return [
    'You extract structured facts from a clinical note. You do not decide coverage.',
    '',
    'Return JSON of the form {"facts": [{"key": ..., "value": ..., "unit": ..., "confidence": 0-1, "evidence_text": ...}]}.',
    '',
    'Rules:',
    '- Only use keys from the list below.',
    '- evidence_text must be copied verbatim from the note, exactly as it appears.',
    '- Never infer a value to fill a key. If the note does not document it, omit the key entirely.',
    '  An absent key is a meaningful signal and is handled downstream.',
    '- A negative statement is a fact: "no middle ear infection" gives value false, not omission.',
    '',
    `Keys for policy ${policy.policy_id}:`,
    JSON.stringify(keys, null, 1),
    '',
    'Note:',
    '"""',
    note,
    '"""',
  ].join('\n');
}

// The same span check the offline pipeline applies: a fact whose evidence is not
// in the note is dropped rather than shown.
function verifyFacts(rawFacts, note) {
  const kept = [];
  const dropped = [];
  for (const fact of rawFacts || []) {
    const evidence = typeof fact.evidence_text === 'string' ? fact.evidence_text : '';
    const index = note.indexOf(evidence);
    if (!evidence || index === -1) {
      dropped.push({ key: fact.key, reason: 'evidence_text not found verbatim in the note' });
      continue;
    }
    kept.push({
      key: fact.key,
      value: fact.value,
      unit: fact.unit === undefined ? null : fact.unit,
      confidence: typeof fact.confidence === 'number' ? fact.confidence : 0.5,
      source_span: [index, index + evidence.length],
      evidence_text: evidence,
    });
  }
  return { kept, dropped };
}

async function extract(policy, note) {
  const response = await fetch(ENDPOINT, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: MODEL,
      temperature: 0,
      response_format: { type: 'json_object' },
      messages: [{ role: 'user', content: buildPrompt(policy, note) }],
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`OpenRouter returned ${response.status}: ${detail.slice(0, 200)}`);
  }
  const payload = await response.json();
  const content = payload.choices && payload.choices[0] && payload.choices[0].message.content;
  if (!content) throw new Error('No content in the model response.');
  return JSON.parse(content);
}

export function initLiveMode({ container, manifest, loadPolicy, onResult }) {
  container.textContent = '';

  const intro = document.createElement('p');
  intro.className = 'key-notice';
  intro.textContent =
    'Paste an OpenRouter key and a note of your own to run extraction against one of the policies. ' +
    'Extraction runs remotely; the verdict is still computed locally by the same evaluator the demo uses.';
  container.appendChild(intro);

  const keyRow = document.createElement('div');
  keyRow.className = 'row';
  const keyLabel = document.createElement('label');
  keyLabel.textContent = 'OpenRouter key ';
  const keyInput = document.createElement('input');
  keyInput.type = 'password';
  keyInput.autocomplete = 'off';
  keyInput.placeholder = 'sk-or-…';
  keyLabel.appendChild(keyInput);
  keyRow.appendChild(keyLabel);
  container.appendChild(keyRow);

  const notice = document.createElement('p');
  notice.className = 'key-notice';
  notice.textContent =
    'Your key is used only for this request and is not stored or transmitted anywhere else. ' +
    'It is kept in a JavaScript variable, never in localStorage, sessionStorage, a cookie or the URL, and is discarded when you reload.';
  container.appendChild(notice);

  const policyRow = document.createElement('div');
  policyRow.className = 'row';
  const policyLabel = document.createElement('label');
  policyLabel.textContent = 'Policy ';
  const policySelect = document.createElement('select');
  for (const policy of manifest.policies) {
    const option = document.createElement('option');
    option.value = policy.policy_id;
    option.textContent = `${policy.title} (${policy.source_type})`;
    policySelect.appendChild(option);
  }
  policyLabel.appendChild(policySelect);
  policyRow.appendChild(policyLabel);
  container.appendChild(policyRow);

  const noteArea = document.createElement('textarea');
  noteArea.placeholder = 'Paste a clinical note. Do not paste real patient information.';
  noteArea.setAttribute('aria-label', 'Clinical note');
  container.appendChild(noteArea);

  const runRow = document.createElement('div');
  runRow.className = 'row';
  const runButton = document.createElement('button');
  runButton.type = 'button';
  runButton.className = 'primary';
  runButton.textContent = 'Extract and evaluate';
  runButton.disabled = true;
  runButton.title = 'Enter a key to enable live mode.';
  runRow.appendChild(runButton);
  const status = document.createElement('span');
  status.className = 'key-notice';
  status.textContent = 'Live mode is disabled until a key is entered.';
  runRow.appendChild(status);
  container.appendChild(runRow);

  const updateEnabled = () => {
    apiKey = keyInput.value.trim();
    const ready = apiKey.length > 0 && noteArea.value.trim().length > 0;
    runButton.disabled = !ready;
    if (!apiKey) status.textContent = 'Live mode is disabled until a key is entered.';
    else if (!noteArea.value.trim()) status.textContent = 'Paste a note to run.';
    else status.textContent = 'Ready.';
  };
  keyInput.addEventListener('input', updateEnabled);
  noteArea.addEventListener('input', updateEnabled);

  runButton.addEventListener('click', async () => {
    runButton.disabled = true;
    status.textContent = 'Extracting…';
    try {
      const policy = await loadPolicy(policySelect.value);
      const note = noteArea.value;
      const payload = await extract(policy, note);
      const { kept, dropped } = verifyFacts(payload.facts, note);
      status.textContent =
        `Extracted ${kept.length} fact${kept.length === 1 ? '' : 's'}` +
        (dropped.length ? `; dropped ${dropped.length} with unverifiable evidence spans.` : '.');
      onResult({ policy, facts: kept, note, title: 'Live note (pasted)' });
    } catch (error) {
      status.textContent = `Failed: ${error.message}`;
    } finally {
      runButton.disabled = false;
    }
  });
}
