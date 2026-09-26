# Agent HQ — web

Vite + React 19 + TypeScript + Tailwind v4 + motion. Dark "mission control" SPA for the Agent HQ API
(`docs/CONTRACT.md` §3–§5). In production FastAPI serves the built `web/dist` at `/`.

## Commands

```bash
cd web
npm install                      # deps are pinned in package.json / package-lock.json
npm run dev                      # http://localhost:5173, proxies /api → http://127.0.0.1:8765
VITE_API_TARGET=http://127.0.0.1:8876 npm run dev   # proxy to another backend port
npm run dev:mock                 # no backend: in-browser simulator (VITE_MOCK=1)
npm run build                    # tsc -b (zero errors required) + vite build → dist/
npm run typecheck
```

The proxy keeps the `Host` header as-is (`changeOrigin: false`) so the backend's host allowlist sees `localhost`;
the dev origin `http://localhost:5173` is allowed for mutations.

## Mock mode (`VITE_MOCK=1`)

`src/lib/mock` patches `window.fetch` for `/api/*` and `window.EventSource` for `/api/stream`, so `api.ts`,
`stream.ts` and the store run their real code paths against a simulator:

- 10 agents working a task queue (2–8 s per task ÷ `sim_speed`, progress + `now_line` + tok/s over `agent.live`),
  5 % transient failures with retries, Scout discovering fictional companies every 25–60 s.
- Stage flow found → verified/filtered → drafted → checked → applied → replied → interview/offer/rejected,
  with `task.handoff`, `opp.created`, `opp.stage`, `needs.created`, `mail.mock_sent`, `notification`, `log`,
  `control.pause`, `worker.heartbeat` events — the same shapes as the real SSE.
- Pay in INR/USD/EUR/GBP/CHF/JPY/SGD/CAD/AED/TWD incl. hourly-variable, unknown, fee-required and funded programs;
  4 frozen legacy-like items (₹25,000/mo, ₹25,000–40,000/mo, USD 13.25–27.50/hr, NT$15,000/mo).
- Pause/resume, freeze, settings, agent create/patch/delete, needs, stage override and `/api/sim/reset`
  (which triggers the `resync` path) all work.

URL switches (persist per tab): `?mock_auth=out` (logged out → login redirect), `?mock_setup=1`
("Set your passcode"), `?mock_speed=2`, `?mock_paused=1`. Passcode `wrong` is rejected; anything ≥ 6 chars works.
Mock code is excluded from production builds.

## Screenshots

```bash
VITE_MOCK=1 npx vite --port 5180 &                       # from web/
../.venv/bin/python scripts/shots.py --base http://localhost:5180 \
  --out ../data/test/shots/<name> / /pipeline "/login?mock_auth=out"
```

1440×900 and 390×844 (headless Chrome via `channel="chrome"`); non-localhost requests are aborted; console
errors make it exit 1.

## Layout

```
src/
  main.tsx, App.tsx          entry (fonts, mock install, providers) and routes (lazy pages)
  index.css                  Tailwind tokens (@theme), glass/text-money utilities, backdrop, keyframes
  theme/tokens.ts            colors, agent presets, STAGE_META, MODE_META, withAlpha()
  lib/types.ts               CONTRACT §5 types (+ EVENT_TYPES, EventDataMap, isEvent)
  lib/api.ts                 typed REST client (`api.*`), ApiError, 401 → /login
  lib/stream.ts              SSE client (`hqStream`, `useLiveConnection`), resync + backoff
  lib/store.ts               zustand live state, per-frame batching, actions, selector hooks
  lib/bus.ts                 handoffBus (graph particles), eventBus
  lib/queries.ts             TanStack Query client + useOpportunityDetail/useEventsQuery/useAgentsMeta/useHealth
  lib/format.ts              ₹ formatting (Indian grouping, ₹1.2L), currencies, IST time, durations
  lib/hooks.ts               useNow, useIsMobile, usePersistentState
  lib/mock/                  simulator (VITE_MOCK=1 only)
  components/                shared kit (below), barrel: `import { PayBadge } from '@/components'`
  layout/                    AppShell, Sidebar, Header, KillSwitch, StatusCluster, MobileTabBar, RequireAuth
  pages/<Name>/index.tsx     one module per route (default export) — page agents own these
```

## Rules for page agents

- Only replace files in `src/pages/<Page>/` (add sub-files there freely). Don't add npm deps — everything in
  PLAN.md is installed: `@xyflow/react`, `recharts`, `d3-geo`, `topojson-client`, `world-atlas`,
  `react-virtuoso`, `lucide-react`, `motion`, `@tanstack/react-query`, `zustand`, `clsx`.
