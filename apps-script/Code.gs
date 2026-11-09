/**
 * JobEngine — Apps Script (lié au Google Sheets "Pipeline Candidatures (BDD)")
 * Modules : 3 Validation (Web App) · 4 Envoi · 5 Suivi · Récapitulatif email
 *
 * Installation : coller ce fichier + Index.html, exécuter setup() puis setupTriggers(),
 * puis Déployer > Nouveau déploiement > Application Web (exécuter en tant que : moi ; accès : moi uniquement).
 */

const TAB = 'Candidatures', PARAMS = 'Parametres', JOURNAL = 'Journal';
const COLUMNS = ['id','date_detection','source','url','entreprise','titre','lieu','contrat',
  'mots_cles','score','email_contact','date_pub','date_limite','statut','description',
  'adequation','points_forts','contenu_cv','prompt_claude_design','objet_mail','lettre',
  'cv_file_id','date_preparation','date_envoi','thread_id','date_reponse',
  'date_entretien','resultat','erreur','notes'];
const STATUTS = ['Nouveau','À préparer','À envoyer','Test envoyé','Envoyé','Réponse reçue',
  'Entretien','Offre reçue','Refusé','Sans réponse','Candidature manuelle','Ignorée','Erreur envoi'];
const EDITABLE = ['entreprise','email_contact','objet_mail','lettre','notes','date_entretien',
  'resultat','statut','lieu','contrat'];
const DEFAULT_PARAMS = [
  ['mode_test', 'TRUE', 'TRUE = tous les envois partent vers email_test'],
  ['email_test', '', 'Adresse de test (vide = ton adresse)'],
  ['envoi_auto_apres_cv', 'TRUE', 'TRUE = CV déposé + email renseigné → envoi automatique'],
  ['plafond_jour', '15', "Nombre maximum d'envois réels par jour"],
  ['nom_expediteur', 'Paul Cédric TIENE YOMA', 'Nom affiché chez le recruteur'],
  ['nom_fichier_cv', 'CV_Cedric_TIENE.pdf', 'Nom de la pièce jointe'],
  ['heures_recap', '8,18', 'Heures du récapitulatif email (heure Abidjan)'],
  ['email_recap', 'cedrictiene@gmail.com', 'Adresse qui reçoit le récapitulatif (vide = compte du script)'],
  ['zone_recherche', '', 'Localités acceptées, séparées par des virgules (vide = Grand Abidjan, voir config.yaml)'],
  ['frequence_recherche_h', '6', 'Recherche d\'offres toutes les N heures (1 à 24, 0 = pause)'],
  ['relance_jours', '10', 'Jours sans réponse avant suggestion de relance'],
  ['sans_reponse_jours', '30', 'Jours avant passage en "Sans réponse"'],
  ['seuil_generation', '4', 'Score minimum pour la génération IA automatique'],
  ['max_generations_par_run', '12', 'Candidatures préparées par run GitHub'],
  ['dossier_cv_envoyes', '1eFOer572foZIQ_o00k3Aq3rWF0gqzL-q', 'Drive : CV_envoyes'],
  ['dossier_cv', '1tnZHfVizLl4hNa7MS7jeRZJZJmf5IgCO', 'Drive : Base_Profil/CV'],
  ['dossier_lm', '1zqFB3JenZ4WonfF5eWY-KyHGBHaj8fm9', 'Drive : Base_Profil/LM'],
];

