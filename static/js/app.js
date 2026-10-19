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

/* ------------------------------------------------------------------ self-update
 *
 * The version pill in the top bar is only a check: the server reads its own
 * version, asks the release server for the newest one and returns two terminal
 * commands for the variant that is actually running (from $APPIMAGE). Nothing
 * here changes the system; the copy buttons exist because the commands are
 * meant to be pasted into a terminal, not because SLPM would run them itself. */

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch (e) { /* clipboard API denied or absent - fall back below */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

let versionCheckBusy = false;
if ($('#version-pill')) ($('#version-pill').onclick = async () => {
  // A double click (or a click while a stale check is still in flight) must not open
  // a second modal cycle on top of the first.
  if (versionCheckBusy) return;
  versionCheckBusy = true;
  modal({
    title: T('Check for a new version of SLPM'),
    html: `<p class="muted">${esc(T('Checking…'))}</p>`,
    buttons: [{ label: T('Close'), kind: 'ghost' }],
  });
  // Captured before the await: if the user dismissed the checking dialog (or opened a
  // different one) while the server answered, the result must not reopen over it.
  const checkingBody = $('#modal .body');
  const data = await api('/api/selfupdate');
  versionCheckBusy = false;
  if (!checkingBody || !checkingBody.isConnected) return;
  if (!data || !data.ok) {
    modal({
      title: T('Check for a new version of SLPM'),
      html: `<p>${esc((data && data.message) || T('The check could not be answered.'))}</p>`,
      buttons: [{ label: T('Close'), kind: 'ghost' }],
    });
    return;
  }
  /* When the running variant is known it is preselected; from a source checkout
     both command pairs are kept and the picker below decides. */
  const plans = data.plan || {};
  let variant = (data.variant && plans[data.variant])
    ? data.variant : Object.keys(plans)[0];

  const statusHtml = () => {
    if (data.status === 'update_available') {
      const txt = T('This copy runs version {current}; version {latest} is out.',
                    { current: data.current, latest: data.latest.version });
      return `<p>${esc(txt)}</p>`;
    }
    if (data.status === 'up_to_date')
      return `<p>${esc(T('This copy is already the newest version.'))}</p>`;
    return `<p>${esc(T('This copy could not be compared to the newest release '
        + 'automatically. You decide from the file list below.'))}</p>`;
  };

  const render = (box) => {
    const root = $('.update-plans', box);
    if (!root) return;
    const plan = plans[variant];
    let html = statusHtml();
    if (!plan) {
      html += `<p class="muted small">${esc(T('No download was listed on the release page.'))}</p>`;
      root.innerHTML = html;
      return;
    }
    if (data.variant === 'unknown' && Object.keys(plans).length > 1) {
      html += `<p class="small muted">${esc(T('Which one is your SLPM?'))}</p>
        <div class="variant-row" role="group" aria-label="${esc(T('Which one is your SLPM?'))}"></div>`;
      root.innerHTML = html;
      const row = $('.variant-row', root);
      const names = { web: T('Web dashboard'), desktop: T('Desktop window') };
      Object.keys(plans).forEach(v => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = `variant-btn ${v === variant ? 'active' : ''}`;
        b.textContent = names[v] || v;
        b.onclick = () => { variant = v; render(box); };
        row.appendChild(b);
      });
    } else {
      root.innerHTML = html;
    }
    ['download_cmd', 'run_cmd'].forEach(field => {
      if (!plan[field]) return;
      const sec = document.createElement('div');
      sec.className = 'update-sec';
      const label = field === 'download_cmd'
        ? T('Download command (checks the published SHA256 sums)')
        : T('Run command');
      sec.innerHTML = `<div class="update-sec-head"><strong>${esc(label)}</strong>`
        + `<button type="button" class="btn btn-ghost copy-btn">${esc(T('Copy'))}</button></div>`
        + `<pre class="update-cmd"><code>${esc(plan[field])}</code></pre>`;
      $('.copy-btn', sec).onclick = async () => {
        const ok = await copyText(plan[field]);
        toast(ok ? T('Copied to clipboard.') : T('Copying to the clipboard did not work.'));
      };
      root.appendChild(sec);
    });
  };

  modal({
    title: T('Check for a new version of SLPM'),
    html: `<div class="update-plans"><p class="muted">${esc(T('Checking…'))}</p></div>`,
    buttons: [
      { label: T('Close'), kind: 'ghost', onClick: closeModal },
    ],
    onOpen: render,
  });
});

/* The Simple/Advanced switch in the tab row. It is rendered by the template (see
   base.html), so a page that has no switch simply has no buttons to wire. */
$$('.mode-btn').forEach(btn => {
  btn.onclick = () => SLPM.setMode(btn.dataset.mode);
});
