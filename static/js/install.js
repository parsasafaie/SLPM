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
