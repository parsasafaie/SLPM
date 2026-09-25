/* Installed Apps: Simple mode (your own apps) and Advanced mode (apt/dpkg packages).
 *
 * The Simple/Advanced switch itself lives in the tab row (base.html) and is owned by
 * prefs.js, because the choice applies to the Startup tab too. What is here is the
 * reaction to it: re-read the list in the new mode, and keep the page's own furniture
 * (subtitle, filter, cleanup button) in step.
 */

const state = {
  mode: SLPM.state.mode,
  items: [],
  query: '',
  source: 'all',
};

/* The render cap on list rows. One DOM row per item is fine at a few hundred; past
   six hundred the page gets heavy for no visible gain, so the rest stay one
   narrowed search away. */
const MAX_ROWS = 600;

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
  $('#cleanup').classList.toggle('hidden', !advanced);
  $('#subtitle').textContent = advanced
    ? T('Installed apt/dpkg packages, including system components.')
    : T('Only the apps you installed yourself. Switch to Advanced Mode to see apt/dpkg packages.');
  // The source filter is shown only with the apt/dpkg package list.
  $('#filter').classList.toggle('hidden', !advanced);
  // Install by name is a repository act, so the card belongs to the advanced view.
  $('#install-box').classList.toggle('hidden', !advanced);
}

/* app.js already wired the buttons to SLPM.setMode, which asks before entering
   Advanced Mode and then calls the listeners above. */

/* --------------------------------------------------------------- loading */

async function load() {
  setLoading(true, state.mode === 'simple'
    ? T('Reading your installed apps…')
    : T('Reading apt/dpkg packages…'));
  if (state.mode === 'simple') {
    const r = await api('/api/apps');
    setLoading(false);
    if (!r.ok) return toast(T('Could not list apps'), r.message, 'bad');
    state.items = r.apps || [];
  } else {
    const r = await api('/api/packages');
    setLoading(false);
    if (!r.ok) return toast(T('Could not list apt/dpkg packages'), r.message, 'bad');
    state.items = (r.packages || []).map(p => ({
      id: `apt:${p.name}`, name: p.name, summary: p.summary, version: p.version,
      size: p.size, manager: 'apt', package: p.name, section: p.section,
      essential: p.essential, dangerous: p.dangerous, removable: true, icon_url: '',
      can_launch: false,
    }));
  }
  render();
}

function render() {
  const q = state.query.toLowerCase();
  let items = state.items;
  if (q) {
    items = items.filter(i =>
      (i.name || '').toLowerCase().includes(q) ||
      (i.summary || '').toLowerCase().includes(q) ||
      (i.package || '').toLowerCase().includes(q));
  }
  // The source filter belongs to the advanced apt/dpkg list.
  if (state.mode === 'advanced' && state.source !== 'all') {
    items = items.filter(i => i.manager === state.source);
  }
  listEl.classList.toggle('rows', state.mode === 'advanced');
  listEl.innerHTML = '';
  if (!items.length) {
    empty.classList.remove('hidden');
    $('#empty-note').textContent = state.query
      ? T('Nothing matched “{q}”.', { q: state.query })
      : (state.mode === 'simple'
          ? T('No apps installed by you yet. Switch to Advanced Mode to see apt/dpkg packages.')
          : T('No apt/dpkg packages matched.'));
    return;
  }
  empty.classList.add('hidden');
  const frag = document.createDocumentFragment();
  items.slice(0, MAX_ROWS).forEach(item => frag.appendChild(row(item)));
  listEl.appendChild(frag);
  if (items.length > MAX_ROWS) {
    const more = document.createElement('p');
    more.className = 'muted small';
    more.textContent = T('Showing the first 600 of {n} items — narrow the search to see the rest.', { n: items.length });
    listEl.appendChild(more);
  }
}

