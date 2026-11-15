// Bridge between the page and the engine, which runs in the Python server.
//
// It exposes the same API the page has always used, globalThis.skyEngine
// (open, view, zoom, fit, resize, clearSelection, pointer), and delivers the
// engine's events to globalThis.skyUI.event(kind, json). Commands go to the
// server in order over POST; events come back over Server-Sent Events. Images
// and overlay geometry go to the canvas viewer instead of the page.

import { Viewer } from './viewer.js';

const KINDS = ['ready', 'field', 'loaded', 'frame', 'hover', 'select', 'status', 'image', 'overlay'];

function sessionId() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
}

export async function start() {
  const session = sessionId();
  const viewer = new Viewer(document.getElementById('canvas'), {
    select: (x, y) => send('select', { x, y }),
    hover: (x, y) => send('hover', x < 0 ? null : { x, y }),
  });

  // Commands are sent one at a time, in order. Hover only matters at its
  // latest position, so a hover still waiting is replaced by the next one.
  const queue = [];
  let sending = false;
  function send(cmd, args) {
    const last = queue[queue.length - 1];
    if (cmd === 'hover' && last?.cmd === 'hover') last.args = args;
    else queue.push({ cmd, args });
    pump();
  }
  async function pump() {
    if (sending) return;
    sending = true;
    while (queue.length) {
      const { cmd, args } = queue.shift();
      try {
        await fetch('/api/engine/command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session, cmd, args }),
        });
      } catch (err) {
        console.warn('skyEngine:', cmd, err);
      }
    }
    sending = false;
  }

  globalThis.skyEngine = {
    open: (json) => send('open', JSON.parse(json)),
    view: (json) => send('view', JSON.parse(json)),
    zoom: (factor) => viewer.zoomCenter(factor),
    fit: () => viewer.fit(),
    resize: (w, h) => viewer.resize(w, h),
    clearSelection: () => send('clearSelection', null),
    // The canvas tracks the pointer itself.
    pointer: () => {},
  };

  const deliver = (kind, json) => {
    if (kind === 'image') return viewer.setImage(JSON.parse(json));
    if (kind === 'overlay') return viewer.setOverlay(JSON.parse(json));
    if (kind === 'field') viewer.reset(JSON.parse(json).npix);
    if (kind === 'status') {
      const st = JSON.parse(json);
      if (st.stage === 'visits' && st.state === 'loading') viewer.clear();
    }
    globalThis.skyUI?.event(kind, json);
  };

  const es = new EventSource(`/api/engine/events?session=${session}`);
  for (const kind of KINDS) {
    es.addEventListener(kind, (e) => {
      try {
        deliver(kind, e.data);
      } catch (err) {
        console.error('skyEngine event', kind, err);
      }
    });
  }
  es.addEventListener('error', () => {
    if (es.readyState === EventSource.CLOSED) console.error('skyEngine: event stream closed');
  });
  return { session, viewer };
}
