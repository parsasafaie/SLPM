/* Updates: what apt, Flatpak and snap can still upgrade, and the one click per step.
 *
 * Available in both modes - updating what is already installed targets nothing the
 * user does not own, and the run endpoint's confirm dialog and polkit password are
 * the protections. The card skeletons (headings, buttons, the count and up-to-date
 * sentences) are rendered by the template in the page's language; this script fills
 * the counts, the lists and the busy state from /api/updates. /api/updates/run blocks
 * until its step is done, so the clicked button simply stays busy for the whole run.
 */

const cards = $$('[id^="card-"]');
const loader = $('#loader');
let running = null;   // the button currently waiting on /api/updates/run
// The last list each manager reported. The confirm dialogs read it to say which
// snaps are running now, because a refresh of a running snap closes it.
const painted = { apt: [], flatpak: [], snap: [] };

/* The confirmation copy per manager. apt and snap ask for the admin password; the
   Flatpak update runs at user level, so it must not claim to. */
const CONFIRM = {
  apt: {
    title: 'Update all system packages?',
    html: T('Every package on this system will be upgraded to its newest version. '
      + 'On a large system this can take several minutes.'),
    warn: T('SLPM will ask for your administrator password.'),
  },
  flatpak: {
    title: 'Update all Flatpak apps?',
    html: T('Every Flatpak app you have installed will be updated to its newest '
      + 'version.'),
    warn: '',
  },
  snap: {
    title: 'Update all snap apps?',
    html: T('Every snap on this system will be refreshed to its newest revision.'),
    warn: T('SLPM will ask for your administrator password.'),
  },
};

function setLoading(on) {
  loader.classList.toggle('hidden', !on);
  if (on) cards.forEach(c => c.classList.add('hidden'));
}

function setButtonsBusy(busy) {
  $$('#card-apt button, #card-flatpak button, #card-snap button')
    .forEach(b => { b.disabled = busy; });
}

async function load() {
  setLoading(true);
  const r = await api('/api/updates');
  setLoading(false);
  if (!r.ok) return;
  cards.forEach(c => c.classList.remove('hidden'));
  for (const mgr of ['apt', 'flatpak', 'snap']) {
    paint(mgr, r[mgr] || [], r.managers ? r.managers[mgr] : true);
  }
}

function paint(mgr, items, managerInstalled) {
  const card = $('#card-' + mgr);
  const avail = $('#avail-' + mgr);
  const list = $('#list-' + mgr);
  const count = $('#count-' + mgr);
  const updateBtn = $('#run-' + mgr + '-update');
  const refreshBtn = $('#run-' + mgr + '-refresh');
  const toggle = $('#toggle-' + mgr);

  painted[mgr] = items;
  list.innerHTML = '';
  // The chevron and the list it opens exist only while there is something to update;
  // a fresh load always starts collapsed.
  toggle.classList.add('hidden');
  toggle.setAttribute('aria-expanded', 'false');
  list.classList.add('collapsed');
  if (!managerInstalled) {
    avail.textContent = T('This manager is not installed on this system.');
    count.classList.add('hidden');
    [updateBtn, refreshBtn].forEach(b => { if (b) b.disabled = true; });
    return;
  }
  if (!items.length) {
    avail.textContent = T(card.dataset.empty);
    count.classList.add('hidden');
    if (updateBtn) updateBtn.disabled = true;
    return;
  }
  toggle.classList.remove('hidden');
  toggle.setAttribute('aria-label', T('Show available updates'));
  avail.textContent = T(card.dataset.count, { count: items.length });
  count.textContent = String(items.length);
  count.classList.remove('hidden');
  if (updateBtn) updateBtn.disabled = false;

  const frag = document.createDocumentFragment();
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'updates-row';
    // apt knows the versions on both sides of the arrow; the other two managers only
    // report the installed one, so the arrow appears only where it is true. apt rows
    // lead with the package name; flatpak/snap rows lead with the id and show the
    // friendly name beside it, which is the pair the user actually types.
    const right = item.available
      ? `${esc(item.current || '')} → ${esc(item.available)}`
      : esc(item.version || '');
    row.innerHTML = `<strong></strong><small></small><code>${right}</code>`;
    $('strong', row).textContent = mgr === 'apt' ? item.name : (item.id || item.name);
    $('small', row).textContent = mgr === 'apt' ? '' : (item.name || '');
    // A running snap is about to be closed by its own refresh, so it gets a marker
    // next to its name - the confirm dialog repeats the warning in full.
    if (mgr === 'snap' && item.running) {
      const dot = document.createElement('span');
      dot.className = 'running-dot';
      dot.title = T('Running');
      row.appendChild(dot);
    }
    // The row's own button updates just this item; the card button does all of them.
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn';
    btn.textContent = T('Update');
    btn.onclick = () => runOne(mgr, item, btn);
    row.appendChild(btn);
    frag.appendChild(row);
  });
  list.appendChild(frag);
}

