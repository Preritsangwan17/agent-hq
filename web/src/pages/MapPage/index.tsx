/**
 * Map — an offline world map (d3-geo + world-atlas, no tiles, no network). Every placed opportunity is a pin:
 * size = monthly pay (INR), colour = pay vs living cost, pulsing ring = waiting on Prerit, dashed = simulated.
 * Pins at the same city cluster; click one to see the roles there. Remote/unplaced roles are counted aside.
 */
import { geoEqualEarth, geoPath, type GeoProjection } from 'd3-geo';
import { Earth, ExternalLink, Globe2, Wifi } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { feature } from 'topojson-client';
import type { GeometryCollection, Topology } from 'topojson-specification';
import world from 'world-atlas/countries-110m.json';
import { GlassPanel, PayBadge, SectionHeader, SimTag, StageChip, ratioColor } from '@/components';
import { cn } from '@/lib/cn';
import { flagEmoji, formatINRCompact } from '@/lib/format';
import { useHQ } from '@/lib/store';
import type { OppSummary } from '@/lib/types';
import { SIDE_STAGES, colors } from '@/theme/tokens';

const W = 960;
const H = 500;

type Scope = 'active' | 'all';
type Region = 'world' | 'india' | 'europe' | 'asia' | 'americas';

const REGIONS: Record<Region, { label: string; box: [[number, number], [number, number]] | null }> = {
  world: { label: 'World', box: null },
  india: { label: 'India', box: [[67, 6], [98, 36]] },
  asia: { label: 'Asia', box: [[60, -10], [150, 55]] },
  europe: { label: 'Europe', box: [[-12, 35], [35, 62]] },
  americas: { label: 'Americas', box: [[-130, -45], [-35, 60]] },
};

const topo = world as unknown as Topology<{ countries: GeometryCollection }>;
const countries = feature(topo, topo.objects.countries);

function makeProjection(region: Region): GeoProjection {
  const p = geoEqualEarth();
  const box = REGIONS[region].box;
  if (!box) return p.fitExtent([[8, 8], [W - 8, H - 8]], { type: 'Sphere' });
  const [[x0, y0], [x1, y1]] = box;
  const frame = {
    type: 'Feature' as const,
    properties: {},
    geometry: { type: 'MultiPoint' as const, coordinates: [[x0, y0], [x1, y1], [x0, y1], [x1, y0]] },
  };
  return p.fitExtent([[24, 24], [W - 24, H - 24]], frame);
}

interface Cluster {
  key: string;
  x: number;
  y: number;
  opps: OppSummary[];
  pay: number | null;
  ratio: number | null;
  needs: boolean;
  sim: boolean;
}

function radiusFor(pay: number | null, maxPay: number): number {
  if (pay == null || maxPay <= 0) return 4.5;
  return 4.5 + 13 * Math.sqrt(Math.min(1, pay / maxPay));
}

