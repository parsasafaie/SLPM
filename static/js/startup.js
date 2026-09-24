/* Startup Apps: entries that start with a session, plus an add button.
 *
 * The list is rebuilt from the server after every change rather than edited in place,
 * because a system entry and its user override are the same row and only the server
 * knows which file a toggle actually landed in.
 *
 * The Simple/Advanced switch lives in the tab row (base.html) and is owned by prefs.js,
 * because the choice applies to the Installed Apps tab too. In Simple mode the list is
 * the user's own entries only, and their turn-off control is the only one offered;
 * packaged entries belong to Advanced Mode.
 */

const state = {
  mode: SLPM.state.mode,
  items: [],
  query: '',
  filter: 'all',
};

const listEl = $('#list');
const loader = $('#loader');
const empty = $('#empty');

function setLoading(on, text) {
  loader.classList.toggle('hidden', !on);
  if (on && text) $('span', loader).textContent = text;
  if (on) { listEl.innerHTML = ''; empty.classList.add('hidden'); }
}

/* ------------------------------------------------------------ mode switch */

/* prefs.js tells us when the switch was used; the page only has to repaint itself. */
SLPM.onModeChange(mode => {
  state.mode = mode;
  applyModeChrome();
  load();
});

function applyModeChrome() {
  const advanced = state.mode === 'advanced';
  $('#subtitle').textContent = advanced
    ? T('Startup apps that start when you log in, including system startup apps.')
    : T('Only the startup apps you added yourself. Switch to Advanced Mode to see system startup apps.');
  // The system/yours split only exists in the advanced list, where both appear.
  const opt = $('#filter').querySelector('option[value="system"]');
  if (opt) opt.hidden = !advanced;
  if (!advanced && state.filter === 'system') {
    state.filter = 'all';
    $('#filter').value = 'all';
  }
}

/* --------------------------------------------------------------- loading */

async function load() {
  setLoading(true, T('Reading startup apps…'));
  const r = await api('/api/startup');
  setLoading(false);
  if (!r.ok) return toast(T('Could not list startup apps'), r.message, 'bad');
  state.items = r.apps || [];
  render();
}

function render() {
  const q = state.query.toLowerCase();
  let items = state.items;
  if (q) {
    items = items.filter(i =>
      (i.name || '').toLowerCase().includes(q) ||
      (i.comment || '').toLowerCase().includes(q) ||
      (i.exec || '').toLowerCase().includes(q));
  }
  // The source filter follows ownership, so "yours" means the same thing here as it
  // does in the badge and in what Simple Mode shows.
  if (state.filter === 'disabled') items = items.filter(i => !i.enabled);
  else if (state.filter === 'user') items = items.filter(i => i.user_owned);
  else if (state.filter === 'system') items = items.filter(i => !i.user_owned);

  listEl.innerHTML = '';
  if (!items.length) {
    empty.classList.remove('hidden');
    $('#empty-note').textContent = state.query
      ? T('Nothing matched “{q}”.', { q: state.query })
      : (state.mode === 'simple'
          ? T('No startup apps added yet. Switch to Advanced Mode to see system startup apps.')
          : T('No startup apps matched.'));
    return;
  }
  empty.classList.add('hidden');
  const frag = document.createDocumentFragment();
  items.forEach(item => frag.appendChild(row(item)));
  listEl.appendChild(frag);
}

function row(item) {
  const el = document.createElement('div');
  el.className = 'item' + (item.enabled ? '' : ' off');
  const icon = item.icon_url
    ? `<img src="${esc(item.icon_url)}" alt="" loading="lazy">`
    : `<span class="letter">${esc((item.name || '?').trim().charAt(0).toUpperCase())}</span>`;
  // The source badge is only meaningful where both kinds are on screen. In Simple Mode
  // every row is the user's, so a badge saying so on every one of them is noise.
  const badges = [
    state.mode === 'advanced'
      ? `<span class="badge">${esc(item.user_owned ? T('yours') : T('system'))}</span>` : '',
    item.enabled ? '' : `<span class="badge danger">${esc(T('turned off'))}</span>`,
  ].join('');
  // The command is shown rather than the file path: it is what the user recognises, and
  // it is what would have to be edited by hand to change what the entry runs.
  const meta = [item.comment, item.exec].filter(Boolean).map(esc).join(' · ');
  el.innerHTML = `<div class="icon">${icon}</div>
    <div class="meta">
      <div class="title-line"><strong>${esc(item.name)}</strong>${badges}</div>
      <span>${meta}</span>
    </div>
    <div class="actions"></div>`;
  // Only an entry the user owns can be switched off from here. The server refuses the
  // rest anyway; not drawing the control is what keeps the rule visible rather than
  // something the user discovers by being told no.
  if (item.enabled && (state.mode === 'advanced' || item.user_owned)) {
    $('.actions', el).appendChild(closeButton(item));
  }
  return el;
}