// ============================================================ INSTALLATION
function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  PropertiesService.getScriptProperties().setProperty('SHEET_ID', ss.getId());
  ss.setSpreadsheetTimeZone('Africa/Abidjan');

  const c = ss.getSheetByName(TAB) || ss.insertSheet(TAB);
  const head = c.getLastColumn() ? c.getRange(1, 1, 1, c.getLastColumn()).getValues()[0] : [];
  const merged = head.filter(String).concat(COLUMNS.filter(k => head.indexOf(k) < 0));
  c.getRange(1, 1, 1, merged.length).setValues([merged]).setFontWeight('bold').setBackground('#1f3a5f').setFontColor('#fff');
  c.setFrozenRows(1);
  const col = merged.indexOf('statut') + 1;
  c.getRange(2, col, c.getMaxRows() - 1, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(STATUTS, true).setAllowInvalid(false).build());

  const p = ss.getSheetByName(PARAMS) || ss.insertSheet(PARAMS);
  if (p.getLastRow() < 1) p.getRange(1, 1, 1, 3).setValues([['cle', 'valeur', 'description']]).setFontWeight('bold');
  const keys = p.getLastRow() > 1 ? p.getRange(2, 1, p.getLastRow() - 1, 1).getValues().flat() : [];
  const me = Session.getEffectiveUser().getEmail();
  DEFAULT_PARAMS.filter(r => keys.indexOf(r[0]) < 0)
    .forEach(r => p.appendRow(r[0] === 'email_test' ? [r[0], me, r[2]] : r));
  repairParams_();

  const j = ss.getSheetByName(JOURNAL) || ss.insertSheet(JOURNAL);
  if (j.getLastRow() < 1) j.getRange(1, 1, 1, 3).setValues([['date', 'type', 'message']]).setFontWeight('bold');

  const def = ss.getSheetByName('Feuille 1') || ss.getSheetByName('Sheet1');
  if (def && def.getLastRow() === 0 && ss.getSheets().length > 1) ss.deleteSheet(def);
  log_('setup', 'Installation OK');
}

// Paramètres à stocker en texte brut (Sheets convertit sinon « 8,18 » en date du 18 août)
const TEXT_PARAMS = ['heures_recap', 'email_recap', 'zone_recherche', 'email_test', 'dossier_cv', 'dossier_lm', 'dossier_cv_envoyes'];

function heuresRecap_() {
  const v = params_().heures_recap;
  const ok = /^\s*\d{1,2}(\s*[,;]\s*\d{1,2})*\s*$/.test(String(v || ''));
  const h = ok ? String(v).split(/[,;]/).map(x => parseInt(x, 10)).filter(x => x >= 0 && x < 24) : [];
  return h.length ? h : [8, 18];
}

// Remet en texte les paramètres que Sheets aurait convertis (ex. heures_recap devenu une date)
function repairParams_() {
  const sh = sheet_(PARAMS); if (!sh) return;
  const vals = sh.getDataRange().getValues();
  for (let i = 1; i < vals.length; i++) {
    const k = vals[i][0];
    if (TEXT_PARAMS.indexOf(k) < 0) continue;
    const cell = sh.getRange(i + 1, 2);
    cell.setNumberFormat('@');
    if (k === 'heures_recap' && !/^\s*\d{1,2}(\s*[,;]\s*\d{1,2})*\s*$/.test(String(vals[i][1]))) {
      cell.setValue('8,18');
      log_('parametres', 'heures_recap invalide (converti en date par Sheets) → remis à 8,18');
    }
  }
}

function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('processSendQueue').timeBased().everyMinutes(10).create();
  ScriptApp.newTrigger('checkReplies').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('scheduleSourcing').timeBased().everyHours(1).create();
  repairParams_();
  heuresRecap_().forEach(h => ScriptApp.newTrigger('sendDigest').timeBased().atHour(h).everyDays(1).inTimezone('Africa/Abidjan').create());
  log_('setup', 'Déclencheurs créés');
}

// ============================================================ WEB APP
function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('JobEngine')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function api_getData() {
  const rows = readAll_().map(r => {
    r.description = String(r.description || '').slice(0, 6000);
    return r;
  });
  return { rows: rows, params: params_(), statuts: STATUTS, url: ScriptApp.getService().getUrl() };
}

