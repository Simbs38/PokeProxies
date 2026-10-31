/**
 * Pokédex Proxies — collection store on a Google Sheet.
 *
 * Two readable tabs hold the collection, one row per Pokémon form / per card: "Gen 1" and
 * "30th Celebration". Only the website writes them; every save rewrites both. The old "state"
 * tab (one JSON blob) is handed to the site once to fill them, then left alone as a rollback
 * point. See DEPLOY.md.
 */

// Who may read or write this Sheet. The website signs the user in with Google and sends the
// resulting ID token; nothing else opens the door, so a leaked /exec URL on its own is useless.
const CLIENT_ID = '1081036062887-svjpkvhkiut32tou6cmfgiic1lr4gqea.apps.googleusercontent.com';

// The allow list lives in Project Settings → Script Properties → ALLOWED (comma-separated), so
// re-pasting this file never wipes it and your address stays out of the public repo.
const PROPS = PropertiesService.getScriptProperties();
const allowed_ = () => (PROPS.getProperty('ALLOWED') || '').split(/[\s,]+/).filter(Boolean);

const TABS = {
  gen1:  { name: 'Gen 1',            head: ['Pokémon', 'Owned', 'Card IDs', 'Favourite'] },
  anniv: { name: '30th Celebration', head: ['Pokémon', 'Owned', 'Card ID', 'Number', 'Rarity', 'Section'] },
};
const LEGACY = 'state';
const CHUNK = 40000;               // a Sheets cell tops out at 50k chars, so the JSON is split
const STALE = 'site updated — reload the page';

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

/** Google's tokeninfo does the signature and expiry work; we check who it is. */
function verify_(tok) {
  if (!tok) return null;
  const r = UrlFetchApp.fetch(
    'https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(tok),
    { muteHttpExceptions: true });
  if (r.getResponseCode() !== 200) return null;          // expired, malformed or forged
  const p = JSON.parse(r.getContentText());
  if (p.aud !== CLIENT_ID) return null;                  // token minted for some other site
  if (String(p.email_verified) !== 'true') return null;
  return allowed_().indexOf(p.email) >= 0 ? p.email : null;
}

function guard_(tok) {
  if (!allowed_().length) return 'set ALLOWED in Script Properties';
  return verify_(tok) ? '' : 'sign in with Google';
}

// ---- the tabs ----

function rows_(s) {
  if (!s || s.getLastRow() < 2) return [];
  return s.getRange(2, 1, s.getLastRow() - 1, s.getLastColumn()).getDisplayValues();
}

function writeTab_(ss, t, rows) {
  let s = ss.getSheetByName(t.name);
  if (!s) {                                          // first save: header row, frozen and bold
    s = ss.insertSheet(t.name);
    s.getRange(1, 1, 1, t.head.length).setValues([t.head]).setFontWeight('bold');
    s.setFrozenRows(1);
    s.setColumnWidth(1, 180);
    s.setColumnWidth(3, 320);
  }
  const old = s.getLastRow();
  if (old > 1) s.getRange(2, 1, old - 1, t.head.length).clearContent();
  if (!rows.length) return;
  // plain text, or Sheets reads "4/102" as a date and a bare card number as a number
  s.getRange(2, 1, rows.length, t.head.length).setNumberFormat('@')
    .setValues(rows.map(r => t.head.map((_, i) => r[i] ?? '')));
}

// ---- the old one-blob store: read once by the new site, still served to a cached old site ----

function legacyGet_(ss) {
  const s = ss.getSheetByName(LEGACY);
  if (!s) return { ok: true, state: null, updated: 0 };
  const raw = s.getRange(1, 1, Math.max(s.getLastRow(), 1), 1).getValues().map(r => r[0]).join('');
  return { ok: true, state: raw ? JSON.parse(raw) : null, updated: Number(s.getRange('C1').getValue()) || 0 };
}

function legacyPost_(ss, body) {
  const s = ss.getSheetByName(LEGACY) || ss.insertSheet(LEGACY), state = body.state || {};
  const str = JSON.stringify(state);
  const parts = str.match(new RegExp('[\\s\\S]{1,' + CHUNK + '}', 'g')) || [''];
  s.getRange(1, 1, Math.max(s.getLastRow(), parts.length), 1).clearContent();
  parts.forEach((p, i) => s.getRange(i + 1, 1).setValue(p));
  s.getRange('C1').setValue(body.updated || Date.now());
  s.getRange('D1').setValue(new Date().toISOString());
  s.getRange('C2').setValue((state.owned || []).length);   // readable at a glance
  s.getRange('D2').setValue('proxies done');
  s.getRange('C3').setValue((state.have || []).length);
  s.getRange('D3').setValue('TCG cards owned');
  s.getRange('C4').setValue(Object.keys(state.favs || {}).length);
  s.getRange('D4').setValue('favourite prints');
}

// ---- web app ----

function doGet(e) {
  const err = guard_(e.parameter.idToken);
  if (err) return json_({ ok: false, error: err });
  const ss = SpreadsheetApp.getActive(), filled = ss.getSheetByName(TABS.gen1.name);
  if (e.parameter.v !== '2') return json_(filled ? { ok: false, error: STALE } : legacyGet_(ss));
  if (!filled) {                                     // first run: the old JSON fills the tabs once
    const old = legacyGet_(ss);
    return json_({ ok: true, tabs: null, legacy: old.state, updated: old.updated });
  }
  const tabs = {};
  for (const k in TABS) tabs[k] = rows_(ss.getSheetByName(TABS[k].name));
  return json_({ ok: true, tabs, updated: Number(PROPS.getProperty('updated')) || 0 });
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents || '{}') } catch (err) { body = {} }
  const err = guard_(body.idToken);
  if (err) return json_({ ok: false, error: err });

  const ss = SpreadsheetApp.getActive();
  const lock = LockService.getScriptLock();          // two devices saving at once
  lock.waitLock(10000);
  try {
    if (body.v !== 2) {                              // old site: fine until the tabs exist
      if (ss.getSheetByName(TABS.gen1.name)) return json_({ ok: false, error: STALE });
      legacyPost_(ss, body);
    } else {
      for (const k in TABS) writeTab_(ss, TABS[k], (body.tabs || {})[k] || []);
      PROPS.setProperty('updated', String(body.updated || Date.now()));
    }
  } finally {
    lock.releaseLock();
  }
  return json_({ ok: true, updated: body.updated });
}
