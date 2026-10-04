/* Shortcuts: manage .desktop entries in the application menu.
 *
 * Simple mode shows shortcuts that appear in the user's application menu.
 * Advanced mode shows all desktop entries, including hidden ones.
 * Users can view details, delete shortcuts, and create new shortcuts.
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

function button(label, onclick, cls = 'btn-ghost') {
  const b = document.createElement('button');
  b.className = `btn ${cls}`;
  b.textContent = label;
  b.onclick = onclick;
  return b;
}

function setLoading(on, text) {
  loader.classList.toggle('hidden', !on);
  if (on && text) $('span', loader).textContent = text;
  if (on) { listEl.innerHTML = ''; empty.classList.add('hidden'); }
}

/* ------------------------------------------------------------ mode switch */

SLPM.onModeChange(mode => {
  state.mode = mode;
  applyModeChrome();
  load();
});

function applyModeChrome() {
  const advanced = state.mode === 'advanced';
  $('#subtitle').textContent = advanced
    ? T('All desktop entries, including hidden and system components.')
    : T('Application shortcuts that appear in your menu. Switch to Advanced Mode to see all desktop entries.');
}

/* --------------------------------------------------------------- loading */

async function load() {
  setLoading(true, T('Reading shortcuts…'));
  const r = await api('/api/shortcuts');
  setLoading(false);
  if (!r.ok) return toast(T('Could not list shortcuts'), r.message, 'bad');
  state.items = r.shortcuts || [];
  render();
}

function render() {
  const q = state.query.toLowerCase().trim();
  let items = state.items;
  if (q) {
    items = items.filter(i =>
      (i.name || '').toLowerCase().includes(q) ||
      (i.comment || '').toLowerCase().includes(q) ||
      (i.exec || '').toLowerCase().includes(q) ||
      (i.id || '').toLowerCase().includes(q) ||
      (i.categories || []).some(c => c.toLowerCase().includes(q)));
  }

  if (state.filter === 'user') items = items.filter(i => i.user_owned);
  else if (state.filter === 'system') items = items.filter(i => i.source === 'system');
  else if (state.filter === 'flatpak') items = items.filter(i => i.source === 'flatpak');
  else if (state.filter === 'snap') items = items.filter(i => i.source === 'snap');

  listEl.innerHTML = '';
  if (!items.length) {
    empty.classList.remove('hidden');
    $('#empty-note').textContent = state.query
      ? T('Nothing matched “{q}”.', { q: state.query })
      : (state.mode === 'simple'
          ? T('No shortcuts added yet. Switch to Advanced Mode to see all desktop entries.')
          : T('No shortcuts matched.'));
    return;
  }
  empty.classList.add('hidden');
  const frag = document.createDocumentFragment();
  items.forEach(item => frag.appendChild(row(item)));
  listEl.appendChild(frag);
}

function createIconEl(item) {
  const wrap = document.createElement('div');
  wrap.className = 'icon';
  const initial = (item.name || '?').trim().charAt(0).toUpperCase();
  if (item.icon_url) {
    const img = document.createElement('img');
    img.src = item.icon_url;
    img.alt = '';
    img.loading = 'lazy';
    img.onerror = () => {
      const span = document.createElement('span');
      span.className = 'letter';
      span.textContent = initial;
      img.replaceWith(span);
    };
    wrap.appendChild(img);
  } else {
    const span = document.createElement('span');
    span.className = 'letter';
    span.textContent = initial;
    wrap.appendChild(span);
  }
  return wrap;
}

function row(item) {
  const el = document.createElement('div');
  el.className = 'item' + (item.hidden ? ' off' : '');

  el.appendChild(createIconEl(item));

  const badges = [
    item.hidden ? `<span class="badge danger">${esc(T('hidden'))}</span>` : '',
    state.mode === 'advanced' || item.user_owned
      ? `<span class="badge">${esc(item.user_owned ? T('yours') : T('system'))}</span>`
      : '',
    item.source === 'flatpak' ? '<span class="badge">Flatpak</span>' : '',
    item.source === 'snap' ? '<span class="badge">Snap</span>' : '',
  ].join('');

  const metaText = [item.comment, item.exec].filter(Boolean).map(esc).join(' · ');

  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.innerHTML = `<div class="title-line"><strong>${esc(item.name)}</strong>${badges}</div><span>${metaText}</span>`;
  el.appendChild(meta);

  const actions = document.createElement('div');
  actions.className = 'actions';
  if (item.can_launch) {
    actions.appendChild(button(T('Launch'), async () => {
      const r = await api('/api/launch', { id: item.id });
      toast(r.ok ? T('Launching') : T('Could not launch'), r.ok ? item.name : r.message,
        r.ok ? 'ok' : 'bad');
    }));
  }
  actions.appendChild(button(T('Details'), () => details(item)));
  if (item.removable) {
    actions.appendChild(button(T('Delete'), () => removeShortcut(item), 'btn-danger'));
  }
  el.appendChild(actions);

  return el;
}

function kv(obj) {
  return `<dl class="kv">${Object.entries(obj).filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`;
}

function details(item) {
  const extra = kv({
    [T('Command')]: item.exec,
    [T('File')]: item.file,
    [T('Source')]: item.source,
    [T('Categories')]: (item.categories || []).join(', '),
    [T('Terminal')]: item.terminal ? T('Yes') : T('No'),
    [T('Status')]: item.hidden ? T('Hidden') : T('Visible in menu'),
  });

  const buttons = [{ label: T('Close'), kind: 'ghost', onClick: closeModal }];
  if (item.can_launch) {
    buttons.push({
      label: T('Launch'),
      kind: 'primary',
      onClick: async () => {
        closeModal();
        const r = await api('/api/launch', { id: item.id });
        toast(r.ok ? T('Launching') : T('Could not launch'), r.ok ? item.name : r.message,
          r.ok ? 'ok' : 'bad');
      }
    });
  }

  modal({
    title: item.name,
    html: `<p>${esc(item.comment || '')}</p>${extra}`,
    buttons,
  });
}