function api_update(id, fields) {
  const r = findById_(id);
  const clean = {};
  Object.keys(fields).forEach(k => { if (EDITABLE.indexOf(k) >= 0) clean[k] = fields[k]; });
  if (clean.statut && STATUTS.indexOf(clean.statut) < 0) throw new Error('Statut inconnu');
  updateRow_(r._row, clean);
  if (clean.statut) log_('statut', `${r.titre} → ${clean.statut}`);
  return true;
}

function api_uploadCv(id, filename, b64) {
  const r = findById_(id);
  const p = params_();
  const blob = Utilities.newBlob(Utilities.base64Decode(b64), 'application/pdf',
    `${Utilities.formatDate(new Date(), tz_(), 'yyyyMMdd')}_${(r.entreprise || r.source)}_${r.titre}`.replace(/[^\w\-]+/g, '_').slice(0, 120) + '.pdf');
  const file = DriveApp.getFolderById(p.dossier_cv_envoyes).createFile(blob);
  if (r.cv_file_id) { try { DriveApp.getFileById(r.cv_file_id).setTrashed(true); } catch (e) {} }
  updateRow_(r._row, { cv_file_id: file.getId() });
  log_('cv', `CV déposé pour ${r.titre} (${filename})`);
  return { id: file.getId(), url: file.getUrl() };
}

function api_listProfil() {
  const p = params_();
  const list = (cat, fid) => {
    const out = [], it = DriveApp.getFolderById(fid).getFiles();
    while (it.hasNext()) {
      const f = it.next();
      out.push({ cat: cat, name: f.getName(), url: f.getUrl(), date: Utilities.formatDate(f.getLastUpdated(), tz_(), 'yyyy-MM-dd'), size: f.getSize() });
    }
    return out;
  };
  return list('CV', p.dossier_cv).concat(list('LM', p.dossier_lm)).sort((a, b) => b.date.localeCompare(a.date));
}

function api_uploadProfil(cat, filename, mime, b64) {
  const p = params_();
  const fid = cat === 'LM' ? p.dossier_lm : p.dossier_cv;
  DriveApp.getFolderById(fid).createFile(Utilities.newBlob(Utilities.base64Decode(b64), mime, filename));
  log_('profil', `${cat} ajouté : ${filename}`);
  return api_listProfil();
}

function api_saveParams(obj) {
  const sh = sheet_(PARAMS), vals = sh.getDataRange().getValues();
  for (let i = 1; i < vals.length; i++) {
    if (Object.prototype.hasOwnProperty.call(obj, vals[i][0])) {
      const cell = sh.getRange(i + 1, 2);
      if (TEXT_PARAMS.indexOf(vals[i][0]) >= 0) cell.setNumberFormat('@');   // évite que « 8,18 » devienne une date
      cell.setValue(obj[vals[i][0]]);
    }
  }
  if ('heures_recap' in obj) setupTriggers();
  log_('parametres', 'Paramètres mis à jour');
  return params_();
}

function api_journal() {
  const sh = sheet_(JOURNAL), n = sh.getLastRow();
  if (n < 2) return [];
  const start = Math.max(2, n - 199);
  return sh.getRange(start, 1, n - start + 1, 3).getDisplayValues().reverse();
}

function api_runSendNow() { processSendQueue(); return api_getData(); }
function api_runSourcingNow() { dispatchSourcing_('manuel'); return api_getData(); }
function api_runRepliesNow() { checkReplies(); return api_getData(); }

// ============================================================ MODULE 1 — PLANIFICATION DE LA RECHERCHE
// Le tableau de bord pilote la fréquence : ce déclencheur horaire lance le workflow GitHub
// quand le délai « frequence_recherche_h » est écoulé. Jeton GitHub : propriété de script GITHUB_TOKEN.
// Dépôt GitHub qui exécute la recherche : propriété de script GITHUB_REPO (« propriétaire/dépôt »), sinon cette valeur
const GITHUB_REPO = PropertiesService.getScriptProperties().getProperty('GITHUB_REPO') || 'Tiene1/job-sourcing-ci',
      GITHUB_WORKFLOW = 'sourcing.yml';

