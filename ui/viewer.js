// The sky viewer: draws the image the engine composes, with zoom, pan, the
// catalog layer, the selected source, flags, a scale bar and a compass. The
// engine sends the image as RGBA pixels and the overlay geometry in image
// pixels; everything here is screen transforms and drawing.

const rgba = (r, g, b, a = 255) => `rgba(${r},${g},${b},${a / 255})`;

// Tifis palette, matching style.css. The catalog arrow is the periwinkle
// (the "blue arrow" of the tours) and the selection the pale sky blue.
const COL = {
  background: rgba(5, 11, 38), // --bg
  frame: rgba(27, 42, 102), // --line
  empty: rgba(9, 21, 64), // --panel (navy)
  label: rgba(234, 242, 254), // --text
  flag: rgba(201, 166, 232, 140), // --flag
  flagLine: rgba(228, 210, 245, 210),
  catalog: rgba(118, 146, 255, 240), // --accent #7692FF
  catalogFaint: rgba(118, 146, 255, 175),
  select: rgba(171, 210, 250), // --soft #ABD2FA
  selectFaint: rgba(171, 210, 250, 150),
  selectPoint: rgba(171, 210, 250, 110),
  grid: rgba(234, 242, 254, 22),
  hover: rgba(234, 242, 254, 160),
  reticle: rgba(234, 242, 254, 90),
  // Overlays sit on grayscale sky, where the muted theme colors get lost, so
  // lines, rings and labels get a dark outline.
  outline: rgba(5, 11, 38, 200),
};

const PIX_SCALE = 6.15; // arcsec per pixel
const MAX_ZOOM = 80;

