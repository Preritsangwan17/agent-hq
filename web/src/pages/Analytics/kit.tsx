/**
 * Chart kit for the Analytics page (dataviz method): thin marks, hairline recessive grid, values in text tokens,
 * one colour per series (validated on the dark surface), a hover tooltip on every chart and a table view twin.
 * Gold is reserved for money, so pay/spend charts use it and everything else uses the categorical slots.
 */
import type { LucideIcon } from 'lucide-react';
import { ChartColumn, Table2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { GlassPanel } from '@/components/GlassPanel';
import { SectionHeader } from '@/components/SectionHeader';
import { cn } from '@/lib/cn';
import { colors } from '@/theme/tokens';

/** Categorical slots, dark steps (validated vs #0F1522: CVD ΔE ≥ 9.4, contrast ≥ 3:1). */
export const SERIES = ['#3987e5', '#d95926', '#199e70'] as const;
/** Money marks (a lone colour; contrast-checked on the dark surface). */
export const MONEY = colors.goldDeep;
export const SURFACE = '#0F1522';
export const GRID = 'rgba(255,255,255,0.06)';
export const AXIS_TICK = { fill: colors.muted, fontSize: 11 } as const;
export const VALUE_LABEL = { fill: colors.ink, fontSize: 11 } as const;

export interface Column<R> {
  key: string;
  label: string;
  align?: 'left' | 'right';
  render?: (row: R) => ReactNode;
}

export interface ChartCardProps<R> {
  title: string;
  kicker?: string;
  icon?: LucideIcon;
  color?: string;
  /** one line under the title: what is plotted and its n */
  note?: ReactNode;
  right?: ReactNode;
  /** controls or a legend under the title (wraps on phones instead of squeezing the title) */
  toolbar?: ReactNode;
  /** the table-view twin of the chart (every value reachable without hovering) */
  table?: { columns: Column<R>[]; rows: R[] };
  empty?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function ChartCard<R>({ title, kicker, icon, color = '#8B95A7', note, right, toolbar, table, empty, className, children }: ChartCardProps<R>) {
  const [asTable, setAsTable] = useState(false);
  return (
    <GlassPanel padding="lg" glow={color} glowStrength={0.16} className={cn('flex flex-col', className)}>
      <SectionHeader
        kicker={kicker}
        title={title}
        icon={icon}
        color={color}
        right={
          <>
            {right}
            {table && !empty && (
              <button
                type="button"
                onClick={() => setAsTable((v) => !v)}
                aria-pressed={asTable}
                aria-label={asTable ? `Show ${title} as a chart` : `Show ${title} as a table`}
                title={asTable ? 'Chart view' : 'Table view'}
                className="grid size-8 place-items-center rounded-lg border border-white/[.08] bg-white/[.03] text-muted transition-colors hover:text-ink"
              >
                {asTable ? <ChartColumn className="size-4" aria-hidden /> : <Table2 className="size-4" aria-hidden />}
              </button>
            )}
          </>
        }
      />
      {note && <p className="mt-1 text-[12.5px] text-muted">{note}</p>}
      {toolbar && <div className="mt-3 flex flex-wrap items-center gap-2">{toolbar}</div>}
      <div className="mt-4 min-w-0 flex-1">
        {empty ? empty : asTable && table ? <DataTable columns={table.columns} rows={table.rows} /> : children}
      </div>
    </GlassPanel>
  );
}

export function DataTable<R>({ columns, rows }: { columns: Column<R>[]; rows: R[] }) {
  return (
    <div className="max-h-[320px] overflow-auto rounded-xl border border-white/[.06]">
      <table className="w-full min-w-max text-left text-[12.5px]">
        <thead className="sticky top-0 bg-[#0F1522]">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn('px-3 py-2 font-medium text-muted', c.align === 'right' && 'text-right')}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[.05]">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-white/[.02]">
              {columns.map((c) => (
                <td key={c.key} className={cn('px-3 py-1.5 text-ink/90', c.align === 'right' && 'text-right tabular')}>
                  {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface TipRow {
  color: string;
  name: string;
  value: ReactNode;
}

/** Tooltip body: values lead (strong), series names follow, keyed with a short line in the series colour. */
export function TipBox({ title, rows }: { title: ReactNode; rows: TipRow[] }) {
  return (
    <div className="pointer-events-none min-w-[140px] rounded-xl border border-white/10 bg-[#0B111D]/95 px-3 py-2 text-[12px] shadow-xl backdrop-blur">
      <div className="mb-1 text-muted">{title}</div>
      {rows.map((r) => (
        <div key={r.name} className="flex items-center gap-2">
          <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ backgroundColor: r.color }} />
          <span className="font-semibold text-ink">{r.value}</span>
          <span className="text-muted">{r.name}</span>
        </div>
      ))}
    </div>
  );
}

/** Legend for ≥ 2 series (a line key per series, mirroring the marks). */
export function Legend({ items }: { items: { color: string; label: string; kind?: 'line' | 'rect' }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={it.kind === 'rect' ? 'size-2.5 rounded-[3px]' : 'h-0.5 w-3.5 rounded-full'}
            style={{ backgroundColor: it.color }}
          />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

export function shortDate(iso: string): string {
  const [, m, d] = iso.split('-').map(Number);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d} ${months[(m ?? 1) - 1]}`;
}

/** Height for a horizontal bar chart: one 28px band per row plus the axis band (never a nested scroll). */
export function barsHeight(rows: number): number {
  return Math.max(120, rows * 30 + 24);
}