function scheduleSourcing() {
  const h = Number(params_().frequence_recherche_h || 6);
  if (!(h > 0)) return;                                   // 0 = recherche en pause
  const props = PropertiesService.getScriptProperties();
  const last = Number(props.getProperty('LAST_SOURCING') || 0);
  if (Date.now() - last >= h * 3600000 - 5 * 60000) dispatchSourcing_('planifié');   // marge 5 min
}

function dispatchSourcing_(origine) {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Jeton GitHub manquant : ajoutez la propriété de script GITHUB_TOKEN (Paramètres du projet Apps Script).');
  const res = UrlFetchApp.fetch(`https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
    payload: JSON.stringify({ ref: 'main' }),
  });
  if (res.getResponseCode() !== 204) {
    log_('recherche', `❌ Lancement ${origine} refusé par GitHub (HTTP ${res.getResponseCode()}) : ${res.getContentText().slice(0, 200)}`);
    throw new Error('GitHub a refusé le lancement (HTTP ' + res.getResponseCode() + '). Vérifiez le jeton GITHUB_TOKEN.');
  }
  props.setProperty('LAST_SOURCING', String(Date.now()));
  log_('recherche', `🔎 Recherche d'offres lancée (${origine})`);
}

function testGithubToken() { dispatchSourcing_('test'); }   // à exécuter une fois depuis l'éditeur

// ============================================================ MODULE 4 — ENVOI
function processSendQueue() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return;
  try {
    const p = params_(), rows = readAll_(), now = new Date();
    const test = String(p.mode_test).toUpperCase() === 'TRUE';
    const today = Utilities.formatDate(now, tz_(), 'yyyy-MM-dd');
    let sentToday = rows.filter(r => String(r.date_envoi).indexOf(today) === 0).length;
    const already = new Set(rows.filter(r => r.statut === 'Envoyé')
      .map(r => (String(r.email_contact) + '|' + String(r.titre)).toLowerCase()));

    rows.filter(r => r.statut === 'À envoyer').forEach(r => {
      if (!test && sentToday >= Number(p.plafond_jour || 15)) return;   // reste en file pour demain
      const errs = [];
      const email = String(r.email_contact || '').trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) errs.push('email destinataire invalide');
      if (!String(r.objet_mail).trim()) errs.push('objet vide');
      if (String(r.lettre).trim().length < 100) errs.push('lettre vide ou trop courte');
      if (already.has((email + '|' + r.titre).toLowerCase())) errs.push('déjà envoyé à cette adresse pour ce poste');
      let blob = null;
      if (!r.cv_file_id) errs.push('CV non déposé');
      else {
        try {
          const f = DriveApp.getFileById(r.cv_file_id);
          if (f.getMimeType() !== 'application/pdf') errs.push('le CV doit être un PDF');
          blob = f.getBlob().setName(p.nom_fichier_cv || 'CV.pdf');
        } catch (e) { errs.push('CV introuvable sur Drive'); }
      }
      if (errs.length) {
        updateRow_(r._row, { statut: 'Erreur envoi', erreur: errs.join(' ; ') });
        log_('envoi', `❌ ${r.titre} : ${errs.join(' ; ')}`);
        return;
      }
      const to = test ? (p.email_test || Session.getEffectiveUser().getEmail()) : email;
      const subject = (test ? '[TEST] ' : '') + r.objet_mail;
      const body = (test ? `[MODE TEST — destinataire réel : ${email}]\n\n` : '') + r.lettre;
      const msg = GmailApp.createDraft(to, subject, body, { attachments: [blob], name: p.nom_expediteur }).send();
      const stamp = Utilities.formatDate(new Date(), tz_(), 'yyyy-MM-dd HH:mm');
      if (test) {
        updateRow_(r._row, { statut: 'Test envoyé', erreur: '', notes: `Test envoyé à ${to} le ${stamp}` });
      } else {
        sentToday++;
        updateRow_(r._row, { statut: 'Envoyé', date_envoi: stamp, thread_id: msg.getThread().getId(), erreur: '' });
        already.add((email + '|' + r.titre).toLowerCase());
      }
      log_('envoi', `✅ ${test ? '[TEST] ' : ''}${r.titre} → ${to}`);
    });
  } finally { lock.releaseLock(); }
}

