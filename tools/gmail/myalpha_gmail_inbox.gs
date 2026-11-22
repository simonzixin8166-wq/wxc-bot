/**
 * MyAlpha · Gmail -> private textpack inbox (Owner 2026-11-17; newsletters 2026-11-22).
 * Runs in the Owner's OWN Google account (Apps Script). Two kinds of mail are copied to the PRIVATE repo inbox/gmail/;
 * the Telegram bot then ingests each file exactly like a file forwarded by hand and replies in Telegram:
 *   1. label "MyAlpha" with a .zip or .md attachment: the Owner's own "文学城每日整理" / "文学城博主整理" exports;
 *   2. label "MyAlpha/Newsletter": newsletters the Owner subscribes to himself (e.g. Substack). The mail body is saved
 *      as one .md article with its web link (原文链接), date and sender, and goes through the forwarded-article path.
 * Each processed mail is then labelled "MyAlpha/已收录". Full text goes only to the private repo; the public index
 * keeps title, <=360-char excerpt, link and hash (charter 2026-11-09). No web page is fetched by this script.
 *
 * Setup (once):
 *   Project Settings -> Script properties:  GH_TOKEN = <fine-grained token, only myalpha-s2-textpack, Contents: read/write>
 *                                            GH_REPO  = simonzixin8166-wq/myalpha-s2-textpack
 *   Triggers -> add: run "pushNewMail", time-driven, every 15 minutes.
 *   Gmail filters: daily exports -> label MyAlpha; each newsletter sender -> label MyAlpha/Newsletter.
 * The token never leaves this script's properties; do not paste it anywhere else.
 */
var LABEL_IN = 'MyAlpha';
var LABEL_NEWS = 'MyAlpha/Newsletter';
var LABEL_DONE = 'MyAlpha/已收录';
var MAX_BYTES = 3 * 1024 * 1024;   // same limit as a Telegram forward

function upload_(token, repo, path, bytes, ts) {
  var res = UrlFetchApp.fetch('https://api.github.com/repos/' + repo + '/contents/' + encodeURI(path), {
    method: 'put', muteHttpExceptions: true, contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ message: 'gmail inbox ' + ts, content: Utilities.base64Encode(bytes) })
  });
  var code = res.getResponseCode();
  if (code !== 201 && code !== 422) { Logger.log('GitHub ' + code + ' ' + res.getContentText()); return false; }  // 422 = already uploaded
  return true;
}

function webLink_(text) {
  var m = text.match(/View (?:this post|it|this email) (?:on the web|in (?:your )?browser)[^h]*(https?:\/\/\S+)/i)
       || text.match(/(https?:\/\/[a-z0-9-]+\.substack\.com\/p\/[^\s?#)>\]]+)/i)
       || text.match(/(https?:\/\/[^\s)>\]]+\/p\/[^\s?#)>\]]+)/i);
  return m ? m[1].replace(/[)>\].,]+$/, '') : null;
}

function newsletterMd_(m) {
  var body = m.getPlainBody() || '';
  var link = webLink_(body);
  var cut = body.search(/\n(?:Unsubscribe|取消訂閱|取消订阅) https?:/i);   // drop the footer with the unsubscribe token
  if (cut > 0) body = body.substring(0, cut);
  var when = Utilities.formatDate(m.getDate(), 'UTC', 'yyyy-MM-dd HH:mm');
  return { link: link, md: '# ' + m.getSubject() + '\n' +
    '- 原文链接：' + (link || '') + '\n' +
    '- 发布时间：' + when + '\n' +
    '- 发件人：' + m.getFrom().replace(/<[^>]*>/, '').trim() + '\n' +
    '- 来源：Owner 自己订阅的邮件（Gmail）\n' +
    '---\n' + body.trim() + '\n' };
}

function pushNewMail() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('GH_TOKEN'), repo = props.getProperty('GH_REPO');
  if (!token || !repo) throw new Error('GH_TOKEN / GH_REPO not set in Script properties');
  var done = GmailApp.getUserLabelByName(LABEL_DONE) || GmailApp.createLabel(LABEL_DONE);
  var doneQ = ' -label:' + LABEL_DONE.replace('/', '-') + ' newer_than:14d';

  // 1. exports: .zip / .md attachments
  GmailApp.search('label:' + LABEL_IN + doneQ + ' has:attachment', 0, 20).forEach(function (t) {
    var ok = true;
    t.getMessages().forEach(function (m) {
      var ts = Utilities.formatDate(m.getDate(), 'UTC', "yyyyMMdd'T'HHmmss'Z'");
      m.getAttachments().forEach(function (a) {
        var name = a.getName();
        if (!/\.(zip|md)$/i.test(name)) return;
        if (a.getSize() > MAX_BYTES) { ok = false; Logger.log('too large: ' + name); return; }
        var safe = name.replace(/[^0-9A-Za-z._\-一-鿿]/g, '_');
        if (!upload_(token, repo, 'inbox/gmail/' + ts + '_' + m.getId() + '_' + safe, a.getBytes(), ts)) ok = false;
      });
    });
    if (ok) t.addLabel(done);
  });

  // 2. newsletters: the mail body as one .md article (with its web link)
  GmailApp.search('label:' + LABEL_NEWS.replace('/', '-') + doneQ, 0, 20).forEach(function (t) {
    var ok = true;
    t.getMessages().forEach(function (m) {
      var ts = Utilities.formatDate(m.getDate(), 'UTC', "yyyyMMdd'T'HHmmss'Z'");
      var n = newsletterMd_(m);
      if (!n.link) { Logger.log('no web link, skipped: ' + m.getSubject()); return; }
      var bytes = Utilities.newBlob(n.md, 'text/markdown').getBytes();
      if (bytes.length > MAX_BYTES) { ok = false; Logger.log('too large: ' + m.getSubject()); return; }
      if (!upload_(token, repo, 'inbox/gmail/' + ts + '_' + m.getId() + '_newsletter.md', bytes, ts)) ok = false;
    });
    if (ok) t.addLabel(done);
  });
}
