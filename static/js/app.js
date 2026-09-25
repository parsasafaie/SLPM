/* Shared helpers: toasts, modals, API calls. No framework. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* Server messages are already in the page's language, but a few are built in the
   browser (see prefs.js), and those have to be translated where they are shown. */
const T = (text, values) => (window.TT ? TT(text, values) : text);

async function api(url, body) {
  const opts = body === undefined
    ? { method: 'GET' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    return { ok: false, message: T('SLPM is not reachable any more. Is the server still running?'), detail: String(e) };
  }
  let data;
  try {
    data = await res.json();
  } catch (e) {
    return { ok: false, message: T('The server sent a reply SLPM could not read.'), detail: `HTTP ${res.status}` };
  }
  return data;
}

function toast(title, message = '', kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `<button class="close" aria-label="${esc(T('Dismiss'))}">&times;</button>
    <strong></strong><p></p>`;
  $('strong', el).textContent = title;
  const p = $('p', el);
  p.textContent = message || '';
  if (!message) p.remove();
  $('.close', el).onclick = () => el.remove();
  $('#toasts').appendChild(el);
  if (kind === 'ok') setTimeout(() => el.remove(), 9000);
  return el;
}

function esc(text) {
  return String(text == null ? '' : text).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* modal({title, html, buttons:[{label, kind, onClick}], onOpen})

   The dialog moves keyboard focus in on open and traps Tab inside until it closes,
   then gives the focus back to whatever had it before. Without the trap, a keyboard
   user tabbing through a remove dialog would walk straight into the page's controls,
   where the same buttons exist with their full destructive power. */
let lastFocused = null;
function modal(opts) {
  const overlay = $('#overlay');
  const box = $('#modal');
  box.innerHTML = `<h3></h3><div class="body"></div><div class="footer"></div>`;
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-label', opts.title || '');
  box.tabIndex = -1;
  $('h3', box).textContent = opts.title || '';
  $('.body', box).innerHTML = opts.html || '';
  const footer = $('.footer', box);
  (opts.buttons || []).forEach(b => {
    const btn = document.createElement('button');
    btn.className = `btn ${b.kind ? 'btn-' + b.kind : 'btn-ghost'}`;
    btn.textContent = b.label;
    btn.onclick = () => b.onClick ? b.onClick(box) : closeModal();
    footer.appendChild(btn);
  });
  const focusables = () => $$('button, [href], input, select, textarea', box)
    .filter(el => !el.disabled && el.offsetParent !== null);
  lastFocused = document.activeElement;
  overlay.classList.remove('hidden');
  if (opts.onOpen) opts.onOpen(box);
  requestAnimationFrame(() => {
    const first = focusables()[0] || box;
    first.focus();
  });
  box.onkeydown = e => {
    if (e.key !== 'Tab') return;
    const els = focusables();
    if (!els.length) { e.preventDefault(); return; }
    const first = els[0], last = els[els.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === box)) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  };
  return box;
}

function closeModal() {
  $('#overlay').classList.add('hidden');
  const box = $('#modal');
  box.innerHTML = '';
  box.onkeydown = null;
  if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  lastFocused = null;
}

$('#overlay') && $('#overlay').addEventListener('click', e => {
  if (e.target.id === 'overlay') closeModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

/* ------------------------------------------------------------------ top bar */

$('#theme-toggle') && ($('#theme-toggle').onclick = () => SLPM.toggleTheme());
$('#lang-toggle') && ($('#lang-toggle').onclick = () => SLPM.toggleLang());

/* The Simple/Advanced switch in the tab row. It is rendered by the template (see
   base.html), so a page that has no switch simply has no buttons to wire. */
$$('.mode-btn').forEach(btn => {
  btn.onclick = () => SLPM.setMode(btn.dataset.mode);
});
