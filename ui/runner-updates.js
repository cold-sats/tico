/* How a computer stands against the server's release (backend/runner_versions.py): its version, whether it is
   up to date, updating, behind or too old to work with (its bots are paused), and the last update error.
   Health and Settings > Computers both draw it. */
'use strict';
// `version`: what the computer itself reported; with one, "Version not reported" would contradict it, so an unknown state says nothing.
window.runnerUpdateHtml = function runnerUpdateHtml(update, version) {
  if (!update || !update.state || (update.state === 'unknown' && version)) return '';
  const tone = {current: 'ok', updating: 'waiting', needs_update: 'waiting', incompatible: 'fail'}[update.state] || '';
  const detail = [update.release ? `Tico ${update.release}` : '', update.kind || '', update.update_state === 'pinned' ? 'pinned' : '']
    .filter(Boolean).map(esc).join(' · ');
  const target = update.state === 'needs_update' && update.target ? ` <span class="muted">to ${esc(update.target)}</span>` : '';
  const why = update.state === 'incompatible'
    ? `<div class="err" data-runner-paused>Needs Tico ${esc(update.min_runner)} or later; it takes no work until it updates.</div>` : '';
  const error = update.error ? `<div class="err" data-runner-error>Last update error: ${esc(update.error)}</div>` : '';
  return `<div class="runner-update" data-runner-update="${esc(update.state)}"><span class="pill ${tone}">${esc(update.label)}</span>`
    + `${target} <span class="muted">${detail}</span>${why}${error}</div>`;
};