// ============================================================ MODULE 5 — SUIVI
function checkReplies() {
  const p = params_(), rows = readAll_(), me = Session.getEffectiveUser().getEmail().toLowerCase();
  const now = new Date();
  rows.filter(r => r.statut === 'Envoyé' && r.thread_id).forEach(r => {
    let thread;
    try { thread = GmailApp.getThreadById(r.thread_id); } catch (e) { return; }
    if (!thread) return;
    const replies = thread.getMessages().filter(m => m.getFrom().toLowerCase().indexOf(me) < 0);
    if (replies.length) {
      const last = replies[replies.length - 1];
      const from = last.getFrom().toLowerCase();
      const txt = (last.getSubject() + ' ' + last.getPlainBody()).toLowerCase();
      let st = 'Réponse reçue', err = '';
      if (/mailer-daemon|postmaster|delivery status|undeliverable|non remis/.test(from + txt)) { st = 'Erreur envoi'; err = 'Adresse rejetée (mail non remis)'; }
      else if (/entretien|rencontrer|convocation|disponibilit|interview|test technique/.test(txt)) st = 'Entretien';
      else if (/regret|malheureusement|pas été retenu|pas retenu|ne pouvons donner suite|autre candidat|candidature n'a pas/.test(txt)) st = 'Refusé';
      updateRow_(r._row, { statut: st, date_reponse: Utilities.formatDate(last.getDate(), tz_(), 'yyyy-MM-dd HH:mm'), erreur: err });
      log_('suivi', `📩 ${r.titre} → ${st}`);
      return;
    }
    const days = (now - parseDate_(r.date_envoi)) / 86400000;
    if (days >= Number(p.sans_reponse_jours || 30)) {
      updateRow_(r._row, { statut: 'Sans réponse' });
      log_('suivi', `⌛ ${r.titre} → Sans réponse`);
    }
  });
}

// ============================================================ RÉCAPITULATIF EMAIL
function sendDigest() {
  const p = params_(), rows = readAll_(), now = new Date();
  const by = s => rows.filter(r => r.statut === s);
  const aPreparer = by('À préparer'), erreurs = by('Erreur envoi'), reponses = by('Réponse reçue');
  const aRelancer = by('Envoyé').filter(r => (now - parseDate_(r.date_envoi)) / 86400000 >= Number(p.relance_jours || 10));
  const urgent = aPreparer.filter(r => { const d = parseDate_(r.date_limite); return d && (d - now) / 86400000 <= 3; });
  const total = aPreparer.length + erreurs.length + reponses.length + aRelancer.length;
  const journal = sheet_(JOURNAL).getDataRange().getDisplayValues();
  const dernier = t => { for (let i = journal.length - 1; i > 0; i--) if (journal[i][1] === t) return journal[i][0] + ' — ' + journal[i][2]; return 'aucune'; };

  const url = ScriptApp.getService().getUrl();
  const top = aPreparer.sort((a, b) => (Number(b.adequation) || 0) - (Number(a.adequation) || 0)).slice(0, 5);
  const li = r => `<li><b>${esc_(r.titre)}</b> — ${esc_(r.entreprise || r.source)} · adéquation ${r.adequation || '?'}%${r.date_limite ? ' · limite ' + esc_(r.date_limite) : ''}</li>`;
  const html = `<div style="font-family:Arial,sans-serif;max-width:600px">
    <h2 style="color:#1f3a5f">JobEngine — ton point du jour</h2>
    <table style="border-collapse:collapse;width:100%">
      ${[['📝 À préparer', aPreparer.length], ['⏰ Expirent sous 3 jours', urgent.length], ['📩 Réponses à traiter', reponses.length],
         ['🔁 À relancer', aRelancer.length], ['❌ Erreurs d’envoi', erreurs.length]]
        .map(x => `<tr><td style="padding:6px;border-bottom:1px solid #eee">${x[0]}</td><td style="padding:6px;border-bottom:1px solid #eee;text-align:right"><b>${x[1]}</b></td></tr>`).join('')}
    </table>
    ${top.length ? `<h3>Meilleures offres à préparer</h3><ul>${top.map(li).join('')}</ul>` : ''}
    ${urgent.length ? `<h3 style="color:#c0392b">Urgent</h3><ul>${urgent.map(li).join('')}</ul>` : ''}
    <p><a href="${url}" style="background:#1f3a5f;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">Ouvrir le tableau de bord</a></p>
    ${String(p.mode_test).toUpperCase() === 'TRUE' ? '<p style="color:#c0392b">⚠️ Mode test actif : aucun email ne part chez les recruteurs.</p>' : ''}
    ${!total ? '<p>Rien à traiter pour l’instant : le pipeline tourne normalement.</p>' : ''}
    <p style="color:#666;font-size:12px">Dernière recherche : ${esc_(dernier('sourcing'))}<br>Dernier envoi : ${esc_(dernier('envoi'))}</p>
  </div>`;
  GmailApp.sendEmail(String(p.email_recap || '').trim() || Session.getEffectiveUser().getEmail(),
    `JobEngine : ${aPreparer.length} à préparer, ${reponses.length} réponse(s)`,
    `Ouvre le tableau de bord : ${url}`, { htmlBody: html, name: 'JobEngine' });
  log_('recap', `Récap envoyé (${total} éléments) → ${String(p.email_recap || '').trim() || 'compte du script'}`);
}

// ============================================================ OUTILS
function ss_() { return SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SHEET_ID') || SpreadsheetApp.getActiveSpreadsheet().getId()); }
function sheet_(name) { return ss_().getSheetByName(name); }
function tz_() { return 'Africa/Abidjan'; }

function readAll_() {
  const v = sheet_(TAB).getDataRange().getValues();
  const h = v.shift();
  return v.map((row, i) => {
    const o = { _row: i + 2 };
    h.forEach((k, j) => { o[k] = row[j] instanceof Date ? Utilities.formatDate(row[j], tz_(), 'yyyy-MM-dd HH:mm') : row[j]; });
    return o;
  }).filter(o => o.id);
}

function findById_(id) {
  const r = readAll_().find(x => String(x.id) === String(id));
  if (!r) throw new Error('Candidature introuvable : ' + id);
  return r;
}

function updateRow_(row, obj) {
  const sh = sheet_(TAB), h = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  Object.keys(obj).forEach(k => { const c = h.indexOf(k); if (c >= 0) sh.getRange(row, c + 1).setValue(obj[k]); });
}

function params_() {
  const sh = sheet_(PARAMS);
  if (!sh) return {};
  const o = {};
  sh.getDataRange().getValues().slice(1).forEach(r => { if (r[0]) o[r[0]] = String(r[1]); });
  return o;
}

function log_(type, msg) {
  const sh = sheet_(JOURNAL);
  if (sh) sh.appendRow([Utilities.formatDate(new Date(), tz_(), 'yyyy-MM-dd HH:mm'), type, String(msg).slice(0, 2000)]);
}

function parseDate_(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  const t = String(s);
  let m = t.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1]);
  m = t.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
  const d = new Date(t);
  return isNaN(d) ? null : d;
}

function esc_(s) { return String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
