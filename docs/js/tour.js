// First-visit guide. Shown once per browser (tracked in localStorage), and
// reopenable any time from the "Guide" button. Pure explanation, no state
// that affects the evaluator.

const STORAGE_KEY = 'prior-auth-tour-seen';

const STEPS = [
  {
    title: 'What this is',
    body: 'This tool checks a clinical note against a published Medicare coverage policy and shows exactly which criterion is missing, if any. It is a demo built for a portfolio project, not a certified clinical or billing tool.',
  },
  {
    title: 'Start with a case',
    body: 'Pick a case from the dropdown at the top. Each one is a synthetic clinical note paired with the Medicare policy it should be checked against.',
  },
  {
    title: 'The criteria tree',
    body: 'This tree is the policy itself, broken into individual criteria from the published source document. Green means the case satisfies that criterion, red means it fails, amber means the note does not document it.',
  },
  {
    title: 'Note and facts',
    body: 'The note is on the left. Every fact extracted from it appears on the right, and each one stays linked back to the exact sentence it came from, so you can check the evidence yourself.',
  },
  {
    title: 'The verdict',
    body: 'The verdict pane rolls the whole tree into one decision: approved, denied, or indeterminate, plus the single clause that is blocking approval and a link to its source.',
  },
  {
    title: 'Try your own note',
    body: 'Scroll down to Live mode to paste in your own OpenRouter key, pick a policy, and run extraction on a note of your own. The verdict is still computed locally by the same rules used above.',
  },
];

export function initTour() {
  const overlay = document.createElement('div');
  overlay.className = 'tour-overlay';
  overlay.hidden = true;

  const dialog = document.createElement('div');
  dialog.className = 'tour-dialog';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-label', 'Guide');

  const title = document.createElement('h3');
  const body = document.createElement('p');
  const dots = document.createElement('div');
  dots.className = 'tour-dots';

  const footer = document.createElement('div');
  footer.className = 'tour-footer';
  const skipBtn = document.createElement('button');
  skipBtn.type = 'button';
  skipBtn.textContent = 'Skip';
  const backBtn = document.createElement('button');
  backBtn.type = 'button';
  backBtn.textContent = 'Back';
  const nextBtn = document.createElement('button');
  nextBtn.type = 'button';
  nextBtn.className = 'primary';
  nextBtn.textContent = 'Next';

  footer.appendChild(skipBtn);
  footer.appendChild(backBtn);
  footer.appendChild(nextBtn);
  dialog.appendChild(title);
  dialog.appendChild(body);
  dialog.appendChild(dots);
  dialog.appendChild(footer);
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  let index = 0;

  function render() {
    const step = STEPS[index];
    title.textContent = step.title;
    body.textContent = step.body;
    dots.textContent = '';
    STEPS.forEach((_, i) => {
      const dot = document.createElement('span');
      dot.className = 'tour-dot' + (i === index ? ' active' : '');
      dots.appendChild(dot);
    });
    backBtn.hidden = index === 0;
    nextBtn.textContent = index === STEPS.length - 1 ? 'Done' : 'Next';
  }

  function close() {
    overlay.hidden = true;
    try { localStorage.setItem(STORAGE_KEY, '1'); } catch (error) { /* private browsing */ }
  }

  function open() {
    index = 0;
    render();
    overlay.hidden = false;
  }

  skipBtn.addEventListener('click', close);
  backBtn.addEventListener('click', () => { index = Math.max(0, index - 1); render(); });
  nextBtn.addEventListener('click', () => {
    if (index === STEPS.length - 1) { close(); return; }
    index += 1;
    render();
  });
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !overlay.hidden) close();
  });

  let seen = false;
  try { seen = localStorage.getItem(STORAGE_KEY) === '1'; } catch (error) { /* private browsing */ }
  if (!seen) open();

  return { open };
}