export default function MapPage() {
  const opps = useHQ((s) => s.opportunities);
  const [scope, setScope] = useState<Scope>('active');
  const [showSim, setShowSim] = useState(true);
  const [region, setRegion] = useState<Region>('world');
  const [sel, setSel] = useState<string | null>(null);

  const projection = useMemo(() => makeProjection(region), [region]);
  const path = useMemo(() => geoPath(projection), [projection]);
  const land = useMemo(() => countries.features.map((f, i) => ({ id: String(f.id ?? i), d: path(f) ?? '' })), [path]);
  const graticule = useMemo(() => path({ type: 'Sphere' }) ?? '', [path]);

  const list = useMemo(
    () =>
      Object.values(opps).filter(
        (o) => (showSim || !o.is_simulated) && (scope === 'all' || !SIDE_STAGES.includes(o.stage)),
      ),
    [opps, scope, showSim],
  );
  const placed = list.filter((o) => o.lat != null && o.lon != null);
  const unplaced = list.length - placed.length;
  const maxPay = Math.max(0, ...placed.map((o) => o.pay?.monthly_inr_mid ?? o.pay?.monthly_inr_min ?? 0));

  const clusters = useMemo(() => {
    const m = new Map<string, Cluster>();
    for (const o of placed) {
      const xy = projection([o.lon!, o.lat!]);
      if (!xy || xy[0] < 0 || xy[0] > W || xy[1] < 0 || xy[1] > H) continue;
      const key = `${Math.round(xy[0] / 9)}:${Math.round(xy[1] / 9)}`;
      const pay = o.pay?.monthly_inr_mid ?? o.pay?.monthly_inr_min ?? null;
      const c = m.get(key) ?? { key, x: xy[0], y: xy[1], opps: [], pay: null, ratio: null, needs: false, sim: true };
      c.opps.push(o);
      if (pay != null && (c.pay == null || pay > c.pay)) {
        c.pay = pay;
        c.ratio = o.pay?.ratio ?? null;
      }
      c.needs ||= o.needs_prerit;
      c.sim &&= o.is_simulated;
      m.set(key, c);
    }
    return [...m.values()].sort((a, b) => (a.pay ?? 0) - (b.pay ?? 0));
  }, [placed, projection]);

  const selected = clusters.find((c) => c.key === sel);

  return (
    <div className="space-y-5">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="World"
        title="Map"
        icon={Earth}
        color="#2DD4BF"
        right={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Pills value={region} onChange={setRegion} options={Object.entries(REGIONS).map(([v, r]) => ({ value: v as Region, label: r.label }))} label="Region" />
            <Pills value={scope} onChange={setScope} options={[{ value: 'active', label: 'Active' }, { value: 'all', label: 'All' }]} label="Scope" />
            <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-[12px] text-muted">
              <input type="checkbox" checked={showSim} onChange={(e) => setShowSim(e.target.checked)} className="accent-cyan-400" />
              simulated
            </label>
          </div>
        }
      />

      <GlassPanel padding="none" glow="#2DD4BF" glowStrength={0.25} className="relative overflow-hidden">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label={`${placed.length} opportunities on a world map`}>
          <defs>
            <radialGradient id="ocean" cx="50%" cy="45%" r="75%">
              <stop offset="0%" stopColor="#0E1A2C" />
              <stop offset="100%" stopColor="#070B14" />
            </radialGradient>
            <filter id="pinGlow" x="-100%" y="-100%" width="300%" height="300%">
              <feGaussianBlur stdDeviation="3.2" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <rect width={W} height={H} fill="url(#ocean)" onClick={() => setSel(null)} />
          <path d={graticule} fill="none" stroke="rgba(45,212,191,0.12)" />
          <g>
            {land.map((c) => (
              <path key={c.id} d={c.d} fill="rgba(148,163,184,0.10)" stroke="rgba(148,163,184,0.22)" strokeWidth={0.5} />
            ))}
          </g>
          <g>
            {clusters.map((c) => {
              const r = radiusFor(c.pay, maxPay);
              const col = c.pay == null ? colors.muted : ratioColor(c.ratio);
              const active = c.key === sel;
              return (
                <g
                  key={c.key}
                  transform={`translate(${c.x},${c.y})`}
                  className="cursor-pointer"
                  onClick={() => setSel(active ? null : c.key)}
                  role="button"
                  tabIndex={0}
                  aria-label={`${c.opps.length} role${c.opps.length > 1 ? 's' : ''} in ${c.opps[0].city ?? c.opps[0].country_iso2 ?? 'here'}`}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setSel(active ? null : c.key)}
                >
                  {c.needs && (
                    <circle r={r + 5} fill="none" stroke={colors.gold} strokeWidth={1.2} opacity={0.8}>
                      <animate attributeName="r" values={`${r + 2};${r + 9};${r + 2}`} dur="2.4s" repeatCount="indefinite" />
                      <animate attributeName="opacity" values="0.8;0;0.8" dur="2.4s" repeatCount="indefinite" />
                    </circle>
                  )}
                  <circle
                    r={r}
                    fill={col}
                    fillOpacity={active ? 0.55 : 0.32}
                    stroke={col}
                    strokeWidth={active ? 2 : 1.3}
                    strokeDasharray={c.sim ? '2.5 2' : undefined}
                    filter="url(#pinGlow)"
                  />
                  <circle r={1.8} fill="#fff" opacity={0.9} />
                  {c.opps.length > 1 && (
                    <text y={-r - 4} textAnchor="middle" fontSize={10} fill={colors.ink} className="font-mono">
                      {c.opps.length}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-[#070B14]/80 px-3 py-2 text-[11px] text-muted backdrop-blur">
          <span className="inline-flex items-center gap-1.5"><Dot c={colors.ratioGood} /> ≥1.5× living cost</span>
          <span className="inline-flex items-center gap-1.5"><Dot c={colors.ratioOk} /> 1–1.5×</span>
          <span className="inline-flex items-center gap-1.5"><Dot c={colors.ratioLow} /> &lt;1×</span>
          <span className="inline-flex items-center gap-1.5"><Dot c={colors.muted} /> pay unknown</span>
          <span className="hidden sm:inline">· size = monthly pay{maxPay ? ` (max ${formatINRCompact(maxPay)})` : ''}</span>
        </div>
      </GlassPanel>

      <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
        <GlassPanel>
          {selected ? (
            <>
              <SectionHeader
                size="sm"
                icon={Globe2}
                color="#2DD4BF"
                title={`${flagEmoji(selected.opps[0].country_iso2)} ${selected.opps[0].city ?? selected.opps[0].country_iso2 ?? 'Here'}`}
                kicker={`${selected.opps.length} role${selected.opps.length > 1 ? 's' : ''}`}
              />
              <ul className="mt-3 divide-y divide-white/[.05]">
                {selected.opps.map((o) => (
                  <li key={o.id} className="flex flex-wrap items-center gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <Link to={`/o/${o.id}`} className="inline-flex max-w-full items-center gap-1 truncate text-[14px] font-medium text-ink hover:text-cyan-200">
                        <span className="truncate">{o.title}</span>
                        <ExternalLink className="size-3.5 shrink-0 text-muted" />
                      </Link>
                      <div className="mt-0.5 flex items-center gap-2 text-[12px] text-muted">
                        {o.company_name}
                        <SimTag show={o.is_simulated} />
                      </div>
                    </div>
                    <StageChip stage={o.stage} />
                    <PayBadge pay={o.pay} />
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-muted">
              {placed.length ? 'Click a pin to see the roles there.' : 'No placed opportunities yet — pins appear as the Scout finds roles with a location.'}
            </p>
          )}
        </GlassPanel>
        <GlassPanel>
          <div className="space-y-3 text-[13px]">
            <Stat label="On the map" value={placed.length} />
            <Stat label="Cities" value={clusters.length} />
            <Stat label="Remote / unplaced" value={unplaced} icon={<Wifi className="size-3.5 text-muted" />} />
            <Stat label="Waiting on you" value={placed.filter((o) => o.needs_prerit).length} gold />
          </div>
        </GlassPanel>
      </div>
    </div>
  );
}

function Dot({ c }: { c: string }) {
  return <span className="inline-block size-2.5 rounded-full" style={{ backgroundColor: c, boxShadow: `0 0 8px ${c}` }} />;
}

function Stat({ label, value, icon, gold }: { label: string; value: number; icon?: React.ReactNode; gold?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="inline-flex items-center gap-1.5 text-muted">{icon}{label}</span>
      <span className={cn('font-display text-lg font-semibold tabular', gold && value ? 'text-amber-300' : 'text-ink')}>{value}</span>
    </div>
  );
}

function Pills<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-lg border border-white/10 bg-white/[.03] p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn('h-7 rounded-md px-2.5 text-[12px] font-medium transition-colors', value === o.value ? 'bg-white/[.1] text-ink' : 'text-muted hover:text-ink')}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
