/**
 * Pokédex Proxies — collection store on a Google Sheet.
 *
 * Holds one JSON blob (your proxies done / cards owned / favourites) and hands it
 * back to any device that knows the passphrase. See DEPLOY.md for the 5 steps.
 */

const PASS = 'change-me';          // <- set this, then paste the same one in the website
const SHEET = 'state';
const CHUNK = 40000;               // a Sheets cell tops out at 50k chars, so the JSON is split

function sheet_() {
  const ss = SpreadsheetApp.getActive();
  return ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function read_(s) {
  const last = Math.max(s.getLastRow(), 1);
  return s.getRange(1, 1, last, 1).getValues().map(r => r[0]).join('');
}

function write_(s, str) {
  const parts = str.match(new RegExp('[\\s\\S]{1,' + CHUNK + '}', 'g')) || [''];
  s.getRange(1, 1, Math.max(s.getLastRow(), parts.length), 1).clearContent();
  parts.forEach((p, i) => s.getRange(i + 1, 1).setValue(p));
}

function doGet(e) {
  const s = sheet_();
  if ((e.parameter.pass || '') !== PASS) return json_({ ok: false, error: 'wrong passphrase' });
  const raw = read_(s);
  return json_({
    ok: true,
    state: raw ? JSON.parse(raw) : null,
    updated: Number(s.getRange('C1').getValue()) || 0,
  });
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents || '{}') } catch (err) { body = {} }
  if ((body.pass || '') !== PASS) return json_({ ok: false, error: 'wrong passphrase' });

  const s = sheet_(), state = body.state || {};
  const lock = LockService.getScriptLock();          // two devices saving at once
  lock.waitLock(10000);
  try {
    write_(s, JSON.stringify(state));
    s.getRange('C1').setValue(body.updated || Date.now());
    s.getRange('D1').setValue(new Date().toISOString());
    s.getRange('C2').setValue((state.owned || []).length);   // readable at a glance
    s.getRange('D2').setValue('proxies done');
    s.getRange('C3').setValue((state.have || []).length);
    s.getRange('D3').setValue('TCG cards owned');
    s.getRange('C4').setValue(Object.keys(state.favs || {}).length);
    s.getRange('D4').setValue('favourite prints');
  } finally {
    lock.releaseLock();
  }
  return json_({ ok: true, updated: body.updated });
}