- Pages render inside the shell only after the first snapshot loaded, so the store is populated.
- Live data: `useHQ(selector)` / `useAgentsList()` / `useOppList()` / `useOpp(id)` / `useAgentLive(id)` /
  `useOpenNeeds()` / `useStats()` / `useSettings()`. **`live[agentId]` is the authoritative AgentLive**;
  `agents[id].live` is the snapshot copy and is not updated by the stream. Events: `useHQ(s => s.events)`
  (oldest first, max 2000).
- Actions: `pauseAll`, `resumeAll`, `setFreezeOutbound`, `updateSettings`, `patchAgent`, `resolveNeed`,
  `overrideStage` from `@/lib/store`; anything else via `api.*`.
- Graph particles: `handoffBus.on(({from_agent, to_agent, capability, opportunity_id, id}) => …)` — returns
  an unsubscribe function.
- Style: `glass` utility or `<GlassPanel>`; tokens `bg-bg`, `bg-surface-1/2`, `text-ink`, `text-muted`,
  `text-faint`, `text-agent-<id>`, `font-display` (numbers/titles), `font-mono` (logs), `tabular`.
  Red (`danger`) only for errors and the kill switch; gold (`text-money`, `money` prop) only for pay.
  Animate only transform/opacity; `MotionConfig reducedMotion="user"` is set globally.
- Times on the wire are UTC; display with `formatDateTimeIST`/`formatClockIST`/`formatRelative`.
- Layout must work at 390 px: no horizontal page scroll (use `min-w-0` on flex/grid children).
- Backend note: EventSource only receives *named* events we subscribe to — the contract list is
  `EVENT_TYPES` in `lib/types.ts` (plus a few tolerated extras in `stream.ts`). New event types must be added there.

## Component API (src/components)

| Component | Props |
|---|---|
| `GlassPanel` | `as?: 'div'\|'section'\|'article'\|'aside'`, `glow?: hex`, `glowStrength?: 0..1 (0.35)`, `padding?: 'none'\|'sm'\|'md'\|'lg'`, `interactive?`, `accentTop?`, + div attrs |
| `StatCounter` | `value: number\|null`, `label`, `format?: (n)=>string`, `icon?: LucideIcon`, `accent?: hex`, `money?` (gold), `sub?`, `aside?`, `size?: 'sm'\|'md'\|'lg'`, `duration?` |
| `PayBadge` | `pay: Pay\|null`, `size?: 'sm'\|'md'\|'lg'`, `compact?` (₹1.2L), `showRatio? = true`, `showOriginal? = true`, `tooltip? = true`, `align?: 'left'\|'right'`, `className` (applies to outermost element) |
| `PayProvenance` | `pay` — the provenance table (detail page) · helpers `payKind(pay)`, `ratioColor(r)`, `coveredLabel(pay)` |
| `AgentAvatar` | `agent?: {id,name,avatar,color,status?}` or `id?` (store lookup), `size?: 'xs'\|'sm'\|'md'\|'lg'\|'xl'\|px`, `working?` (default status==='working'), `showStatus?`, `title?` |
| `StageChip` | `stage: Stage`, `size?: 'sm'\|'md'`, `dot? = true` |
| `SimTag` | `show? = true` (pass `opp.is_simulated`) |
| `Countdown` | `deadline: iso\|null`, `confidence?`, `compact?`, `showIcon? = true` |
| `EmptyState` | `icon?`, `title`, `hint?`, `action?`, `compact?`, `color?` |
| `Sparkline` | `data: number[]`, `width? = 96`, `height? = 28`, `color?`, `fill? = true`, `strokeWidth?`, `label?` |
| `SectionHeader` | `title`, `kicker?`, `icon?`, `color?`, `right?`, `as?: 'h1'\|'h2'\|'h3'`, `size?: 'sm'\|'md'\|'lg'` |
| `Tooltip` | `content`, `children`, `side?: 'top'\|'bottom'`, `delay?`, `maxWidth?`, `triggerClassName?`, `disabled?` (portal, never clipped) |
| `Button` | `variant?: 'primary'\|'secondary'\|'ghost'\|'danger'`, `size?: 'sm'\|'md'\|'lg'`, `icon?`, `iconRight?`, `loading?`, + button attrs |
| `HoldButton` | `onConfirm`, `holdMs? = 1200`, `color?`, `holdingLabel?`, `disabled?` |
| `Badge` | `children`, `color?`, `icon?`, `size?: 'xs'\|'sm'\|'md'`, `mono?`, `solid?` |
| `StatusDot` | `color`, `pulse?`, `size? = 8`, `label?` |
| `ProgressBar` | `value: 0..1\|null` (null = indeterminate), `color?`, `height? = 4` |
| `PagePlaceholder` | `title`, `kicker?`, `icon`, `color?`, `description` |
