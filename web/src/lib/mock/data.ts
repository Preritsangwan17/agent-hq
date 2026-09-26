/**
 * Static data for the in-browser simulator: the 10-agent team, a pool of FICTIONAL organisations (".example"
 * URLs) with pay in local currencies, provisional living costs, FX seeds and a few legacy-like frozen items.
 * Nothing here is real data; it only exercises the UI.
 */
import { AGENT_PRESETS } from '@/theme/tokens';
import type {
  Agent,
  AgentSchedule,
  ApplyChannel,
  CostTier,
  LivingCostConfidence,
  OppKind,
  Pay,
  PayPeriod,
  PayStatus,
  RoleType,
  WorkMode,
} from '../types';

// ── agents ────────────────────────────────────────────────────────────

interface AgentSeed {
  role: string;
  capabilities: string[];
  cost_tier: CostTier;
  schedule: AgentSchedule;
  model: string | null;
  side_effects?: string[];
  description: string;
  /** typical generation speed range for the sim (null = no LLM) */
  tokS: [number, number] | null;
}

const AGENT_SEEDS: Record<string, AgentSeed> = {
  scout: {
    role: 'scout',
    capabilities: ['discover.ats', 'discover.program_page', 'parse.job'],
    cost_tier: 'local',
    schedule: { mode: 'interval', minutes: 1 },
    model: 'mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit',
    description: 'Finds opportunities on ATS boards, program pages and alert emails.',
    tokS: [190, 260],
  },
  verifier: {
    role: 'verifier',
    capabilities: ['verify.link', 'verify.deadline', 'verify.eligibility', 'verify.pay', 'verify.scam', 'score.fit'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: 'mlx:mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit',
    description: 'Checks link, deadline, eligibility, pay vs living cost and scam signals, then scores fit.',
    tokS: [82, 104],
  },
  writer: {
    role: 'writer',
    capabilities: ['draft.cover_letter'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: 'mlx:mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit',
    description: 'Drafts cover letters sentence-by-sentence from verified facts and job quotes.',
    tokS: [78, 98],
  },
  factchecker: {
    role: 'factchecker',
    capabilities: ['factcheck.deterministic', 'factcheck.sentence', 'check.quality'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: 'mlx:mlx-community/Qwen2.5-7B-Instruct-4bit',
    description: 'Runs the deterministic fact rules and an independent per-sentence verifier.',
    tokS: [128, 176],
  },
  reviewer: {
    role: 'reviewer',
    capabilities: ['factcheck.signoff'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: 'ollama:gemma3:12b',
    description: 'Independent final sign-off: a second local model when one qualifies, Grok only when needed.',
    tokS: [90, 140],
  },
  resume: {
    role: 'resume',
    capabilities: ['build.resume'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: null,
    description: 'Builds the tailored one-page résumé PDF from approved bullets only.',
    tokS: null,
  },
  applicant: {
    role: 'applicant',
    capabilities: ['apply.email_send', 'apply.manual_pack'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: null,
    side_effects: ['apply.email_send'],
    description: 'Sends gated email applications (mock mailbox in sim) or prepares a 2-minute manual pack.',
    tokS: null,
  },
  inbox: {
    role: 'inbox',
    capabilities: ['inbox.poll', 'inbox.classify'],
    cost_tier: 'local',
    schedule: { mode: 'interval', minutes: 3 },
    model: 'mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit',
    description: 'Polls the inbox and classifies replies (interview / rejection / info request …).',
    tokS: [200, 290],
  },
  followup: {
    role: 'followup',
    capabilities: ['followup.schedule'],
    cost_tier: 'local',
    schedule: { mode: 'on_demand' },
    model: null,
    description: 'Schedules exactly one follow-up 10 days after an email application with no reply.',
    tokS: null,
  },
  strategist: {
    role: 'strategist',
    capabilities: ['strategy.daily_review'],
    cost_tier: 'cloud',
    schedule: { mode: 'cron', cron: '0 7 * * *' },
    model: 'xai:grok-4-fast',
    description: 'Daily review of what worked: sources, keywords and thresholds (proposals only).',
    tokS: null,
  },
};

export function agentTokS(id: string): [number, number] | null {
  return AGENT_SEEDS[id]?.tokS ?? null;
}

export function buildAgents(): Agent[] {
  return AGENT_PRESETS.map((p) => {
    const s = AGENT_SEEDS[p.id];
    return {
      id: p.id,
      name: p.name,
      avatar: p.emoji,
      color: p.color,
      role: s.role,
      adapter: 'sim',
      model: s.model,
      capabilities: s.capabilities,
      cost_tier: s.cost_tier,
      concurrency: 1,
      schedule: s.schedule,
      enabled: true,
      paused: false,
      status: 'idle',
      builtin: true,
      side_effects: s.side_effects ?? [],
      tasks_today: 0,
      errors_today: 0,
      tokens_today: 0,
      restarts: 0,
      last_error: null,
      live: null,
      description: s.description,
    } satisfies Agent;
  });
}

export const CAPABILITY_VOCAB: string[] = [
  'discover.ats', 'discover.feed', 'discover.program_page', 'discover.email_alerts', 'parse.job', 'classify.title',
  'verify.link', 'verify.deadline', 'verify.eligibility', 'verify.eligibility_hard', 'verify.pay', 'verify.scam',
  'score.fit', 'draft.cover_letter', 'draft.cold_email', 'draft.research_statement', 'draft.form_answers',
  'draft.followup', 'polish.final', 'factcheck.deterministic', 'factcheck.sentence', 'factcheck.signoff',
  'check.quality', 'build.resume', 'apply.email_send', 'apply.ats_submit', 'apply.manual_pack', 'inbox.poll',
  'inbox.classify', 'reply.draft', 'reply.send', 'followup.schedule', 'followup.send', 'strategy.daily_review',
  'debug.failed_run', 'summarize',
];
export const RESERVED_SIDE_EFFECTS = ['apply.email_send', 'apply.ats_submit', 'reply.send', 'followup.send'];

// ── money ─────────────────────────────────────────────────────────────

export const FX_DATE = '2026-09-25';
/** INR per 1 unit (seed values for the mock only). */
export const FX: Record<string, number> = {
  INR: 1, USD: 88.2, EUR: 103.4, GBP: 118.6, CHF: 110.8, JPY: 0.598, SGD: 68.4, CAD: 63.5, AED: 24.0, TWD: 2.78,
};

interface LivingCost {
  city: string;
  monthly_inr: number;
  confidence: LivingCostConfidence;
}

export const LIVING: Record<string, LivingCost> = {
  'IN-BLR': { city: 'Bengaluru', monthly_inr: 32000, confidence: 'provisional' },
  'IN-PNQ': { city: 'Pune', monthly_inr: 26000, confidence: 'provisional' },
  'IN-HYD': { city: 'Hyderabad', monthly_inr: 27000, confidence: 'provisional' },
  'IN-BOM': { city: 'Mumbai', monthly_inr: 38000, confidence: 'provisional' },
  'IN-GGN': { city: 'Gurugram', monthly_inr: 30000, confidence: 'provisional' },
  'IN-NOI': { city: 'Noida', monthly_inr: 24000, confidence: 'provisional' },
  'IN-HOME': { city: 'Greater Noida (home, remote work)', monthly_inr: 15000, confidence: 'provisional' },
  'US-SFO': { city: 'San Francisco', monthly_inr: 285000, confidence: 'provisional' },
  'US-SEA': { city: 'Seattle', monthly_inr: 235000, confidence: 'provisional' },
  'CH-ZRH': { city: 'Zürich', monthly_inr: 215000, confidence: 'provisional' },
  'CH-LSN': { city: 'Lausanne', monthly_inr: 190000, confidence: 'provisional' },
  'DE-BER': { city: 'Berlin', monthly_inr: 110000, confidence: 'provisional' },
  'DE-MUC': { city: 'Munich', monthly_inr: 128000, confidence: 'provisional' },
  'TW-HSZ': { city: 'Hsinchu', monthly_inr: 52000, confidence: 'provisional' },
  'TW-TPE': { city: 'Taipei', monthly_inr: 60000, confidence: 'provisional' },
  'TW-CYI': { city: 'Chiayi', monthly_inr: 38000, confidence: 'provisional' },
  'JP-TYO': { city: 'Tokyo', monthly_inr: 118000, confidence: 'provisional' },
  'JP-KYO': { city: 'Kyoto', monthly_inr: 98000, confidence: 'provisional' },
  'SG-SIN': { city: 'Singapore', monthly_inr: 150000, confidence: 'provisional' },
  'GB-LON': { city: 'London', monthly_inr: 165000, confidence: 'provisional' },
  'GB-EDI': { city: 'Edinburgh', monthly_inr: 120000, confidence: 'provisional' },
  'CA-TOR': { city: 'Toronto', monthly_inr: 140000, confidence: 'provisional' },
  'AE-DXB': { city: 'Dubai', monthly_inr: 115000, confidence: 'provisional' },
  'NL-AMS': { city: 'Amsterdam', monthly_inr: 135000, confidence: 'provisional' },
};

export interface PaySpec {
  status: PayStatus;
  raw: string;
  min?: number;
  max?: number;
  currency?: string;
  period?: PayPeriod;
  /** funded programs: covered items + monthly allowance in local currency */
  funded?: { housing?: boolean; meals?: boolean; travel?: boolean; allowance?: number };
}

const PER_MONTH: Partial<Record<PayPeriod, number>> = { month: 1, year: 1 / 12, week: 4.33, day: 21.7 };

export function buildPay(spec: PaySpec, livingKey: string): Pay {
  const cur = spec.currency ?? null;
  const rate = cur ? FX[cur] ?? null : null;
  const lc = LIVING[livingKey];
  const pay: Pay = {
    raw: spec.raw,
    status: spec.status,
    min: spec.min ?? null,
    max: spec.max ?? spec.min ?? null,
    currency: cur,
    period: spec.period ?? null,
    monthly_inr_min: null,
    monthly_inr_mid: null,
    monthly_inr_max: null,
    hourly_inr_min: null,
    hourly_inr_max: null,
    fx_rate: cur && cur !== 'INR' ? rate : cur === 'INR' ? 1 : null,
    fx_date: cur && cur !== 'INR' ? FX_DATE : null,
    living_cost_monthly_inr: lc?.monthly_inr ?? null,
    living_cost_basis: lc
      ? `${lc.city}: shared room + food + local transport (provisional estimate, researched in phase c)`
      : null,
    living_cost_confidence: lc?.confidence ?? null,
    ratio: null,
    benefits: {},
  };
  if (rate == null || spec.min == null) {
    if (spec.funded) pay.benefits = { ...spec.funded, allowance_inr: undefined };
    return pay;
  }
  const lo = spec.min;
  const hi = spec.max ?? spec.min;
  if (spec.status === 'variable' || spec.period === 'hour') {
    pay.hourly_inr_min = Math.round(lo * rate);
    pay.hourly_inr_max = Math.round(hi * rate);
    return pay;
  }
  const k = PER_MONTH[spec.period ?? 'month'] ?? 1;
  pay.monthly_inr_min = Math.round(lo * k * rate);
  pay.monthly_inr_max = Math.round(hi * k * rate);
  pay.monthly_inr_mid = Math.round(((lo + hi) / 2) * k * rate);
  if (spec.funded) {
    const { allowance, ...covered } = spec.funded;
    pay.benefits = { ...covered, allowance_inr: allowance != null ? Math.round(allowance * rate) : undefined };
  }
  if (pay.living_cost_monthly_inr) {
    pay.ratio = Math.round((pay.monthly_inr_min / pay.living_cost_monthly_inr) * 100) / 100;
  }
  return pay;
}

// ── opportunity pool (fictional) ──────────────────────────────────────

export type PoolFlag = 'scam' | 'ineligible' | 'expired' | 'unknown_pay';

export interface PoolItem {
  key: string;
  company: string;
  title: string;
  kind: OppKind;
  role_type: RoleType;
  city: string;
  country: string;
  lat: number;
  lon: number;
  work_mode: WorkMode;
  channel: ApplyChannel;
  pay: PaySpec;
  living: string;
  source: string;
  /** days until deadline; null = rolling */
  deadlineDays: number | null;
  flag?: PoolFlag;
  filterReason?: string;
  /** fit score the verifier will assign */
  fit: number;
  page: string;
}

const P = (x: Omit<PoolItem, 'page'> & { page?: string }): PoolItem => ({
  page: `${x.company.split(/[ (]/)[0]} careers page`,
  ...x,
});

export const POOL: PoolItem[] = [
  P({ key: 'lumina', company: 'Lumina Robotics', title: 'ML Research Intern — Perception', kind: 'internship', role_type: 'ml', city: 'Bengaluru', country: 'IN', lat: 12.97, lon: 77.59, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: 'INR 30,000 - 45,000/month', min: 30000, max: 45000, currency: 'INR', period: 'month' }, living: 'IN-BLR', source: 'Greenhouse · lumina-robotics', deadlineDays: 12, fit: 84 }),
  P({ key: 'kestrel', company: 'Kestrel Data Labs', title: 'Data Science Intern', kind: 'internship', role_type: 'data', city: 'Pune', country: 'IN', lat: 18.52, lon: 73.86, work_mode: 'hybrid', channel: 'email', pay: { status: 'listed', raw: '₹22,000 per month', min: 22000, currency: 'INR', period: 'month' }, living: 'IN-PNQ', source: 'Lever · kestrel', deadlineDays: 9, fit: 71 }),
  P({ key: 'vanta', company: 'Vantablack AI', title: 'Applied ML Intern (NLP)', kind: 'internship', role_type: 'ml', city: 'Hyderabad', country: 'IN', lat: 17.39, lon: 78.49, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: 'INR 40,000–60,000 / month', min: 40000, max: 60000, currency: 'INR', period: 'month' }, living: 'IN-HYD', source: 'Ashby · vantablack', deadlineDays: 21, fit: 88 }),
  P({ key: 'northwind', company: 'Northwind Genomics', title: 'Bioinformatics ML Intern', kind: 'internship', role_type: 'ml', city: 'San Francisco', country: 'US', lat: 37.77, lon: -122.42, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'variable', raw: 'USD 38 – 52/hour (hours vary)', min: 38, max: 52, currency: 'USD', period: 'hour' }, living: 'US-SFO', source: 'Greenhouse · northwind', deadlineDays: 30, fit: 66 }),
  P({ key: 'helix', company: 'Helix Quantum Institute', title: 'Summer Research Fellow — ML Systems', kind: 'fellowship', role_type: 'research', city: 'Zürich', country: 'CH', lat: 47.37, lon: 8.54, work_mode: 'onsite', channel: 'portal', pay: { status: 'listed', raw: 'CHF 1,600/month stipend + housing + travel', min: 1600, currency: 'CHF', period: 'month', funded: { housing: true, travel: true, allowance: 1600 } }, living: 'CH-ZRH', source: 'Program page · helix', deadlineDays: 40, fit: 79 }),
  P({ key: 'alpenglow', company: 'Alpenglow Institute of Technology', title: 'Summer Undergraduate Research Program (AI)', kind: 'program', role_type: 'research', city: 'Lausanne', country: 'CH', lat: 46.52, lon: 6.63, work_mode: 'onsite', channel: 'portal', pay: { status: 'listed', raw: 'Accommodation, meals and travel covered + CHF 800/month', min: 800, currency: 'CHF', period: 'month', funded: { housing: true, meals: true, travel: true, allowance: 800 } }, living: 'CH-LSN', source: 'Program page · alpenglow', deadlineDays: 55, fit: 81 }),
  P({ key: 'rheinwerk', company: 'Rheinwerk Analytics', title: 'Werkstudent Machine Learning (20 h/week)', kind: 'part_time', role_type: 'ml', city: 'Berlin', country: 'DE', lat: 52.52, lon: 13.4, work_mode: 'hybrid', channel: 'email', pay: { status: 'listed', raw: 'EUR 1,380/month (20h)', min: 1380, currency: 'EUR', period: 'month' }, living: 'DE-BER', source: 'Personio · rheinwerk', deadlineDays: 18, fit: 62, flag: 'ineligible', filterReason: 'Ineligible: requires enrolment at a German university' }),
  P({ key: 'isar', company: 'Isar Mobility', title: 'Data Engineering Intern', kind: 'internship', role_type: 'data', city: 'Munich', country: 'DE', lat: 48.14, lon: 11.58, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: '€2,100 monthly', min: 2100, currency: 'EUR', period: 'month' }, living: 'DE-MUC', source: 'Greenhouse · isar-mobility', deadlineDays: 16, fit: 69 }),
  P({ key: 'formosa', company: 'Formosa Semicon Lab', title: 'TEEP Research Intern — Computer Vision', kind: 'research_internship', role_type: 'research', city: 'Hsinchu', country: 'TW', lat: 24.8, lon: 120.97, work_mode: 'onsite', channel: 'email', pay: { status: 'listed', raw: 'NT$18,000 – 20,000/month', min: 18000, max: 20000, currency: 'TWD', period: 'month' }, living: 'TW-HSZ', source: 'TEEP table', deadlineDays: 25, fit: 77 }),
  P({ key: 'tatami', company: 'Tatami Systems', title: 'ML Engineer Intern', kind: 'internship', role_type: 'ml', city: 'Tokyo', country: 'JP', lat: 35.68, lon: 139.69, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: '¥250,000 per month', min: 250000, currency: 'JPY', period: 'month' }, living: 'JP-TYO', source: 'Ashby · tatami', deadlineDays: 20, fit: 73 }),
  P({ key: 'kaizen', company: 'Kaizen Vision', title: 'Research Internship — Robot Learning', kind: 'research_internship', role_type: 'research', city: 'Kyoto', country: 'JP', lat: 35.01, lon: 135.77, work_mode: 'onsite', channel: 'email', pay: { status: 'variable', raw: '¥1,800/hour, hours by agreement', min: 1800, currency: 'JPY', period: 'hour' }, living: 'JP-KYO', source: 'Lab page · kaizen', deadlineDays: null, fit: 68 }),
  P({ key: 'merlion', company: 'Merlion Fintech', title: 'Quant / ML Intern', kind: 'internship', role_type: 'ml', city: 'Singapore', country: 'SG', lat: 1.29, lon: 103.85, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: 'SGD 2,500 – 3,500 / month', min: 2500, max: 3500, currency: 'SGD', period: 'month' }, living: 'SG-SIN', source: 'Lever · merlion', deadlineDays: 14, fit: 74 }),
  P({ key: 'thames', company: 'Thames Neural', title: 'AI Research Intern', kind: 'internship', role_type: 'research', city: 'London', country: 'GB', lat: 51.51, lon: -0.13, work_mode: 'hybrid', channel: 'email', pay: { status: 'listed', raw: '£2,400/month', min: 2400, currency: 'GBP', period: 'month' }, living: 'GB-LON', source: 'Greenhouse · thames-neural', deadlineDays: 11, fit: 86 }),
  P({ key: 'maple', company: 'Maple Leaf Robotics', title: 'ML Co-op (4 months)', kind: 'internship', role_type: 'ml', city: 'Toronto', country: 'CA', lat: 43.65, lon: -79.38, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: 'CAD 3,800/month', min: 3800, currency: 'CAD', period: 'month' }, living: 'CA-TOR', source: 'Ashby · maple-robotics', deadlineDays: 19, fit: 64, flag: 'ineligible', filterReason: 'Ineligible: co-op students at Canadian institutions only' }),
  P({ key: 'oasis', company: 'Oasis Cloud', title: 'Data Science Intern', kind: 'internship', role_type: 'data', city: 'Dubai', country: 'AE', lat: 25.2, lon: 55.27, work_mode: 'onsite', channel: 'email', pay: { status: 'listed', raw: 'AED 5,000 monthly', min: 5000, currency: 'AED', period: 'month' }, living: 'AE-DXB', source: 'Lever · oasis-cloud', deadlineDays: 10, fit: 70 }),
  P({ key: 'canal', company: 'Canal Street AI', title: 'ML Intern (Remote)', kind: 'internship', role_type: 'ml', city: 'Remote · Amsterdam', country: 'NL', lat: 52.37, lon: 4.9, work_mode: 'remote', channel: 'email', pay: { status: 'listed', raw: 'EUR 1,000/month', min: 1000, currency: 'EUR', period: 'month' }, living: 'IN-HOME', source: 'Recruitee · canal-street', deadlineDays: 15, fit: 83 }),
  P({ key: 'sahyadri', company: 'Sahyadri Health AI', title: 'Computer Vision Intern', kind: 'internship', role_type: 'ml', city: 'Mumbai', country: 'IN', lat: 19.08, lon: 72.88, work_mode: 'onsite', channel: 'email', pay: { status: 'unknown', raw: 'Not listed' }, living: 'IN-BOM', source: 'Careers page · sahyadri', deadlineDays: 8, fit: 72, flag: 'unknown_pay' }),
  P({ key: 'bluefin', company: 'Bluefin Retail', title: 'Analytics Intern', kind: 'internship', role_type: 'data', city: 'Gurugram', country: 'IN', lat: 28.46, lon: 77.03, work_mode: 'onsite', channel: 'email', pay: { status: 'listed', raw: 'INR 15,000/month', min: 15000, currency: 'INR', period: 'month' }, living: 'IN-GGN', source: 'Lever · bluefin', deadlineDays: 6, fit: 58 }),
  P({ key: 'arcadia', company: 'Arcadia Labs', title: 'Part-time ML Contractor', kind: 'contract', role_type: 'ml', city: 'Remote · Seattle', country: 'US', lat: 47.61, lon: -122.33, work_mode: 'remote', channel: 'email', pay: { status: 'variable', raw: 'USD 25/hour, flexible hours', min: 25, currency: 'USD', period: 'hour' }, living: 'IN-HOME', source: 'Ashby · arcadia', deadlineDays: null, fit: 67 }),
  P({ key: 'ganga', company: 'Ganga Analytics', title: 'NLP Intern (Indic languages)', kind: 'internship', role_type: 'ml', city: 'Remote · Noida', country: 'IN', lat: 28.54, lon: 77.39, work_mode: 'remote', channel: 'email', pay: { status: 'listed', raw: 'INR 25,000/month', min: 25000, currency: 'INR', period: 'month' }, living: 'IN-HOME', source: 'Lever · ganga', deadlineDays: 13, fit: 80 }),
  P({ key: 'pixelwise', company: 'Pixelwise Studio', title: 'Generative AI Intern', kind: 'internship', role_type: 'ml', city: 'Bengaluru', country: 'IN', lat: 12.93, lon: 77.62, work_mode: 'hybrid', channel: 'ats_form', pay: { status: 'listed', raw: '₹35,000/month', min: 35000, currency: 'INR', period: 'month' }, living: 'IN-BLR', source: 'Greenhouse · pixelwise', deadlineDays: 17, fit: 76 }),
  P({ key: 'jade', company: 'Jade Mountain AI Lab', title: 'Visiting Student Researcher', kind: 'research_internship', role_type: 'research', city: 'Taipei', country: 'TW', lat: 25.03, lon: 121.56, work_mode: 'onsite', channel: 'email', pay: { status: 'listed', raw: 'NT$20,000/month + dorm', min: 20000, currency: 'TWD', period: 'month', funded: { housing: true, allowance: 20000 } }, living: 'TW-TPE', source: 'Lab page · jade-mountain', deadlineDays: 33, fit: 78 }),
  P({ key: 'certify', company: 'CertifyMe Global', title: 'AI Internship with Certificate', kind: 'internship', role_type: 'ml', city: 'Remote', country: 'IN', lat: 28.61, lon: 77.21, work_mode: 'remote', channel: 'email', pay: { status: 'fee_required', raw: 'Registration fee ₹2,999 (refundable*)' }, living: 'IN-HOME', source: 'Alert email', deadlineDays: 2, fit: 12, flag: 'scam', filterReason: 'Scam signals: registration fee, certificate-only wording' }),
  P({ key: 'skillforge', company: 'SkillForge Academy', title: 'Virtual Machine Learning Internship', kind: 'internship', role_type: 'ml', city: 'Remote', country: 'IN', lat: 19.07, lon: 72.87, work_mode: 'remote', channel: 'email', pay: { status: 'unpaid', raw: 'Unpaid — certificate provided' }, living: 'IN-HOME', source: 'Alert email', deadlineDays: 4, fit: 9, flag: 'scam', filterReason: 'Known internship mill; unpaid certificate program' }),
  P({ key: 'orion', company: 'Orion Payments', title: 'ML Engineer (2026 graduates only)', kind: 'job', role_type: 'ml', city: 'Bengaluru', country: 'IN', lat: 12.98, lon: 77.64, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: 'INR 14 – 18 LPA', min: 1400000, max: 1800000, currency: 'INR', period: 'year' }, living: 'IN-BLR', source: 'Greenhouse · orion', deadlineDays: 20, fit: 41, flag: 'ineligible', filterReason: 'Ineligible: "2026 graduates only"' }),
  P({ key: 'nimbus', company: 'Nimbus Semiconductors', title: 'Final-year Intern — ML for EDA', kind: 'internship', role_type: 'ml', city: 'Noida', country: 'IN', lat: 28.54, lon: 77.33, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'listed', raw: '₹45,000/month', min: 45000, currency: 'INR', period: 'month' }, living: 'IN-NOI', source: 'Workday · nimbus', deadlineDays: 22, fit: 44, flag: 'ineligible', filterReason: 'Ineligible: 7th-semester students only' }),
  P({ key: 'aurora', company: 'Aurora Climate AI', title: 'Summer Research Intern', kind: 'research_internship', role_type: 'research', city: 'Edinburgh', country: 'GB', lat: 55.95, lon: -3.19, work_mode: 'onsite', channel: 'email', pay: { status: 'listed', raw: '£1,900/month', min: 1900, currency: 'GBP', period: 'month' }, living: 'GB-EDI', source: 'Program page · aurora', deadlineDays: -3, fit: 70, flag: 'expired', filterReason: 'Deadline passed (3 days ago)' }),
  P({ key: 'sakura', company: 'Sakura Speech', title: 'Speech ML Intern', kind: 'internship', role_type: 'ml', city: 'Tokyo', country: 'JP', lat: 35.66, lon: 139.73, work_mode: 'hybrid', channel: 'ats_form', pay: { status: 'variable', raw: '¥2,000/hour', min: 2000, currency: 'JPY', period: 'hour' }, living: 'JP-TYO', source: 'Ashby · sakura-speech', deadlineDays: 27, fit: 65 }),
  P({ key: 'denali', company: 'Denali Health', title: 'ML Research Assistant (part-time)', kind: 'part_time', role_type: 'research', city: 'Remote · Seattle', country: 'US', lat: 47.6, lon: -122.3, work_mode: 'remote', channel: 'email', pay: { status: 'listed', raw: 'USD 1,500/month (20h/week)', min: 1500, currency: 'USD', period: 'month' }, living: 'IN-HOME', source: 'Lever · denali', deadlineDays: 24, fit: 82 }),
  P({ key: 'polaris', company: 'Polaris Freight', title: 'Contract Data Analyst (3 months)', kind: 'contract', role_type: 'data', city: 'Remote · Gurugram', country: 'IN', lat: 28.47, lon: 77.05, work_mode: 'remote', channel: 'email', pay: { status: 'listed', raw: 'INR 50,000 per month', min: 50000, currency: 'INR', period: 'month' }, living: 'IN-HOME', source: 'Lever · polaris', deadlineDays: 9, fit: 63 }),
];

