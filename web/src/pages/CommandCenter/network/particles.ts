/**
 * Particle engine for the agent network. `task.handoff` pulses are routed over the registered edge paths
 * (direct edge, reversed edge, or hop-by-hop along the pipeline order) and drawn as glowing SVG comets in the
 * SOURCE agent's colour. One requestAnimationFrame loop moves every particle by writing SVG `transform`
 * attributes — no React state per frame. Pausing freezes particles in place; resuming continues them.
 * With reduced motion, a handoff only lights the route's edges briefly.
 */
import { createEmitter } from '@/lib/bus';

const SVG_NS = 'http://www.w3.org/2000/svg';
export const MAX_PARTICLES = 40;
const TRAIL = [
  { r: 2.3, o: 0.55 },
  { r: 1.9, o: 0.4 },
  { r: 1.5, o: 0.28 },
  { r: 1.15, o: 0.18 },
  { r: 0.85, o: 0.1 },
];
const TRAIL_GAP = 4.2;
/** flow units per second */
const SPEED = 165;

interface EdgeGeom {
  id: string;
  source: string;
  target: string;
  /** sampled points x0,y0,x1,y1… */
  pts: Float32Array;
  n: number;
  len: number;
  layer: SVGGElement;
  glow: SVGGElement | null;
}

interface Seg {
  geom: EdgeGeom;
  reverse: boolean;
  /** cumulative distance at which this segment starts */
  start: number;
}

interface Particle {
  segs: Seg[];
  total: number;
  duration: number;
  t0: number;
  color: string;
  to: string;
  g: SVGGElement;
  head: SVGGElement;
  trail: SVGCircleElement[];
  segIdx: number;
}

export interface Topology {
  /** pipeline order, left → right / top → bottom */
  order: string[];
  hub: string | null;
}

/** A particle reached its destination agent (drives the node's arrival ring). */
export const arrivals = createEmitter<{ agentId: string; color: string }>();

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) el.setAttribute(k, String(attrs[k]));
  return el;
}

export class ParticleEngine {
  private edges = new Map<string, EdgeGeom>();
  private byPair = new Map<string, EdgeGeom>();
  private particles: Particle[] = [];
  private raf = 0;
  private paused = false;
  private pausedAt = 0;
  private reduced = false;
  private topo: Topology = { order: [], hub: null };
  private lit = new Map<EdgeGeom, string>();
  private flashTimers = new Set<ReturnType<typeof setTimeout>>();

  setTopology(t: Topology): void {
    this.topo = t;
  }

  setReducedMotion(on: boolean): void {
    this.reduced = on;
    if (on) this.clear();
  }

  get count(): number {
    return this.particles.length;
  }

