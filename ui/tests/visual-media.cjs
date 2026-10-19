// Video and audio cards in a conversation (Visual replies 3/4), on ui/app/visual-media.js with a stand-in card frame:
// neither starts by itself (preload metadata, no autoplay, the isolated address, never a blob or the signed-in file
// URL); seeking far into a long clip asks for that part by range instead of the whole file; starting one clip pauses
// the other; an address that expires mid-play is swapped for the card's newest one at the same position, still
// playing; a type the device can't play, or a clip it can't decode, shows the reason and Download.
// Every request is intercepted; the clips are WAV files made here, so the test needs no media files.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// A mono 8 kHz 16-bit WAV of `seconds` of a quiet tone: 16 KB a second.
function wav(seconds) {
  const rate = 8000, n = rate * seconds, data = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) data.writeInt16LE(Math.round(800 * Math.sin(i / 8)), i * 2);
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + data.length, 4); h.write('WAVE', 8); h.write('fmt ', 12);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}
const LONG = wav(120);                          // ~1.9 MB, two minutes
const SHORT = wav(20);
const CHUNK = 64 * 1024;                        // the stand-in server answers at most this much per request

const APP = 'https://app.test', VIS = 'https://visuals.test';
const UI = path.join(__dirname, '..', 'app', 'visual-media.js');

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true,
    args: ['--autoplay-policy=no-user-gesture-required']});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}, serviceWorkers: 'block'});
    const errors = [], served = [], expired = new Set();
    page.on('pageerror', e => errors.push(e.message));
    const bodies = {'long-1': LONG, 'long-2': LONG, 'short-1': SHORT, 'bad-1': Buffer.from('not a wav file at all'.repeat(40))};
    await page.route(`${VIS}/**`, route => {
      const req = route.request(), token = new URL(req.url()).pathname.split('/').pop(), body = bodies[token];
      const range = req.headers().range || '';
      served.push({token, range});
      if (!body || expired.has(token)) return route.fulfill({status: 403, body: ''});
      const m = /bytes=(\d+)-(\d*)/.exec(range);
      if (!m) return route.fulfill({status: 200, headers: {'content-type': 'audio/wav', 'accept-ranges': 'bytes'}, body});
      const start = Number(m[1]), end = Math.min(m[2] ? Number(m[2]) : body.length - 1, start + CHUNK - 1, body.length - 1);
      served[served.length - 1].bytes = end - start + 1;
      return route.fulfill({status: 206, body: body.subarray(start, end + 1), headers: {'content-type': 'audio/wav',
        'accept-ranges': 'bytes', 'content-range': `bytes ${start}-${end}/${body.length}`}});
    });
    await page.route(`${APP}/**`, route => route.fulfill({status: 200, contentType: 'text/html', body: '<!doctype html><main id="thread"></main>'}));
    await page.goto(`${APP}/chat`);
    // The stand-in frame: what visual-cards.js provides (escape, API, VISUAL_BODY, VISUAL_WIRE, visualSrc).
    await page.addScriptTag({content: `
      const API = '/api';
      const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
      const VISUAL_BODY = {}, VISUAL_WIRE = {};
      const visualSrc = f => f.src;
      window.card = (key, f) => {
        const fig = document.createElement('figure');
        fig.className = 'vcard'; fig.dataset.visualKey = key; fig.dataset.kind = f.kind;
        fig.innerHTML = VISUAL_BODY[f.kind](f) + '<figcaption>' + esc(f.title) + '</figcaption>';
        document.getElementById('thread').append(fig);
        VISUAL_WIRE[f.kind]?.(fig);
        return fig;
      };`});
    await page.addScriptTag({content: fs.readFileSync(UI, 'utf8')});
    assert.deepEqual(await page.evaluate(() => [typeof VISUAL_BODY.video, typeof VISUAL_BODY.audio, typeof VISUAL_WIRE.audio]),
      ['function', 'function', 'function'], 'video and audio register with the frame');

    const file = (id, extra) => ({file_id: id, version: 1, name: `${id}.wav`, title: `Clip ${id}`, kind: 'audio',
      content_type: 'audio/wav', size: LONG.length, url: `/api/v2/files/${id}?v=1`, src: `${VIS}/visuals/${id}-1`, ...extra});
    await page.evaluate(([a, b, v]) => { card('m1:a@1', a); card('m1:b@1', b); card('m2:v@1', v); },
      [file('long', {src: `${VIS}/visuals/long-1`}), file('short', {src: `${VIS}/visuals/short-1`, size: SHORT.length}),
       {file_id: 'v', version: 1, name: 'cut.mp4', title: 'The cut', kind: 'video', content_type: 'video/mp4', width: 1280, height: 720,
        url: '/api/v2/files/v?v=1', src: `${VIS}/visuals/video-1`, poster_url: `${VIS}/visuals/video-1-poster`}]);

    // ---- test 12: nothing plays by itself; the players are the task-files ones, on the isolated address
    const long = page.locator('[data-visual-key="m1:a@1"] audio'), short = page.locator('[data-visual-key="m1:b@1"] audio');
    await long.evaluate(m => m.readyState >= 1 || new Promise(r => m.addEventListener('loadedmetadata', r, {once: true})));
    for (const sel of ['audio', 'video']) {
      for (const m of await page.locator(`.vcard ${sel}`).all()) {
        assert.equal(await m.getAttribute('autoplay'), null, `${sel} has no autoplay`);
        assert.equal(await m.getAttribute('preload'), 'metadata');
        assert.equal(await m.getAttribute('controls'), '');
        assert.match(await m.getAttribute('src'), /^https:\/\/visuals\.test\/visuals\//, `${sel} loads from the isolated address`);
      }
    }
    const video = page.locator('.vcard video');
    if (await video.count()) {        // a browser that can play MP4 shows the player; Chromium without H.264 shows the reason
      assert.equal(await video.getAttribute('playsinline'), '');
      assert.equal(await video.getAttribute('poster'), `${VIS}/visuals/video-1-poster`);
      assert.equal(await video.evaluate(m => m.parentElement.getAttribute('style')), 'aspect-ratio:1280/720', 'the card holds the video\'s shape');
    }
    await page.waitForTimeout(500);
    assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('audio, video')].map(m => m.paused)),
      (await page.locator('audio, video').all()).map(() => true), 'nothing is playing after the page settles');
    assert.ok(served.filter(s => !s.token.endsWith('-poster')).every(s => s.range), 'every media request is a range request');

    // ---- test 13: seeking far into the long clip asks for that part, never the whole file
    await long.evaluate(m => m.play());
    await long.evaluate(m => new Promise(r => { m.addEventListener('seeked', r, {once: true}); m.currentTime = 90; }));
    const asked = served.filter(s => s.token === 'long-1');
    const from = asked.map(s => Number((/bytes=(\d+)/.exec(s.range) || [])[1] || 0));
    assert.ok(from.some(n => n > LONG.length / 2), `a range request starts past the middle (${from.join(', ')})`);
    const fetched = asked.reduce((sum, s) => sum + (s.bytes || 0), 0);
    assert.ok(fetched < LONG.length / 2, `seeking fetched ${fetched} of ${LONG.length} bytes, not the whole file`);
    assert.equal(await long.evaluate(m => m.paused), false);

    // ---- test 14: starting another clip pauses the first
    await short.evaluate(m => m.play());
    await page.waitForFunction(() => document.querySelector('[data-visual-key="m1:a@1"] audio').paused);
    assert.equal(await short.evaluate(m => m.paused), false, 'the clip just started plays');
    await short.evaluate(m => m.pause());

    // ---- an address that runs out mid-play: the card's newest address takes over, same place, still playing
    await long.evaluate(m => m.play());
    await page.evaluate(() => { document.querySelector('[data-visual-key="m1:a@1"]').dataset.freshSrc = 'https://visuals.test/visuals/long-2'; });
    expired.add('long-1');
    await long.evaluate(m => new Promise(r => { m.addEventListener('seeking', r, {once: true}); m.currentTime = 30; }));
    await page.waitForFunction(() => document.querySelector('[data-visual-key="m1:a@1"] audio')?.src.endsWith('/long-2'), null, {timeout: 10000});
    await page.waitForFunction(() => { const m = document.querySelector('[data-visual-key="m1:a@1"] audio'); return m.readyState >= 1 && !m.paused && m.currentTime >= 29; }, null, {timeout: 10000});
    assert.ok(served.some(s => s.token === 'long-2'), 'the new address was asked');
    assert.equal(await page.locator('[data-visual-key="m1:a@1"] .vm-cant').count(), 0, 'no error card while a newer address works');
    await long.evaluate(m => m.pause());

    // ---- test 24: an address that runs out with no newer one shows the reason and Download (never a broken player)
    expired.add('long-2');
    await long.evaluate(m => { m.currentTime = 110; });
    await page.locator('[data-visual-key="m1:a@1"] .vm-cant').waitFor({timeout: 10000});
    assert.equal(await page.locator('[data-visual-key="m1:a@1"] .vm-cant a').getAttribute('href'), '/api/v2/files/long?v=1', 'Download is the signed-in download');

    // ---- test 24: a clip the device can't decode, and a type it can't play at all
    await page.evaluate(f => card('m3:bad@1', f), file('bad', {src: `${VIS}/visuals/bad-1`}));
    await page.locator('[data-visual-key="m3:bad@1"] .vm-cant').waitFor({timeout: 10000});
    assert.equal(await page.locator('[data-visual-key="m3:bad@1"] .vm-reason').textContent(), 'This device can\'t play WAV audio.');
    await page.evaluate(() => card('m4:odd@1', {file_id: 'odd', version: 2, name: 'old.flv', title: 'Old', kind: 'video',
      content_type: 'video/x-flv', url: '/api/v2/files/odd?v=2', src: 'https://visuals.test/visuals/odd-2'}));
    assert.equal(await page.locator('[data-visual-key="m4:odd@1"] video').count(), 0, 'no player for a type the device can\'t play');
    assert.equal(await page.locator('[data-visual-key="m4:odd@1"] .vm-reason').textContent(), 'This device can\'t play this video.');
    assert.equal(await page.locator('[data-visual-key="m4:odd@1"] .vm-cant a').getAttribute('download'), 'old.flv');
    assert.ok(!served.some(s => s.token === 'odd-2'), 'nothing is fetched for a type the device can\'t play');

    assert.ok(!(await page.content()).includes('blob:'), 'no blob URLs');
    assert.deepEqual(errors, []);
    console.log('visual-media: ok');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
