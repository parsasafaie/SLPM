/* Install page: detect a dropped file, install it, explain what happened. */

const pathInput = $('#path');
const installBtn = $('#install');
const detectBox = $('#detect');
const progress = $('#progress');
let detected = null;
let working = false;

function setBusy(on, title, note) {
  working = on;
  progress.classList.toggle('hidden', !on);
  installBtn.disabled = on || !detected || !detected.installable;
  $('#browse').disabled = on;
  if (on) {
    $('#progress-title').textContent = title || T('Working…');
    $('#progress-note').textContent = note || T('This can take a minute. Keep this window open.');
  }
}

async function detect() {
  const path = pathInput.value.trim();
  detected = null;
  installBtn.disabled = true;
  detectBox.innerHTML = '';
  if (!path) return;
  detectBox.innerHTML = `<span class="muted small">${esc(T('Checking the file…'))}</span>`;
  const r = await api('/api/detect', { path });
  if (!r.ok) { detectBox.innerHTML = ''; return; }
  detected = r;
  const cls = r.installable ? 'ok' : 'bad';
  detectBox.innerHTML = `<span class="tag ${cls}">${esc(r.label)}</span>
    <span class="muted small">${esc(r.detail)}</span>`;
  installBtn.disabled = !r.installable;
}

function showResult(r) {
  if (r.needs_choice) {
    const choices = r.choices || [];
    modal({
      title: r.title,
      html: `<p>${esc(r.message)}</p>
        <div class="choices">${choices.map((c, i) =>
          `<button class="choice" data-i="${i}">${esc(c.name)}<small>${esc(c.path)}</small></button>`).join('')}</div>`,
      buttons: [{ label: T('Skip'), kind: 'ghost', onClick: closeModal }],
      onOpen: box => {
        $$('.choice', box).forEach(btn => btn.onclick = async () => {
          closeModal();
          await runInstall({ choice: choices[Number(btn.dataset.i)] });
        });
      }
    });
    return;
  }
  if (r.ok) {
    toast(T('Done'), r.message, 'ok');
    pathInput.value = '';
    detectBox.innerHTML = '';
    detected = null;
    installBtn.disabled = true;
  } else {
    modal({
      title: r.title || T('Installation failed'),
      html: `<p>${esc(r.message)}</p>${r.detail ? `<div class="warn-box">${esc(r.detail)}</div>` : ''}`,
      buttons: [{ label: T('Close'), kind: 'primary', onClick: closeModal }]
    });
  }
}

async function runInstall(opts) {
  if (working) return;
  setBusy(true, opts && opts.choice ? T('Finishing up…') : T('Installing…'),
    T('Package operations can take a while. Keep this window open.'));
  const r = await api('/api/install', { path: pathInput.value.trim(), opts: opts || {} });
  setBusy(false);
  if (r.busy) { toast(T('Already busy'), r.message, 'bad'); return; }
  showResult(r);
}

installBtn.onclick = () => runInstall();

/* --- Install-method switcher: swap between "install from file" and
   "download and install". Pure client-side — the download bar below the panels
   keeps running regardless of which panel is showing. --- */
document.querySelectorAll('.view-switch .switch').forEach(btn => {
  btn.addEventListener('click', () => {
    const view = btn.dataset.view;
    document.querySelectorAll('.view-switch .switch').forEach(b =>
      b.classList.toggle('active', b === btn));
    $('#view-file').classList.toggle('hidden', view !== 'file');
    $('#view-download').classList.toggle('hidden', view !== 'download');
  });
});

$('#clear').onclick = () => {
  pathInput.value = '';
  detectBox.innerHTML = '';
  detected = null;
  installBtn.disabled = true;
};

$('#browse').onclick = async () => {
  const r = await api('/api/pick', {});
  if (r.ok && r.path) { pathInput.value = r.path; detect(); }
  else if (r.message) toast(T('No file chooser'), r.message);
};

let timer;
pathInput.addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(detect, 350);
});

/* Drag and drop: browsers only expose the path of a dropped file through
   text/uri-list, which is exactly what we want here. */