  /** Register an edge's geometry and particle layer; returns the unregister function. */
  register(id: string, source: string, target: string, path: SVGPathElement, layer: SVGGElement, glow: SVGGElement | null) {
    let len = 0;
    try {
      len = path.getTotalLength();
    } catch {
      len = 0;
    }
    const n = Math.max(12, Math.ceil(len / 3));
    const pts = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) {
      const p = path.getPointAtLength((i / (n - 1)) * len);
      pts[i * 2] = p.x;
      pts[i * 2 + 1] = p.y;
    }
    const geom: EdgeGeom = { id, source, target, pts, n, len, layer, glow };
    this.edges.set(id, geom);
    this.byPair.set(`${source}>${target}`, geom);
    return () => {
      if (this.edges.get(id) === geom) this.edges.delete(id);
      if (this.byPair.get(`${source}>${target}`) === geom) this.byPair.delete(`${source}>${target}`);
      this.lit.delete(geom);
      this.particles = this.particles.filter((p) => {
        const dead = p.segs.some((s) => s.geom === geom);
        if (dead) p.g.remove();
        return !dead;
      });
    };
  }

  private route(from: string, to: string): Seg[] | null {
    const pair = (a: string, b: string) => this.byPair.get(`${a}>${b}`);
    const direct = pair(from, to);
    if (direct) return [{ geom: direct, reverse: false, start: 0 }];
    const back = pair(to, from);
    if (back) return [{ geom: back, reverse: true, start: 0 }];
    const { order } = this.topo;
    const i = order.indexOf(from);
    const j = order.indexOf(to);
    if (i < 0 || j < 0) return null;
    const step = j > i ? 1 : -1;
    const segs: Seg[] = [];
    for (let k = i; k !== j; k += step) {
      const a = order[k];
      const b = order[k + step];
      const g = step > 0 ? pair(a, b) : pair(b, a);
      if (!g) return null;
      segs.push({ geom: g, reverse: step < 0, start: 0 });
    }
    return segs;
  }

  handoff(from: string, to: string, color: string): void {
    if (this.paused || (typeof document !== 'undefined' && document.hidden)) return;
    if (from === to) {
      arrivals.emit({ agentId: to, color });
      return;
    }
    const segs = this.route(from, to);
    if (!segs || !segs.length) return;
    if (this.reduced) {
      for (const s of segs) this.flash(s.geom, color);
      arrivals.emit({ agentId: to, color });
      return;
    }
    let total = 0;
    for (const s of segs) {
      s.start = total;
      total += s.geom.len;
    }
    if (total < 1) return;

    const g = svg('g', { class: 'cc-particle', 'pointer-events': 'none' });
    const trail = TRAIL.map((t) => svg('circle', { r: t.r, fill: color, opacity: 0 }));
    for (let i = trail.length - 1; i >= 0; i--) g.appendChild(trail[i]);
    const head = svg('g', {});
    head.appendChild(svg('circle', { r: 8, fill: color, opacity: 0.16 }));
    head.appendChild(svg('circle', { r: 4.2, fill: color, opacity: 0.45 }));
    head.appendChild(svg('circle', { r: 2.6, fill: color }));
    head.appendChild(svg('circle', { r: 1.2, fill: '#ffffff', opacity: 0.95 }));
    g.appendChild(head);
    g.style.opacity = '0';
    segs[0].geom.layer.appendChild(g);

    const duration = Math.min(2400, Math.max(700, (total / SPEED) * 1000));
    this.particles.push({ segs, total, duration, t0: performance.now(), color, to, g, head, trail, segIdx: 0 });
    while (this.particles.length > MAX_PARTICLES) this.particles.shift()?.g.remove();
    this.kick();
  }

  setPaused(on: boolean): void {
    if (on === this.paused) return;
    this.paused = on;
    if (on) {
      this.pausedAt = performance.now();
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    } else {
      const shift = performance.now() - this.pausedAt;
      for (const p of this.particles) p.t0 += shift;
      this.kick();
    }
  }

  clear(): void {
    for (const p of this.particles) p.g.remove();
    this.particles = [];
    for (const geom of this.lit.keys()) geom.glow?.removeAttribute('data-on');
    this.lit.clear();
  }

  dispose(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    for (const t of this.flashTimers) clearTimeout(t);
    this.flashTimers.clear();
    this.clear();
    this.edges.clear();
    this.byPair.clear();
  }

  private kick(): void {
    if (!this.raf && !this.paused && this.particles.length) this.raf = requestAnimationFrame(this.frame);
  }

  private flash(geom: EdgeGeom, color: string): void {
    const glow = geom.glow;
    if (!glow) return;
    glow.style.stroke = color;
    glow.setAttribute('data-on', 'true');
    const t = setTimeout(() => {
      this.flashTimers.delete(t);
      glow.removeAttribute('data-on');
    }, 900);
    this.flashTimers.add(t);
  }

  /** point at distance d along the particle's route → [x, y, segment index] */
  private pointAt(p: Particle, d: number): [number, number, number] {
    let k = p.segs.length - 1;
    while (k > 0 && p.segs[k].start > d) k--;
    const s = p.segs[k];
    const g = s.geom;
    let local = Math.min(g.len, Math.max(0, d - s.start));
    if (s.reverse) local = g.len - local;
    const f = g.len > 0 ? (local / g.len) * (g.n - 1) : 0;
    const i0 = Math.min(g.n - 2, Math.floor(f));
    const t = f - i0;
    const x = g.pts[i0 * 2] + (g.pts[i0 * 2 + 2] - g.pts[i0 * 2]) * t;
    const y = g.pts[i0 * 2 + 1] + (g.pts[i0 * 2 + 3] - g.pts[i0 * 2 + 1]) * t;
    return [x, y, k];
  }

  private frame = (now: number): void => {
    this.raf = 0;
    const lit = new Map<EdgeGeom, string>();
    const keep: Particle[] = [];
    for (const p of this.particles) {
      const u = Math.max(0, (now - p.t0) / p.duration);
      if (u >= 1) {
        p.g.remove();
        arrivals.emit({ agentId: p.to, color: p.color });
        continue;
      }
      keep.push(p);
      const d = easeInOut(u) * p.total;
      const [x, y, k] = this.pointAt(p, d);
      if (k !== p.segIdx) {
        p.segIdx = k;
        p.segs[k].geom.layer.appendChild(p.g);
      }
      p.head.setAttribute('transform', `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
      for (let j = 0; j < p.trail.length; j++) {
        const dj = d - (j + 1) * TRAIL_GAP;
        const c = p.trail[j];
        if (dj <= 0) {
          c.setAttribute('opacity', '0');
          continue;
        }
        const [tx, ty] = this.pointAt(p, dj);
        c.setAttribute('transform', `translate(${tx.toFixed(2)} ${ty.toFixed(2)})`);
        c.setAttribute('opacity', String(TRAIL[j].o));
      }
      const fade = Math.min(1, u / 0.06, (1 - u) / 0.1);
      p.g.style.opacity = fade.toFixed(3);
      lit.set(p.segs[k].geom, p.color);
    }
    this.particles = keep;

    for (const geom of this.lit.keys()) if (!lit.has(geom)) geom.glow?.removeAttribute('data-on');
    for (const [geom, color] of lit) {
      if (this.lit.get(geom) === color) continue;
      if (geom.glow) {
        geom.glow.style.stroke = color;
        geom.glow.setAttribute('data-on', 'true');
      }
    }
    this.lit = lit;
    this.kick();
  };
}