// ── legacy-like frozen items (is_simulated = false) ───────────────────

export interface LegacySeed extends PoolItem {
  notes: string;
  letter: string;
}

export const LEGACY: LegacySeed[] = [
  {
    ...P({ key: 'legacy-quill', company: 'Quillstone Analytics', title: 'Data Science Intern', kind: 'internship', role_type: 'data', city: 'Noida', country: 'IN', lat: 28.57, lon: 77.32, work_mode: 'hybrid', channel: 'email', pay: { status: 'listed', raw: 'INR 25,000/month', min: 25000, currency: 'INR', period: 'month' }, living: 'IN-NOI', source: 'legacy shortlist 2026-09-26', deadlineDays: 6, fit: 74 }),
    notes: 'Angle (unverified, from the old session): book-recommender pipeline + churn model.',
    letter: 'Historical letter imported from the legacy shortlist (mock text). Not re-sent; reapplying requires a fresh gated draft.',
  },
  {
    ...P({ key: 'legacy-tide', company: 'Tidewater AI', title: 'Machine Learning Intern', kind: 'internship', role_type: 'ml', city: 'Remote · Bengaluru', country: 'IN', lat: 12.95, lon: 77.7, work_mode: 'remote', channel: 'ats_form', pay: { status: 'listed', raw: 'INR 25,000 - 40,000/month', min: 25000, max: 40000, currency: 'INR', period: 'month' }, living: 'IN-HOME', source: 'legacy shortlist 2026-09-26', deadlineDays: 11, fit: 78 }),
    notes: 'Angle (unverified): YAML-configured pipeline; ask about Streamlit demo.',
    letter: 'Historical letter imported from the legacy shortlist (mock text).',
  },
  {
    ...P({ key: 'legacy-coast', company: 'Coastline Robotics', title: 'ML Intern — Autonomy', kind: 'internship', role_type: 'ml', city: 'Pittsburgh', country: 'US', lat: 40.44, lon: -79.99, work_mode: 'onsite', channel: 'ats_form', pay: { status: 'variable', raw: 'USD 13.25 - 27.50/hour (depending on experience)', min: 13.25, max: 27.5, currency: 'USD', period: 'hour' }, living: 'US-SEA', source: 'legacy shortlist 2026-09-26', deadlineDays: null, fit: 61 }),
    notes: 'Angle (unverified): perception coursework.',
    letter: 'Historical letter imported from the legacy shortlist (mock text).',
  },
  {
    ...P({ key: 'legacy-teep', company: 'National Chung Cheng University (CCU)', title: 'TEEP Research Intern — MARS Lab', kind: 'research_internship', role_type: 'research', city: 'Chiayi', country: 'TW', lat: 23.56, lon: 120.47, work_mode: 'onsite', channel: 'email', pay: { status: 'listed', raw: 'NT$15,000/month (minimum)', min: 15000, currency: 'TWD', period: 'month' }, living: 'TW-CYI', source: 'legacy shortlist 2026-09-26', deadlineDays: 34, fit: 75 }),
    notes: 'Re-verify: listed as NCCU in the old notes; it is CCU (MARS lab). TEEP minimum stipend NT$15,000/month.',
    letter: 'Historical letter imported from the legacy shortlist (mock text).',
  },
];