function row(item) {
  const el = document.createElement('div');
  el.className = 'item';
  const icon = item.icon_url
    ? `<img src="${esc(item.icon_url)}" alt="" loading="lazy">`
    : `<span class="letter">${esc((item.name || '?').trim().charAt(0).toUpperCase())}</span>`;
  // Essential packages get the strongest badge. Packages that merely belong to the OS
  // are still removable, so they must not look protected. Both are advanced-view concepts.
  const badges = [
    state.mode === 'advanced' && item.essential
      ? `<span class="badge essential">${esc(T('essential'))}</span>` : '',
    state.mode === 'advanced' && !item.essential && item.dangerous
      ? `<span class="badge">${esc(T('os'))}</span>` : '',
    item.manager && item.manager !== 'apt' ? `<span class="badge">${esc(item.manager)}</span>` : '',
  ].join('');
  const meta = [item.version && `v${item.version}`, item.size, item.summary]
    .filter(Boolean).map(esc).join(' · ');
  el.innerHTML = `<div class="icon">${icon}</div>
    <div class="meta">
      <div class="title-line"><strong>${esc(item.name)}</strong>${badges}</div>
      <span>${meta}</span>
    </div>
    <div class="actions"></div>`;
  const actions = $('.actions', el);
  if (item.can_launch) {
    actions.appendChild(button(T('Launch'), async () => {
      // Only the id goes to the server: the launch command is looked up from the
      // desktop entries the server itself scanned, never taken from this request.
      const r = await api('/api/launch', {
        id: item.id, manager: item.manager, package: item.package,
      });
      toast(r.ok ? T('Launching') : T('Could not launch'), r.ok ? item.name : r.message,
        r.ok ? 'ok' : 'bad');
    }));
  }
  if (state.mode === 'simple') {
    actions.appendChild(button(T('Details'), () => details(item)));
    if (item.removable) {
      actions.appendChild(button(T('Remove'), () => removeApp(item), 'btn-danger'));
    }
  } else {
    actions.appendChild(button(T('Details'), () => pkgDetails(item.package, item.essential)));
    // Advanced Mode can remove any listed apt/dpkg package, including Essential ones.
    // The typed package name in the confirmation dialog is the guard.
    actions.appendChild(button(T('Remove'), () =>
      removePackage(item.package, item.dangerous, item.essential), 'btn-danger'));
  }
  return el;
}

function button(label, onclick, cls = 'btn-ghost') {
  const b = document.createElement('button');
  b.className = `btn ${cls}`;
  b.textContent = label;
  b.onclick = onclick;
  return b;
}

/* --------------------------------------------------------------- details */

async function details(item) {
  modal({
    title: item.name,
    html: `<p class="muted">${esc(T('Reading details…'))}</p>`,
    buttons: [{ label: T('Close'), kind: 'ghost', onClick: closeModal }]
  });
  // The package database endpoint is Advanced-only, so Simple Mode shows the row it
  // already has. Asking anyway would answer 403 and leave the panel empty.
  let extra = '';
  if (state.mode === 'advanced' && item.package && item.manager === 'apt') {
    const r = await api(`/api/packages/${encodeURIComponent(item.package)}`);
    if (r.ok) {
      const p = r.package;
      extra = kv({
        [T('Version')]: p.Version, [T('Size')]: p.installed_size,
        [T('Section')]: p.Section, [T('Maintainer')]: p.Maintainer,
        [T('Homepage')]: p.Homepage,
        [T('Description')]: (p.Description || '').split('\n')[0],
        [T('Files installed')]: (p.files || []).length,
      });
    }
  }
  if (!extra) {
    extra = kv({
      [T('Version')]: item.version, [T('Size')]: item.size,
      [T('Source')]: item.manager, [T('Shortcut')]: item.file,
      [T('Command')]: item.exec,
    });
  }
  $('#modal .body').innerHTML = `<p>${esc(item.summary || item.comment || '')}</p>${extra}`;
}

async function pkgDetails(name, essential) {
  modal({
    title: name,
    html: `<p class="muted">${esc(T('Reading apt/dpkg packages…'))}</p>`,
    buttons: [{ label: T('Close'), kind: 'ghost', onClick: closeModal }]
  });
  const r = await api(`/api/packages/${encodeURIComponent(name)}`);
  if (!r.ok) { $('#modal .body').innerHTML = `<p>${esc(r.message)}</p>`; return; }
  const p = r.package;
  // Essential packages can be removed only in Advanced Mode, after typing the package
  // name; apt then receives --allow-remove-essential. Other system components can also
  // be removed, but may break the machine.
  const warn = essential
    ? `<div class="warn-box danger-box">${esc(T('This package is essential to the system. It can be removed in Advanced Mode only after you type its name to confirm; SLPM will use --allow-remove-essential. Removing it can make the computer unable to start and permanently break package management.'))}</div>`
    : p.dangerous
      ? `<div class="warn-box danger-box">${esc(T('This is a system component. '
          + 'Removing it can stop programs from working or prevent the computer from '
          + 'starting.'))}</div>`
      : '';
  const depends = p.Depends && p.Depends.toLowerCase() !== 'none'
    ? p.Depends : T('none');
  $('#modal .body').innerHTML = warn +
    `<p>${esc((p.Description || '').split('\n')[0])}</p>` +
    kv({
      [T('Version')]: p.Version, [T('Size')]: p.installed_size,
      [T('Section')]: p.Section, [T('Priority')]: p.Priority,
      [T('Architecture')]: p.Architecture, [T('Maintainer')]: p.Maintainer,
      [T('Homepage')]: p.Homepage,
      [T('Status')]: statusLabel(p.Status),
    }) +
    `<h3 class="small" style="margin-top:1rem">${esc(T('Dependencies'))}</h3>
     <p class="small muted">${esc(depends.slice(0, 400))}</p>`;
}

