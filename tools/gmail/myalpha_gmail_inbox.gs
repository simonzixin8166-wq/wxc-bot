/**
 * MyAlpha · Gmail -> private textpack inbox (Owner 2026-11-17).
 * Runs in the Owner's OWN Google account (Apps Script). Every new mail labelled "MyAlpha" with a .zip attachment
 * (the Owner's own "文学城每日整理" export) is copied to the PRIVATE repo inbox/gmail/; the Telegram bot then
 * ingests it exactly like a zip forwarded by hand and replies in Telegram. The mail is then labelled "MyAlpha/已收录".
 *
 * Setup (once):
 *   Project Settings -> Script properties:  GH_TOKEN = <fine-grained token, only myalpha-s2-textpack, Contents: read/write>
 *                                            GH_REPO  = simonzixin8166-wq/myalpha-s2-textpack
 *   Triggers -> add: run "pushNewMail", time-driven, every 15 minutes.
 * The token never leaves this script's properties; do not paste it anywhere else.
 */
var LABEL_IN = 'MyAlpha';
var LABEL_DONE = 'MyAlpha/已收录';
var MAX_BYTES = 3 * 1024 * 1024;   // same limit as a Telegram forward

function pushNewMail() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('GH_TOKEN'), repo = props.getProperty('GH_REPO');
  if (!token || !repo) throw new Error('GH_TOKEN / GH_REPO not set in Script properties');
  var done = GmailApp.getUserLabelByName(LABEL_DONE) || GmailApp.createLabel(LABEL_DONE);
  var threads = GmailApp.search('label:' + LABEL_IN + ' -label:' + LABEL_DONE.replace('/', '-') + ' has:attachment newer_than:14d', 0, 20);
  threads.forEach(function (t) {
    var ok = true;
    t.getMessages().forEach(function (m) {
      var ts = Utilities.formatDate(m.getDate(), 'UTC', "yyyyMMdd'T'HHmmss'Z'");
      m.getAttachments().forEach(function (a) {
        var name = a.getName();
        if (!/\.zip$/i.test(name)) return;
        if (a.getSize() > MAX_BYTES) { ok = false; Logger.log('too large: ' + name); return; }
        var safe = name.replace(/[^0-9A-Za-z._\-一-鿿]/g, '_');
        var path = 'inbox/gmail/' + ts + '_' + m.getId() + '_' + safe;
        var res = UrlFetchApp.fetch('https://api.github.com/repos/' + repo + '/contents/' + encodeURI(path), {
          method: 'put', muteHttpExceptions: true, contentType: 'application/json',
          headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
          payload: JSON.stringify({ message: 'gmail inbox ' + ts, content: Utilities.base64Encode(a.getBytes()) })
        });
        var code = res.getResponseCode();
        if (code !== 201 && code !== 422) { ok = false; Logger.log('GitHub ' + code + ' ' + res.getContentText()); }  // 422 = already uploaded
      });
    });
    if (ok) t.addLabel(done);
  });
}