function decodeBase64(b64) {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

export class Viewer {
  constructor(canvas, { select, hover } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onSelect = select || (() => {});
    this.onHover = hover || (() => {});
    this.width = 0;
    this.height = 0;
    this.dpr = 1;
    this.n = 0;
    this.active = false; // a field is open
    this.zoom = 1; // screen pixels per image pixel
    this.cx = 0; // image point at the center of the screen
    this.cy = 0;
    this.fitted = false;
    this.userMoved = false; // zoomed or panned by hand, so resizing keeps the view
    this.image = document.createElement('canvas');
    this.hasImage = false;
    this.flags = null;
    this.overlay = null;
    this.hoverX = -1;
    this.hoverY = -1;
    this.drag = null;
    this.font = getComputedStyle(document.documentElement).getPropertyValue('--mono').trim() || 'monospace';
    this.queued = false;
    this.wire();
  }

  // ---------- state from the engine ----------

  reset(n) {
    this.n = n;
    this.active = true;
    this.fitted = false;
    this.hasImage = false;
    this.flags = null;
    this.overlay = null;
    this.redraw();
  }

  clear() {
    this.active = false;
    this.hasImage = false;
    this.overlay = null;
    this.setHover(-1, -1);
    this.redraw();
  }

  setImage({ n, rgba: pixels, flags }) {
    if (!pixels) {
      this.hasImage = false;
      this.flags = null;
      this.redraw();
      return;
    }
    const bytes = decodeBase64(pixels);
    if (bytes.length !== n * n * 4) return;
    if (this.image.width !== n || this.image.height !== n) {
      this.image.width = n;
      this.image.height = n;
    }
    this.image.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(bytes.buffer), n, n), 0, 0);
    this.flags = flags ? decodeBase64(flags) : null;
    this.hasImage = true;
    this.redraw();
  }

  setOverlay(o) {
    this.overlay = o;
    this.redraw();
  }

  // ---------- geometry ----------

  resize(w, h) {
    w = Math.max(1, Math.floor(w));
    h = Math.max(1, Math.floor(h));
    const dpr = window.devicePixelRatio || 1;
    if (w === this.width && h === this.height && dpr === this.dpr) return;
    this.width = w;
    this.height = h;
    this.dpr = dpr;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    if (!this.userMoved) this.fit();
    this.redraw();
  }

  fitZoom() {
    return (Math.min(this.width, this.height) * 0.92) / Math.max(this.n, 1);
  }

  fit() {
    this.zoom = this.fitZoom();
    this.cx = this.n / 2;
    this.cy = this.n / 2;
    this.fitted = true;
    this.userMoved = false;
    this.redraw();
  }

  zoomBy(factor, sx, sy) {
    const [ix, iy] = this.toImage(sx, sy);
    this.zoom = Math.max(this.fitZoom() * 0.5, Math.min(this.zoom * factor, MAX_ZOOM));
    // Keep the point under the cursor still.
    this.cx = ix - (sx - this.width / 2) / this.zoom;
    this.cy = iy - (sy - this.height / 2) / this.zoom;
    this.userMoved = true;
    this.redraw();
  }

  zoomCenter(factor) {
    this.zoomBy(factor, this.width / 2, this.height / 2);
  }

  toScreen(ix, iy) {
    return [(ix - this.cx) * this.zoom + this.width / 2, (iy - this.cy) * this.zoom + this.height / 2];
  }

  toImage(sx, sy) {
    return [(sx - this.width / 2) / this.zoom + this.cx, (sy - this.height / 2) / this.zoom + this.cy];
  }

  // ---------- input ----------

  wire() {
    const c = this.canvas;
    const local = (e) => {
      const r = c.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    c.addEventListener('wheel', (e) => {
      if (!this.active) return;
      e.preventDefault();
      if (e.deltaY === 0) return;
      const [x, y] = local(e);
      this.zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15, x, y);
      this.updateHover(x, y);
    }, { passive: false });
    c.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !this.active) return;
      const [x, y] = local(e);
      this.drag = { x, y, cx: this.cx, cy: this.cy, moved: false, id: e.pointerId };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', (e) => {
      const [x, y] = local(e);
      const d = this.drag;
      if (d && d.id === e.pointerId) {
        if (Math.hypot(x - d.x, y - d.y) > 4) d.moved = true;
        if (d.moved) {
          this.userMoved = true;
          this.cx = d.cx - (x - d.x) / this.zoom;
          this.cy = d.cy - (y - d.y) / this.zoom;
          this.redraw();
        }
      }
      this.updateHover(x, y);
    });
    const end = (e, cancelled) => {
      const d = this.drag;
      if (!d || d.id !== e.pointerId) return;
      this.drag = null;
      if (!d.moved && !cancelled) {
        const [x, y] = local(e);
        const [ix, iy] = this.toImage(x, y);
        this.onSelect(ix, iy);
      }
    };
    c.addEventListener('pointerup', (e) => end(e, false));
    c.addEventListener('pointercancel', (e) => end(e, true));
    c.addEventListener('pointerleave', () => {
      if (!this.drag) this.setHover(-1, -1);
    });
  }

  updateHover(sx, sy) {
    let hx = -1;
    let hy = -1;
    const inside = sx >= 0 && sy >= 0 && sx < this.width && sy < this.height;
    if (this.active && this.n && inside) {
      const [ix, iy] = this.toImage(sx, sy);
      if (ix >= 0 && iy >= 0 && Math.floor(ix) < this.n && Math.floor(iy) < this.n) {
        hx = Math.floor(ix);
        hy = Math.floor(iy);
      }
    }
    this.setHover(hx, hy);
  }

  setHover(hx, hy) {
    if (hx === this.hoverX && hy === this.hoverY) return;
    this.hoverX = hx;
    this.hoverY = hy;
    this.onHover(hx, hy);
    this.redraw();
  }

  // ---------- drawing ----------

  redraw() {
    if (this.queued) return;
    this.queued = true;
    requestAnimationFrame(() => {
      this.queued = false;
      this.draw();
    });
  }

  draw() {
    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = COL.background;
    ctx.fillRect(0, 0, this.width, this.height);
    if (!this.active || !this.n) return;
    if (!this.fitted) this.fit();
    const n = this.n;
    const [ox, oy] = this.toScreen(0, 0);
    const size = n * this.zoom;

    ctx.strokeStyle = COL.frame;
    ctx.lineWidth = 1;
    ctx.strokeRect(ox - 1.5, oy - 1.5, size + 3, size + 3);
    if (this.hasImage) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(this.image, 0, 0, n, n, ox, oy, size, size);
    } else {
      ctx.fillStyle = COL.empty;
      ctx.fillRect(ox, oy, size, size);
    }

    if (this.zoom >= 14) this.drawGrid();
    if (this.flags && this.hasImage) this.drawFlags();
    const o = this.overlay;
    this.drawReticle(o?.center ?? [n / 2, n / 2]);
    for (const c of o?.catalog ?? []) this.drawCatalogEntry(c);
    if (o?.selection) this.drawSelection(o.selection);
    if (this.hoverX >= 0) {
      const [hx, hy] = this.toScreen(this.hoverX, this.hoverY);
      ctx.strokeStyle = COL.hover;
      ctx.lineWidth = 1;
      ctx.strokeRect(hx + 0.5, hy + 0.5, this.zoom - 1, this.zoom - 1);
    }
    this.drawScaleBar();
    this.drawCompass();
  }

  line(x0, y0, x1, y1, width, color) {
    const ctx = this.ctx;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
  }

  ring(x, y, r, color) {
    const ctx = this.ctx;
    const rr = Math.max(0.5, r - 0.5);
    for (const [w, c] of [[4, COL.outline], [2, color]]) {
      ctx.strokeStyle = c;
      ctx.lineWidth = w;
      ctx.beginPath();
      ctx.arc(x, y, rr, 0, 2 * Math.PI);
      ctx.stroke();
    }
  }

  label(text, x, y, color) {
    const ctx = this.ctx;
    ctx.font = `600 16px ${this.font}`;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = COL.outline;
    ctx.lineWidth = 3;
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
  }

  arrow(x0, y0, x1, y1, color) {
    this.line(x0, y0, x1, y1, 4, COL.outline);
    this.line(x0, y0, x1, y1, 2, color);
    const len = Math.hypot(x1 - x0, y1 - y0);
    if (!len) return;
    const dx = (x1 - x0) / len;
    const dy = (y1 - y0) / len;
    const bx = x1 - dx * 9;
    const by = y1 - dy * 9;
    const ctx = this.ctx;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(bx - dy * 5, by + dx * 5);
    ctx.lineTo(bx + dy * 5, by - dx * 5);
    ctx.closePath();
    ctx.fill();
  }

  drawGrid() {
    const [x0, y0] = this.toImage(0, 0);
    const [x1, y1] = this.toImage(this.width, this.height);
    const i0 = Math.max(0, Math.trunc(x0));
    const i1 = Math.min(this.n, Math.trunc(x1) + 1);
    const j0 = Math.max(0, Math.trunc(y0));
    const j1 = Math.min(this.n, Math.trunc(y1) + 1);
    const [left, top] = this.toScreen(0, 0);
    const [right, bottom] = this.toScreen(this.n, this.n);
    for (let i = i0; i <= i1; i++) {
      const x = this.toScreen(i, 0)[0];
      this.line(x, top, x, bottom, 1, COL.grid);
    }
    for (let j = j0; j <= j1; j++) {
      const y = this.toScreen(0, j)[1];
      this.line(left, y, right, y, 1, COL.grid);
    }
  }

  // Flagged pixels are shaded and hatched, so the cue does not rely on color alone.
  drawFlags() {
    const ctx = this.ctx;
    const n = this.n;
    const z = this.zoom;
    ctx.fillStyle = COL.flag;
    const hatch = [];
    for (let i = 0; i < this.flags.length; i++) {
      if (!this.flags[i]) continue;
      const [x, y] = this.toScreen(i % n, Math.floor(i / n));
      ctx.fillRect(x, y, z, z);
      if (z >= 6) hatch.push([x, y]);
    }
    if (hatch.length) {
      ctx.strokeStyle = COL.flagLine;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (const [x, y] of hatch) {
        ctx.moveTo(x, y);
        ctx.lineTo(x + z, y + z);
      }
      ctx.stroke();
    }
  }

  drawReticle([ix, iy]) {
    const [x, y] = this.toScreen(ix, iy);
    const gap = Math.max(10, 4 * this.zoom);
    const l = 10;
    this.line(x - gap - l, y, x - gap, y, 1.5, COL.reticle);
    this.line(x + gap, y, x + gap + l, y, 1.5, COL.reticle);
    this.line(x, y - gap - l, x, y - gap, 1.5, COL.reticle);
    this.line(x, y + gap, x, y + gap + l, 1.5, COL.reticle);
  }

  // Catalog positions at their catalog epoch, with an arrow to where the
  // proper motion puts the source on the current frame.
  drawCatalogEntry(c) {
    const [x0, y0] = this.toScreen(c.x0, c.y0);
    const [x1, y1] = this.toScreen(c.x1, c.y1);
    const r = Math.max(5, 1.6 * this.zoom);
    if (c.target) {
      this.ring(x0, y0, r, COL.catalog);
      this.label(c.name, x0 + r + 4, y0 - r - 20, COL.catalog);
    } else {
      this.ring(x0, y0, r * 0.7, COL.catalogFaint);
    }
    if (c.arrow) this.arrow(x0, y0, x1, y1, COL.catalog);
  }

  drawSelection(s) {
    const [x, y] = this.toScreen(s.x, s.y);
    const [ap, inner, outer] = s.radii;
    this.ring(x, y, ap * this.zoom, COL.select);
    this.ring(x, y, inner * this.zoom, COL.selectFaint);
    this.ring(x, y, outer * this.zoom, COL.selectFaint);
    if (s.line) {
      const [ax, ay] = this.toScreen(s.line[0], s.line[1]);
      const [bx, by] = this.toScreen(s.line[2], s.line[3]);
      this.line(ax, ay, bx, by, 1.5, COL.selectFaint);
    }
    const ctx = this.ctx;
    const r = Math.max(1.5, this.zoom * 0.08);
    for (const [px, py, current] of s.points) {
      const [sx, sy] = this.toScreen(px, py);
      ctx.fillStyle = current ? COL.select : COL.selectPoint;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, 2 * Math.PI);
      ctx.fill();
    }
  }

  drawScaleBar() {
    const pxPerArcsec = this.zoom / PIX_SCALE;
    let length = 5;
    for (const l of [5, 10, 15, 30, 60, 120, 300, 600]) {
      length = l;
      if (l * pxPerArcsec >= 70) break;
    }
    const w = length * pxPerArcsec;
    const x = 18;
    const y = this.height - 24;
    const ctx = this.ctx;
    ctx.fillStyle = COL.label;
    ctx.fillRect(x, y, w, 4);
    ctx.fillRect(x, y - 5, 2, 14);
    ctx.fillRect(x + w - 2, y - 5, 2, 14);
    const text = length >= 60 ? `${(length / 60).toFixed(0)}′` : `${length.toFixed(0)}″`;
    this.label(text, x + w + 8, y - 8, COL.label);
  }

  drawCompass() {
    const cx = this.width - 36;
    const cy = 52;
    const l = 26;
    this.arrow(cx, cy, cx, cy - l, COL.label);
    this.arrow(cx, cy, cx - l, cy, COL.label);
    this.label('N', cx - 5, cy - l - 24, COL.label);
    this.label('E', cx - l - 18, cy - 9, COL.label);
  }
}