export const TITLE_VARIANTS = ['', ' (Summer 2027)', ' — Winter cohort', ' II', ' (6 months)'];

export const NOW_LINES: Record<string, string[]> = {
  'discover.ats': [
    'Polling Greenhouse boards (14 slugs)…',
    'Reading {company} careers page…',
    'Parsing job JSON → title, location, pay…',
    'Classifying title: "{title}"…',
    'Deduping against 212 known postings…',
  ],
  'verify.eligibility': [
    'Checking {company} link is live…',
    'Reading eligibility section for "{title}"…',
    'Extracting requirements with exact quotes…',
    'Converting {raw} → ₹/month…',
    'Comparing against living cost in {city}…',
    'Scam lexicon + known-mill check…',
    'Scoring fit (role 25 · skills 20 · pay 15 …)…',
  ],
  'draft.cover_letter': [
    'Selecting facts F-BOOK-*, F-CHURN-* for {company}…',
    'Quoting the job ad: 2 verified quotes…',
    'Drafting paragraph 1 of 3…',
    'Drafting paragraph 2 of 3…',
    'Emitting sentence-level citations…',
  ],
  'factcheck.sentence': [
    'Deterministic rules: NUM_NOT_IN_FACTS, BANNED_CLAIM…',
    'Checking WRONG_PROJECT attribution…',
    'Independent verifier: sentence 4/11…',
    'Independent verifier: sentence 9/11…',
    'Quality gate: specificity rubric, clichés…',
  ],
  'factcheck.signoff': [
    'Sign-off: reading letter + fact sheet…',
    'Sign-off: checking claims against citations…',
    'Sign-off: verdict + notes…',
  ],
  'build.resume': [
    'Selecting approved bullets for {company}…',
    'Rendering HTML → PDF (Chrome headless)…',
    'Checking PDF is exactly one page…',
  ],
  'apply.email_send': [
    'Pre-submit recheck: link, deadline, caps…',
    'Composing email with résumé attached…',
    'Writing to mock mailbox (dry run)…',
  ],
  'apply.manual_pack': [
    'Pre-submit recheck: link, deadline, caps…',
    'Building 2-minute pack: answers + files…',
    'Flagging fields that need you…',
  ],
  'inbox.poll': ['Polling mock inbox (history id 48213)…', 'Matching threads to applications…'],
  'inbox.classify': ['Classifying reply from {company}…', 'Checking notify-only lock terms…'],
  'followup.schedule': ['Scheduling one follow-up for {company} (day 10)…'],
  'strategy.daily_review': [
    'Reviewing 24h of pipeline outcomes…',
    'Ranking sources by verified yield…',
    'Drafting proposals (keywords, thresholds)…',
  ],
};