/* dpkg reports Status as a three-word phrase ("install ok installed",
   "deinstall ok config-files", "install ok half-configured"). Rewriting one word of it
   in place produced "installed installed", so the whole phrase is mapped to a single
   label instead - and an unfamiliar phrase is shown as-is rather than guessed at. */
function statusLabel(status) {
  const map = {
    'install ok installed': T('installed'),
    'install ok half-installed': T('half-installed'),
    'install ok half-configured': T('half-configured'),
    'install ok unpacked': T('unpacked'),
    'install ok triggers-awaited': T('triggers awaited'),
    'install ok triggers-pending': T('triggers pending'),
    'deinstall ok config-files': T('config files only'),
    'hold ok installed': T('installed (held)'),
    'purge ok not-installed': T('not installed'),
  };
  const raw = (status || '').trim();
  return map[raw] || raw;
}

function kv(obj) {
  return `<dl class="kv">${Object.entries(obj).filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`;
}

/* --------------------------------------------------------------- removal */

function removeApp(item) {
  const what = {
    apt: T('The system package for this app will be uninstalled. Your personal files '
      + 'are not touched.'),
    snap: T('The snap package will be removed, together with the icon it added to your '
      + 'menu. Your personal files are not touched.'),
    flatpak: T('The Flatpak app will be removed, together with the icon it added to '
      + 'your menu. Your personal files are not touched.'),
  }[item.manager]
    || T('The shortcut and the installed files for this app will be deleted.');
  // Snap, Flatpak and apt are package-manager removals, so an admin password is asked
  // for; removing a shortcut SLPM wrote itself needs no privileges.
  const needsRoot = ['apt', 'snap'].includes(item.manager);
  modal({
    title: T('Remove {name}?', { name: item.name }),
    html: `<p>${esc(what)}</p>
      ${item.package
        ? `<p class="small muted">${esc(T('Package: {name}', { name: item.package }))}</p>`
        : ''}
      ${needsRoot
        ? `<div class="warn-box">${esc(T('You will be asked for your admin password to '
            + 'make this change.'))}</div>`
        : ''}`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Remove'), kind: 'danger', onClick: async () => {
          closeModal();
          setLoading(true, T('Removing {name}…', { name: item.name }));
          const r = await api('/api/uninstall', {
            manager: item.manager, target: item.package || item.id,
            file: item.file,
          });
          setLoading(false);
          if (r.ok) { toast(T('Removed'), r.message, 'ok'); load(); }
          else toast(T('Could not remove'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
        } }
    ]
  });
}

function removePackage(name, dangerous, essential) {
  // Three levels of warning. `essential` is the strongest: dpkg marks these as required
  // for the system to exist, and removing one can leave the machine unable to boot or
  // unable to install anything ever again.
  const warning = essential
    ? `<div class="warn-box danger-box">${T('<strong>This package is essential to the '
        + 'system.</strong> Removing it can make the computer unable to start and can '
        + 'break package management permanently, so nothing else can be installed or '
        + 'removed afterwards. This is very likely to destroy this installation of '
        + 'Linux. There is no undo.')}</div>`
    : dangerous
      ? `<div class="warn-box danger-box">${esc(T('You are about to remove a system '
          + 'component. Other programs may depend on it, and on some packages the '
          + 'computer may not start afterwards. Continue only if you know what this '
          + 'package does.'))}</div>`
      : `<div class="warn-box">${esc(T('You are about to remove a package. Other '
          + 'programs may depend on it - check the details first if you are unsure '
          + 'what it does.'))}</div>`;
  modal({
    title: T('Remove {name}', { name }),
    html: `${warning}
           <p class="small muted">${esc(T('Backups are not created by SLPM.'))}</p>
           <label class="label confirm-input" for="confirm-name">
             ${esc(T('Type the package name to confirm'))}
             <code>${esc(name)}</code></label>
           <input id="confirm-name" type="text" autocomplete="off" spellcheck="false">
           <label class="row gap small" style="margin-top:.7rem">
             <input type="checkbox" id="purge">
             ${esc(T('Also delete configuration files (purge)'))}
           </label>`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Remove package'), kind: 'danger', onClick: async box => {
          const typed = $('#confirm-name', box).value.trim();
          if (typed !== name) {
            toast(T('Not confirmed'), T('The name did not match.'), 'bad'); return;
          }
          const purge = $('#purge', box).checked;
          closeModal();
          setLoading(true, T('Removing {name}…', { name }));
          const r = await api('/api/packages/remove', { name, purge, confirmed: typed });
          setLoading(false);
          if (r.ok) { toast(T('Removed'), r.message, 'ok'); load(); }
          else toast(T('Could not remove'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
        } }
    ]
  });
}

