/* ui/app/markdown.js — safeMd: untrusted Markdown rendered to safe HTML
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// Issue attachments are untrusted text. Render a small Markdown vocabulary, discard active
// content and attributes, and proxy bucket images through the authenticated hub route.
const SAFE_MD_TAGS = new Set(['P','BR','HR','H1','H2','H3','H4','H5','H6','STRONG','EM','DEL','UL','OL','LI','BLOCKQUOTE','PRE','CODE','TABLE','THEAD','TBODY','TR','TH','TD','A','IMG']);
const DROP_MD_TAGS = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','FORM','INPUT','BUTTON','TEXTAREA','SELECT','OPTION','LINK','META']);
// This hub's own address (the page's, or the public one bots write in links).
function hubUrl(url) {
  return [location.origin, publicUrl()].some(o => { try { return new URL(o).host === url.host; } catch { return false; } });
}
// A route of the app (#/...) or a task (/tasks/<id>, which the task link handler opens), not a file or the API.
const hubPageUrl = url => hubUrl(url) && (url.hash.startsWith('#/') || /^\/tasks?\/[A-Za-z0-9-]{8,80}\/?$/.test(url.pathname));
function safeMd(s, options = {}) {
  const tpl = document.createElement('template');
  try { tpl.innerHTML = marked.parse(String(s ?? '')); }
  catch { return `<div class="plain-message">${esc(s)}</div>`; }
  for (const el of [...tpl.content.querySelectorAll('*')]) {
    if (!el.parentNode) continue;
    if (!SAFE_MD_TAGS.has(el.tagName)) {
      if (DROP_MD_TAGS.has(el.tagName)) el.remove();
      else el.replaceWith(...el.childNodes);
      continue;
    }
    const allowedAttrs = el.tagName === 'A' ? new Set(['href','title'])
      : el.tagName === 'IMG' ? new Set(['src','alt','title']) : new Set();
    if (options.documentImages && /^H[1-6]$/.test(el.tagName)) allowedAttrs.add('id');
    for (const attr of [...el.attributes]) if (!allowedAttrs.has(attr.name.toLowerCase())) el.removeAttribute(attr.name);
    if (el.tagName === 'A') {
      const href = el.getAttribute('href') || '';
      try {
        // A path on a bot's Mac (`/Users/...`) or a raw bucket URI would resolve against this
        // origin and look clickable while leading nowhere. Files reach humans as `/api/v2/files/<id>`
        // (`hub task attach`); only that root-relative form and hash routes are in-app links.
        if (/^s3:\/\//i.test(href) || (href.startsWith('/') && !href.startsWith('/api/'))) throw new Error('unreachable link');
        const url = new URL(href, location.href);
        if (!['http:','https:','mailto:'].includes(url.protocol)) throw new Error('unsafe link');
        el.setAttribute('href', href); el.setAttribute('rel', 'noopener');
        // A page of this hub opens in place; in the desktop app a new window would go nowhere.
        if (url.protocol !== 'mailto:' && !hubPageUrl(url)) el.setAttribute('target', '_blank');
        if (options.shortLinks) shortLink(el, href);
      } catch { el.removeAttribute('href'); }
    }
    if (el.tagName === 'IMG') {
      let src = el.getAttribute('src') || '';
      if (/^s3:\/\//i.test(src)) src = s3url(src);
      try {
        const url = new URL(src, location.href);
        // Linked images show by default (not proxied): any https picture, or one of this server's files.
        if (!['http:','https:'].includes(url.protocol) || (url.origin !== location.origin && url.protocol !== 'https:')) throw new Error('unsafe image');
        el.setAttribute('src', src); el.setAttribute('loading', 'lazy'); el.setAttribute('decoding', 'async');
        if (url.origin !== location.origin) el.setAttribute('referrerpolicy', 'no-referrer');
      } catch { el.remove(); }
    }
  }
  return tpl.innerHTML;
}
// A pull request or an issue in a bot's reply, as the one thing
// anyone needs from it: a small mark saying which and its number, the full URL in the tooltip
// (#524, after bot-desk). Link text the bot chose on purpose stays; a bare URL is replaced.
function shortRef(href) {
  let m = /^https?:\/\/github\.com\/[\w.-]+\/([\w.-]+)\/(pull|issues)\/(\d+)/i.exec(href);
  if (m) return {kind: m[2] === 'pull' ? 'pr' : 'issue', label: '#' + m[3], title: `${m[1]} ${m[2] === 'pull' ? 'pull request' : 'issue'} #${m[3]}`};
  return null;
}
function shortLink(a, href) {
  const ref = shortRef(href); if (!ref) return;
  const text = a.textContent.trim();
  a.className = 'ref ref-' + ref.kind;
  a.title = ref.title + '\n' + href;
  if (!text || text === href || /^https?:\/\//i.test(text)) a.textContent = ref.label;
}
// The same Markdown vocabulary flattened to one plain line, for previews and summaries that get a
// single row and no room to render: headings, emphasis, lists, tables and links become their text.
function plainMd(s) {
  return String(s ?? '')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')                                     // images -> alt
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')                                      // links -> text
    .split('\n')
    .map(l => l.replace(/^\s*(?:```|~~~)\S*\s*$/, '')                             // fence markers
               .replace(/^\s*>+\s?/, '')                                          // blockquote
               .replace(/^\s*#{1,6}(\s+|$)/, '')                                  // heading markers
               .replace(/^\s*(?:[-*+]|\d+[.)])\s+/, ''))                          // list markers
    .filter(l => !/^\s*(?:[-*_]\s*){3,}$/.test(l))                                // horizontal rules
    .map(l => l.includes('|')                                    // table cells, minus separator rows
      ? l.split('|').map(c => c.trim()).filter(c => c && !/^[:\s-]+$/.test(c)).join(' · ') : l)
    .join(' ')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')                                           // bold
    .replace(/(\*|_)(?=\S)(.*?\S)\1/g, '$2')                                      // italics
    .replace(/[*`]/g, '')                                                         // leftover markers
    .replace(/\s+/g, ' ').trim();
}
