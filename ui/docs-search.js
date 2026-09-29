(function (root) {
  'use strict';
  const terms = query => (String(query).match(/"[^"]+"|\S+/g) || []).map(t => t.replace(/^"|"$/g, '').toLocaleLowerCase()).filter(Boolean);
  function search(documents, query, audience = '') {
    const words = terms(query);
    return documents.filter(d => !audience || d.category === audience).map(doc => {
      const title = doc.title.toLocaleLowerCase();
      const body = String(doc.search || '').replace(/\s+/g, ' ');
      const text = (doc.title + ' ' + doc.category + ' ' + body).toLocaleLowerCase();
      if (!words.every(word => text.includes(word))) return null;
      const score = words.reduce((n, word) => n + (title === word ? 100 : title.startsWith(word) ? 30 : title.includes(word) ? 15 : 1), 0);
      const hit = Math.max(0, Math.min(...words.map(w => body.toLocaleLowerCase().indexOf(w)).filter(i => i >= 0), body.length));
      const start = Math.max(0, hit - 65);
      const excerpt = (start ? '…' : '') + body.slice(start, start + 190) + (body.length > start + 190 ? '…' : '');
      return {doc, score, excerpt};
    }).filter(Boolean).sort((a, b) => b.score - a.score || a.doc.title.localeCompare(b.doc.title));
  }
  root.DocsSearch = {terms, search};
  if (typeof module !== 'undefined') module.exports = root.DocsSearch;
})(typeof globalThis !== 'undefined' ? globalThis : this);