// A snap refresh stops the snap's processes, so a running one (an open VS Code)
// gets killed mid-session and the update can fail on the pile of PIDs it could not
// stop cleanly. The confirm dialog says so and asks the app to be closed first.
function runningWarn(mgr, items) {
  if (mgr !== 'snap') return '';
  const names = (items || []).filter(i => i.running).map(i => i.name || i.id);
  if (!names.length) return '';
  if (names.length === 1)
    return T('{name} is running now. Close it first, then update.', { name: names[0] });
  return T('These are running now. Close them first, then update: {list}',
           { list: names.join(', ') });
}

function runStep(mgr, step, btn) {
  if (running) return;
  const doIt = () => {
    running = btn;
    setButtonsBusy(true);
    const old = btn.textContent;
    btn.textContent = T('Updating…');
    api('/api/updates/run', { manager: mgr, step: step || 'update' }).then(r => {
      running = null;
      setButtonsBusy(false);
      btn.textContent = old;
      // The server's message is already in the page's language, so it carries the
      // result on its own.
      if (r.ok) toast(T('Done'), r.message, 'ok');
      else toast(T('Failed'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
      load();
    });
  };
  if (step === 'refresh') { doIt(); return; }
  // A real update is the irreversible one, so it asks first; a list refresh only
  // reads from the mirrors.
  const c = CONFIRM[mgr];
  const runWarn = runningWarn(mgr, painted[mgr]);
  modal({
    title: T(c.title),
    html: `<p>${esc(T(c.html))}</p>${c.warn
      ? `<div class="warn-box">${esc(T(c.warn))}</div>` : ''}${runWarn
      ? `<div class="warn-box">${esc(runWarn)}</div>` : ''}`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Continue'), kind: 'primary', onClick: () => { closeModal(); doIt(); } }
    ]
  });
}

// One row at a time: the same one-run-at-a-time gate as the card button, but the
// payload names the item, and apt pins the version the row showed.
function runOne(mgr, item, btn) {
  if (running) return;
  const name = mgr === 'apt' ? item.name : (item.id || item.name);
  const label = item.name || name;
  const doIt = () => {
    running = btn;
    setButtonsBusy(true);
    const old = btn.textContent;
    btn.textContent = T('Updating…');
    api('/api/updates/run', { manager: mgr, step: 'update', name: name,
                              version: item.available || '' }).then(r => {
      running = null;
      setButtonsBusy(false);
      btn.textContent = old;
      if (r.ok) toast(T('Done'), r.message, 'ok');
      else toast(T('Failed'), [r.message, r.detail].filter(Boolean).join(' '), 'bad');
      load();
    });
  };
  const warn = mgr === 'flatpak' ? '' : T('SLPM will ask for your administrator password.');
  const runWarn = runningWarn(mgr, [item]);
  modal({
    title: T('Update {name}?', { name: label }),
    html: `<p>${esc(T('Only {name} will be updated to its newest version.', { name: label }))}</p>
           ${warn ? `<div class="warn-box">${esc(warn)}</div>` : ''}
           ${runWarn ? `<div class="warn-box">${esc(runWarn)}</div>` : ''}`,
    buttons: [
      { label: T('Cancel'), kind: 'ghost', onClick: closeModal },
      { label: T('Continue'), kind: 'primary', onClick: () => { closeModal(); doIt(); } }
    ]
  });
}

$$('#card-apt [id^="run-"], #card-flatpak [id^="run-"], #card-snap [id^="run-"]').forEach(btn => {
  // The button id is the contract: run-<manager>-<step>. Only run- buttons carry a
  // step; the header chevron (toggle-<manager>) must not be mistaken for one.
  const [, mgr, step] = btn.id.split('-');
  btn.onclick = () => runStep(mgr, step, btn);
});

// Open and close the list of upgradable items under each card.
$$('#toggle-apt, #toggle-flatpak, #toggle-snap').forEach(btn => {
  btn.onclick = () => {
    const open = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', String(!open));
    btn.setAttribute('aria-label', open ? T('Show available updates')
                                        : T('Hide available updates'));
    $('#list-' + btn.id.split('-')[1]).classList.toggle('collapsed', open);
  };
});

$('#refresh').onclick = () => {
  // The toolbar refresh re-reads all three lists; apt's list refresh button does the
  // heavier apt-get update.
  load();
};

SLPM.onModeChange(() => load());
load();