/* ------------------------------------------------------------- toolbar */

let searchTimer;
$('#search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  const value = e.target.value;
  searchTimer = setTimeout(() => { state.query = value; render(); }, 120);
});
$('#filter').addEventListener('change', e => {
  state.source = e.target.value;
  if (state.mode === 'simple' && !state.items.length) load();
  else render();
});
$('#refresh').onclick = load;
$('#cleanup').onclick = () => {
  modal({
    title: T('Clean unused dependencies?'),
    html: `<p>${esc(T('Packages that were installed automatically as dependencies and '
             + 'are no longer needed by anything will be removed.'))}</p>
           <div class="warn-box">${T('Review is not possible from here; SLPM runs '
             + '<code>apt-get autoremove</code> with the default settings.')}</div>`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Clean up'), kind: 'primary', onClick: async () => {
          closeModal();
          setLoading(true, T('Cleaning up…'));
          const r = await api('/api/packages/autoremove', {});
          setLoading(false);
          toast(r.ok ? T('Cleaned up') : T('Cleanup failed'),
            [r.message, r.detail].filter(Boolean).join(' '), r.ok ? 'ok' : 'bad');
          load();
        } }
    ]
  });
};

/* ---------------------------------------------------------- install by name

   The card lives in the template and is shown by applyModeChrome in Advanced Mode.
   apt is the only manager with a search endpoint, so the suggestion list appears
   only while apt is selected; snap and flatpak installs take the typed name and are
   shape-checked on the server. */

const pkgManager = $('#pkg-manager');
const pkgName = $('#pkg-name');
const pkgInstall = $('#pkg-install');
const pkgResults = $('#pkg-search-results');

/* The placeholder names the shape the selected manager expects, so a wrong-shape
   name is noticed before it is sent. */
const PKG_PLACEHOLDERS = {
  apt: T('Package name, like vlc'),
  snap: T('Snap name, like code'),
  flatpak: T('Flatpak app id, like org.gimp.GIMP'),
};

function syncPkgBox() {
  pkgName.placeholder = PKG_PLACEHOLDERS[pkgManager.value] || '';
  pkgInstall.disabled = !pkgName.value.trim();
  if (pkgManager.value !== 'apt') pkgResults.innerHTML = '';
}

function paintSearchResults(results) {
  pkgResults.innerHTML = '';
  if (!results.length) {
    const p = document.createElement('p');
    p.className = 'small muted';
    p.textContent = T('No packages matched.');
    pkgResults.appendChild(p);
    return;
  }
  results.slice(0, 20).forEach(res => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'choice';
    b.innerHTML = `<strong></strong><small></small>`;
    $('strong', b).textContent = res.name;
    $('small', b).textContent = res.summary;
    b.onclick = () => {
      pkgName.value = res.name;
      pkgInstall.disabled = false;
      pkgResults.innerHTML = '';
    };
    pkgResults.appendChild(b);
  });
}

let pkgSearchTimer;
pkgName.addEventListener('input', () => {
  syncPkgBox();
  clearTimeout(pkgSearchTimer);
  const q = pkgName.value.trim();
  if (pkgManager.value !== 'apt' || q.length < 2) { pkgResults.innerHTML = ''; return; }
  pkgResults.innerHTML = `<p class="small muted">${esc(T('Searching…'))}</p>`;
  pkgSearchTimer = setTimeout(async () => {
    const r = await api(`/api/apt/search?q=${encodeURIComponent(q)}`);
    // A newer keystroke may have started its own search; only the latest paints.
    if (r.ok && pkgName.value.trim() === q) paintSearchResults(r.results || []);
    else pkgResults.innerHTML = '';
  }, 250);
});

pkgManager.addEventListener('change', syncPkgBox);

pkgInstall.onclick = async () => {
  const name = pkgName.value.trim();
  if (!name || pkgInstall.disabled) return;
  pkgInstall.disabled = true;
  const r = await api('/api/packages/install', { manager: pkgManager.value, name });
  pkgInstall.disabled = false;
  if (r.ok) { toast(T('Done'), r.message, 'ok'); load(); }
  else toast(T('Failed'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
};

syncPkgBox();

/* The page opens in whatever mode the server rendered (see base.html), so the chrome
   has to follow that before the first load rather than assuming simple. */
applyModeChrome();
load();