const drop = $('#drop');
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault();
  drop.classList.add('dragover');
}));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault();
  drop.classList.remove('dragover');
}));
drop.addEventListener('drop', e => {
  const text = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain');
  const first = text.split(/[\r\n]+/).find(Boolean);
  if (!first) return;
  pathInput.value = first.replace(/^file:\/\//, '').replace(/%20/g, ' ');
  detect();
});

pathInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && detected && detected.installable) runInstall();
});

/* ---------------------------------------------------------------- downloads
   A link is downloaded by the app into the Downloads folder in the background. A bar at
   the bottom tracks every download (pause / continue / stop). When one finishes, SLPM
   tries to detect and install the saved file unless another file is already selected. */

const downloadUrl = $('#download-url');
const downloadBtn = $('#download-btn');
const downloadHint = $('#download-hint');
const downloadBar = $('#download-bar');
const downloadRows = $('#download-rows');
const downloadBarNote = $('#download-bar-note');
const ACTIVE_STATES = new Set(["queued", "running", "paused"]);
/* Downloads already turned into a finished row. Cleared when the user dismisses the
   row, so a job the server still reports is drawn once and not again on every poll. */
const doneIds = new Set();
const failedIds = new Set();

const ICONS = {
  pause: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5h3v14H9zM14 5h3v14h-3z"/></svg>`,
  play: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>`,
  close: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>`,
};

function isValidUrl(u) {
  return /^https?:\/\/[^\s]+$/.test((u || '').trim());
}

function setDownloadHint(msg, cls) {
  downloadHint.innerHTML = msg
    ? `<span class="muted small ${cls || ''}">${esc(msg)}</span>` : '';
}

function syncDownloadBtn() {
  const ok = isValidUrl(downloadUrl.value);
  downloadBtn.disabled = !ok;
  setDownloadHint(
    ok ? T('A valid link starts a background download; SLPM will try to detect and install the file when it finishes unless another file is selected.')
       : T('Enter a link starting with http:// or https://'));
}

downloadUrl.addEventListener('input', syncDownloadBtn);
downloadUrl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && isValidUrl(downloadUrl.value)) startDownload();
});
downloadBtn.onclick = () => { if (isValidUrl(downloadUrl.value)) startDownload(); };

async function startDownload() {
  const url = downloadUrl.value.trim();
  const r = await api('/api/download/start', { url });
  syncDownloadBtn();
  if (!r.ok) {
    toast(T('Download failed'), r.error || r.message, 'bad');
    return;
  }
  downloadBar.classList.remove('hidden');
}

/* Poll the server so progress and state stay live without a websocket. */
let downloadPoll;
function pollDownloads() {
  clearInterval(downloadPoll);
  downloadPoll = setInterval(async () => {
    const r = await api('/api/downloads');
    if (r.ok) renderDownloads(r.downloads || []);
  }, 1000);
}

const STATE_LABEL = {
  queued: T('Waiting…'),
  running: T('Downloading…'),
  paused: T('Paused'),
  done: T('Done'),
  failed: T('Failed'),
  stopped: T('Stopped'),
};