/* The X is the window-close convention: one control, and it takes the entry out of the
   startup list. It is hidden on an entry that is already off, where there is nothing left
   to close, and on a packaged entry the user has no override for yet - that one is closed
   by writing an override, which is a change the row explains in its confirmation. */
function closeButton(item) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'close-x';
  b.setAttribute('aria-label', T('Turn off {name}', { name: item.name }));
  b.title = T('Turn off {name}', { name: item.name });
  b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  b.onclick = () => setEnabled(item);
  return b;
}

/* --------------------------------------------------------------- changes */

/* Closing an entry takes it off the startup list, so it asks first. */
function setEnabled(item) {
  modal({
    title: T('Turn off {name}?', { name: item.name }),
    html: `<p>${esc(T('This startup app will no longer start when you log in. It stays installed and can still be opened from your menu.'))}</p>
      <p class="small muted">${esc(T('You can add it again later from Add startup app.'))}</p>`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Turn off'), kind: 'danger', onClick: () => {
          closeModal();
          applyToggle(item);
        } }
    ]
  });
}

async function applyToggle(item) {
  setLoading(true, T('Saving…'));
  const r = await api('/api/startup/toggle', { id: item.id, enabled: false });
  setLoading(false);
  if (!r.ok) toast(T('Could not change this'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
  else toast(T('Saved'), r.message, 'ok');
  load();
}

/* ------------------------------------------------------------ add button */

async function addDialog() {
  modal({
    title: T('Add a startup app'),
    html: `<p class="muted">${esc(T('Reading installed apps…'))}</p>`,
    buttons: [{ label: T('Cancel'), kind: 'ghost', onClick: closeModal }]
  });
  const r = await api('/api/startup/candidates');
  if (!r.ok) {
    $('#modal .body').innerHTML = `<p>${esc(r.message)}</p>`;
    return;
  }
  const apps = r.apps || [];
  if (!apps.length) {
    $('#modal .body').innerHTML = `<p>${esc(T('No installed app with a launch command was found.'))}</p>`;
    return;
  }
  $('#modal .body').innerHTML = `
    <p class="muted small">${esc(T('Pick the app to add as a startup app.'))}</p>
    <input id="cand-search" type="search" placeholder="${esc(T('Search apps…'))}"
           autocomplete="off">
    <div class="choices" id="cand-list"></div>`;
  const list = $('#cand-list');
  const paint = query => {
    const q = (query || '').toLowerCase();
    const hits = apps.filter(a =>
      !q || (a.name || '').toLowerCase().includes(q) ||
      (a.exec || '').toLowerCase().includes(q));
    list.innerHTML = '';
    if (!hits.length) {
      list.innerHTML = `<p class="small muted">${esc(T('No apps matched.'))}</p>`;
      return;
    }
    hits.slice(0, 200).forEach(app => {
      const b = document.createElement('button');
      b.className = 'choice';
      b.innerHTML = `<strong></strong><small></small>`;
      $('strong', b).textContent = app.name;
      $('small', b).textContent = app.exec;
      b.onclick = () => submitAdd(app);
      list.appendChild(b);
    });
  };
  paint('');
  $('#cand-search').addEventListener('input', e => paint(e.target.value));
  $('#cand-search').focus();
}

async function submitAdd(app) {
  closeModal();
  setLoading(true, T('Adding…'));
  const r = await api('/api/startup/add', {
    name: app.name, exec: app.exec, icon: app.icon, comment: app.comment,
  });
  setLoading(false);
  if (r.ok) toast(T('Added'), r.message, 'ok');
  else toast(T('Could not add'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
  load();
}

/* ------------------------------------------------------------- toolbar */

let searchTimer;
$('#search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  const value = e.target.value;
  searchTimer = setTimeout(() => { state.query = value; render(); }, 120);
});
$('#filter').addEventListener('change', e => { state.filter = e.target.value; render(); });
$('#refresh').onclick = load;
$('#add').onclick = addDialog;

/* The page opens in whatever mode the server rendered (see base.html), so the chrome
   has to follow that before the first load rather than assuming simple. */
applyModeChrome();
load();
