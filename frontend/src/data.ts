export type Range = { low: string; high: string };
export type Mode = 'forecast' | 'assessment';
export type Organization = { id: string; name: string };
export type Workflow = { id: string; name: string; department: string; unit: string; benefit_pool: string; outcome_metrics: string[] };
export type Estimates = {
  months: string; implementation_usd: Range; period_benefit_usd: Range; period_operating_usd: Range;
  period_net_benefit_usd: Range; roi_ratio: Range | null;
  payback_months: { earliest: string | null; latest: string | null };
  cost_breakdown_usd?: Record<string, Range>; benefit_breakdown_usd?: Record<string, Range>;
  component_sensitivity_span_usd?: Record<string, string>;
};
export type Observed = {
  data_origin?: string; executions: number; units: number; reviewed_units: number; reworked_units: number;
  successful_executions: number; model_charge_usd: string; infrastructure_charge_usd: string;
  model_charge_runs: number; infrastructure_charge_runs: number; outcomes: Record<string, string>;
};
export type Analysis = {
  id: string; mode: Mode; created_at: string; deployment_id: string | null;
  snapshot: { baseline: { name: string; evidence: string }; measured: Observed | null;
    prior_estimates: Record<string, unknown> | null;
    assumptions: { evidence: string; months?: number; start?: string; end?: string };
    estimates: Estimates };
};
export type Detail = { workflow: Workflow; baselines: { id: string; name: string; evidence: string; assumptions?: { outcome_per_unit?: Record<string, Range> } }[];
  deployments: { id: string; name: string; adapter: string }[]; analyses: Analysis[] };
export type Report = { mode: Mode; window: Analysis['snapshot']['assumptions']; analysis_ids: string[]; estimates: Estimates; shared_items: unknown[] };
export type Api = <T>(path: string, options?: RequestInit) => Promise<T>;
export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
export function apiFor(key: string): Api {
  return async <T>(path: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers);
    if (key) headers.set('X-Workspace-Key', key);
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch('/portfolio' + path, { ...options, headers });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail;
      const validation = Array.isArray(detail) ? detail.map((item: {msg: string; loc: string[]}) =>
        item.loc.slice(1).map(String).map(human).join(' › ') + ' — ' + item.msg.replace(/^Value error, /, '')).join(' ') : '';
      throw new ApiError(response.status, response.status === 401 ? 'Enter a valid workspace key in Settings.' :
        typeof detail === 'string' ? detail : validation || 'AgentLedger returned an error (' + response.status + ').');
    }
    return data as T;
  };
}
export const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
export const errorText = (error: unknown) => error instanceof TypeError ? 'Could not reach AgentLedger. Check that the API is running and try again.'
  : error instanceof Error ? error.message : 'Something went wrong. Try again.';
export const human = (value: string) => value.replaceAll('_', ' ');
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
export const money = (value: number | string) => usd.format(Number(value));
export const num = (value: number | string) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
export const pct = (value: number | string) => num(Number(value) * 100) + '%';
export const formatRange = (range: Range | null, format = money) => range ? format(range.low) +
  (Number(range.low) === Number(range.high) ? '' : ' to ' + format(range.high)) : 'Unavailable';
export const date = (value: string) => new Date(value.endsWith('Z') || /[+-][0-9]{2}:[0-9]{2}$/.test(value) ? value : value + 'Z').toLocaleDateString(undefined, { dateStyle: 'medium', timeZone: 'UTC' });
export const modeName = (mode: Mode) => mode === 'forecast' ? 'Pre-adoption forecast' : 'Post-adoption assessment';
export const period = (item: Pick<Analysis, 'mode' | 'snapshot'>) => describeWindow(item.mode, item.snapshot.assumptions);
export function describeWindow(mode: Mode, window: Report['window']) {
  if (mode === 'forecast') return (window.months ?? '—') + '-month forecast';
  if (!window.start || !window.end) return 'Assessment period';
  const start = new Date(window.start), end = new Date(window.end);
  if (end.getTime() - start.getTime() < 86_400_000) {
    const dateTime = (value: Date) => value.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' });
    return dateTime(start) + ' – ' + dateTime(end) + ' UTC';
  }
  return date(window.start) + ' – ' + date(window.end) + ' UTC';
}
export const modeOrigin = (item: Analysis, org: Organization) => item.snapshot.measured?.data_origin === 'synthetic'
  ? 'Synthetic observations' : item.mode === 'assessment' ? 'Recorded observations + assumptions'
  : /\bsynthetic\b/i.test(org.name) && /\bsynthetic\b/i.test(item.snapshot.assumptions.evidence) ? 'Synthetic assumptions' : 'User assumptions';
export function favorability(range: Range) {
  if (Number(range.low) > 0) return ['Favorable across range', 'positive'] as const;
  if (Number(range.high) < 0) return ['Unfavorable across range', 'negative'] as const;
  if (Number(range.low) === 0 && Number(range.high) === 0) return ['Break-even', 'neutral'] as const;
  if (Number(range.low) === 0) return ['Break-even to favorable', 'neutral'] as const;
  if (Number(range.high) === 0) return ['Unfavorable to break-even', 'neutral'] as const;
  return ['Could gain or lose', 'neutral'] as const;
}
export function paybackText(value: Estimates['payback_months']) {
  if (value.earliest === null) return 'No payback estimated';
  if (value.latest === null) return 'From ' + num(value.earliest) + ' months';
  return formatRange({ low: value.earliest, high: value.latest }, num) + ' months';
}
export const latest = (detail: Detail, mode: Mode) => detail.analyses.find(item => item.mode === mode);
export const exact = (value: string | number): Range => ({ low: String(value), high: String(value) });