function formatBytes(n) {
  if (!n) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

function renderDownloads(list) {
  downloadBar.classList.toggle('hidden',
    list.length === 0 && doneIds.size === 0 && failedIds.size === 0);

  // Active downloads are driven by the server; done and failed ones become permanent
  // rows (the user dismisses them), stopped ones are dropped.
  const ids = new Set();
  for (const d of list) {
    if (d.state === 'done') {
      if (!doneIds.has(d.id)) { doneIds.add(d.id); renderDone(d); }
      continue;
    }
    if (d.state === 'failed') {
      if (!failedIds.has(d.id)) { failedIds.add(d.id); renderFailed(d); }
      continue;
    }
    if (!ACTIVE_STATES.has(d.state)) continue;   // stopped -> remove
    ids.add(d.id);
    renderActive(d);
  }
  // Remove active rows that the server no longer reports.
  downloadRows.querySelectorAll('.download-row[data-active]').forEach(row => {
    if (!ids.has(row.dataset.active)) row.remove();
  });

  const active = list.filter(d => ACTIVE_STATES.has(d.state));
  downloadBarNote.textContent = active.length
    ? `${active.length} ${T('in progress')}` : '';
}

function makeRow() {
  const row = document.createElement('div');
  row.className = 'download-row';
  row.innerHTML = `
    <div class="download-row-top">
      <div class="spinner small"></div>
      <span class="download-name" tabindex="0"></span>
      <span class="download-meta"></span>
      <div class="download-actions"></div>
    </div>
    <div class="bar"><div class="download-bar-fill"></div></div>`;
  downloadRows.appendChild(row);
  return row;
}

function renderActive(d) {
  let row = downloadRows.querySelector(`.download-row[data-active="${d.id}"]`);
  if (!row) { row = makeRow(); row.dataset.active = d.id; }
  row.querySelector('.spinner').classList.toggle('hidden', d.state !== 'paused');
  row.querySelector('.download-name').textContent = d.filename;
  row.querySelector('.download-actions').innerHTML = '';

  if (d.state === 'paused') {
    const cont = controlBtn(T('Continue'), 'play', d.id, 'resume');
    cont.classList.add('download-resume');
    row.querySelector('.download-actions').appendChild(cont);
  } else {
    const pause = controlBtn(T('Pause'), 'pause', d.id, 'pause');
    row.querySelector('.download-actions').appendChild(pause);
  }
  const close = controlBtn(T('Stop'), 'close', d.id, 'stop');
  row.querySelector('.download-actions').appendChild(close);

  const pct = d.percent;
  row.querySelector('.download-bar-fill').style.width = `${pct}%`;
  row.querySelector('.download-meta').textContent =
    `${formatBytes(d.downloaded)} / ${formatBytes(d.total)} · ${pct}%`;
}

function renderDone(d) {
  const row = document.createElement('div');
  row.className = 'download-row download-done';
  row.innerHTML = `
    <span class="download-check" aria-hidden="true">✓</span>
    <span class="download-name" tabindex="0">${esc(d.filename)}</span>
    <span class="download-meta">${T('Download complete')}</span>
    <div class="download-actions"></div>`;
  const actions = row.querySelector('.download-actions');
  const stop = controlBtn(T('Clear'), 'close', null);
  stop.addEventListener('click', () => { row.remove(); doneIds.delete(d.id); });
  actions.appendChild(stop);
  downloadRows.appendChild(row);
  if (!downloadBar.classList.contains('hidden')) downloadBar.classList.remove('hidden');
  // A finished download stays visible even when another file prevents auto-install.
  if (pathInput && d.path) installSavedFile(d);
}

function renderFailed(d) {
  const row = document.createElement('div');
  row.className = 'download-row download-done download-failed';
  row.innerHTML = `
    <span class="download-check fail" aria-hidden="true">✕</span>
    <span class="download-name" tabindex="0">${esc(d.filename)}</span>
    <span class="download-meta">${esc(d.error || T('The download could not be completed.'))}</span>
    <div class="download-actions"></div>`;
  const actions = row.querySelector('.download-actions');
  const clear = controlBtn(T('Clear'), 'close', null);
  clear.addEventListener('click', () => { row.remove(); failedIds.delete(d.id); });
  actions.appendChild(clear);
  downloadRows.appendChild(row);
}

function controlBtn(label, iconKey, jobId, action, kind) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = `btn icon-btn download-control ${kind ? 'btn-' + kind : ''}`;
  btn.title = label;
  btn.setAttribute('aria-label', label);
  if (iconKey) btn.innerHTML = ICONS[iconKey];
  btn.addEventListener('click', async () => {
    // 'stop' and 'close' both stop a live download; the row drops once the server
    // stops reporting it. A finished row has no jobId, so nothing is called.
    if (!action || !jobId) return;
    await api('/api/download/control', { id: jobId, action });
  });
  return btn;
}

let autoFilledPath = '';
function installSavedFile(d) {
  if (!d.path || !pathInput) return;
  const current = pathInput.value.trim();
  // Auto-installing must not clobber a different file the user has already pointed at:
  // in that case the download is finished but the install is left to them.
  if (current && current !== d.path && current !== autoFilledPath) {
    toast(T('Download complete; another file is already selected, so this file was not installed automatically.'), d.filename, 'ok');
    return;
  }
  autoFilledPath = d.path;
  pathInput.value = d.path;
  detected = null;
  installBtn.disabled = true;
  detect().then(() => {
    if (detected && detected.installable) {
      toast(T('Download ready, installing…'), d.filename, 'ok');
      runInstall();
    } else toast(T('Not installable'), T('This file could not be installed.'), 'bad');
  });
}

pollDownloads();