function removeShortcut(item) {
  modal({
    title: T('Delete shortcut {name}?', { name: item.name }),
    html: `<p>${esc(T('This shortcut will be removed from your applications menu.'))}</p>`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Delete'), kind: 'danger', onClick: async () => {
          closeModal();
          setLoading(true, T('Deleting…'));
          const r = await api('/api/shortcuts/remove', { id: item.id });
          setLoading(false);
          if (r.ok) toast(T('Deleted'), r.message, 'ok');
          else toast(T('Could not delete shortcut'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
          load();
        } }
    ]
  });
}

function addShortcutDialog() {
  modal({
    title: T('Add a shortcut'),
    html: `
      <div style="display:flex;flex-direction:column;gap:.9rem;">
        <div>
          <label class="label" for="sc-name">${esc(T('Program name'))}</label>
          <input id="sc-name" type="text" placeholder="${esc(T('Program name, like My App'))}" autocomplete="off">
        </div>
        <div>
          <label class="label" for="sc-exec">${esc(T('Command'))}</label>
          <div class="drop">
            <input id="sc-exec" type="text" dir="ltr" placeholder="${esc(T('Command to run, like /usr/bin/python3 app.py'))}" autocomplete="off">
            <button type="button" class="btn btn-ghost" id="sc-browse">${esc(T('Browse…'))}</button>
          </div>
        </div>
        <div>
          <label class="label" for="sc-comment">${esc(T('Description'))}</label>
          <input id="sc-comment" type="text" placeholder="${esc(T('Optional description or comment'))}" autocomplete="off">
        </div>
        <div>
          <label class="label" for="sc-icon">${esc(T('Icon'))}</label>
          <div class="drop">
            <input id="sc-icon" type="text" dir="ltr" placeholder="${esc(T('Icon name or path to image'))}" autocomplete="off">
            <button type="button" class="btn btn-ghost" id="sc-browse-icon">${esc(T('Browse…'))}</button>
          </div>
        </div>
        <div>
          <label class="label" for="sc-category">${esc(T('Category'))}</label>
          <select id="sc-category" class="select" style="width:100%;">
            <option value="Utility">Utility</option>
            <option value="Development">Development</option>
            <option value="Office">Office</option>
            <option value="Graphics">Graphics</option>
            <option value="Network">Network</option>
            <option value="AudioVideo">AudioVideo</option>
            <option value="Game">Game</option>
            <option value="System">System</option>
          </select>
        </div>
        <div>
          <label style="display:flex;align-items:center;gap:.55rem;cursor:pointer;">
            <input id="sc-terminal" type="checkbox">
            <span>${esc(T('Run in terminal'))}</span>
          </label>
        </div>
      </div>`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Create shortcut'), kind: 'primary', onClick: submitAdd }
    ],
    onOpen: (box) => {
      const browseBtn = $('#sc-browse', box);
      if (browseBtn) {
        browseBtn.onclick = async () => {
          browseBtn.disabled = true;
          try {
            const r = await api('/api/pick', {});
            if (r.ok && r.path) {
              const execInput = $('#sc-exec', box);
              if (execInput) {
                execInput.value = r.path.includes(' ') ? `"${r.path}"` : r.path;
              }
              const nameInput = $('#sc-name', box);
              if (nameInput && !nameInput.value) {
                const file = r.path.split('/').pop().replace(/\.[^/.]+$/, '');
                nameInput.value = file.charAt(0).toUpperCase() + file.slice(1);
              }
            } else if (r.message) {
              toast(T('No file chooser'), r.message);
            }
          } finally {
            browseBtn.disabled = false;
          }
        };
      }
      const browseIconBtn = $('#sc-browse-icon', box);
      if (browseIconBtn) {
        browseIconBtn.onclick = async () => {
          browseIconBtn.disabled = true;
          try {
            const r = await api('/api/pick', {});
            if (r.ok && r.path) {
              const iconInput = $('#sc-icon', box);
              if (iconInput) {
                iconInput.value = r.path;
              }
            } else if (r.message) {
              toast(T('No file chooser'), r.message);
            }
          } finally {
            browseIconBtn.disabled = false;
          }
        };
      }
    }
  });
}

async function submitAdd() {
  const name = ($('#sc-name') ? $('#sc-name').value : '').trim();
  const exec = ($('#sc-exec') ? $('#sc-exec').value : '').trim();
  const comment = ($('#sc-comment') ? $('#sc-comment').value : '').trim();
  const icon = ($('#sc-icon') ? $('#sc-icon').value : '').trim();
  const category = ($('#sc-category') ? $('#sc-category').value : 'Utility').trim();
  const terminal = $('#sc-terminal') ? $('#sc-terminal').checked : false;

  if (!name) {
    return toast(T('Could not add shortcut'), T('This program has no name, so it cannot be added.'), 'bad');
  }
  if (!exec) {
    return toast(T('Could not add shortcut'), T('This program has no command to run.'), 'bad');
  }

  closeModal();
  setLoading(true, T('Adding…'));
  const r = await api('/api/shortcuts/add', {
    name,
    exec,
    comment,
    icon,
    category,
    terminal,
  });
  setLoading(false);
  if (r.ok) {
    toast(T('Added'), r.message, 'ok');
  } else {
    toast(T('Could not add shortcut'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
  }
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
$('#add').onclick = addShortcutDialog;

applyModeChrome();
load();
