import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import './portfolio.css';
import { AppSidebar } from './portfolio';

type Money = number | string;
type Outcome = 'passed' | 'review' | 'failed' | 'unclassified';
type Window = { start: string; end: string; limit: number; truncated: boolean };
type Execution = {
  run_id: string; model: string; provider: string; status: string; created_at: string;
  latency_ms: number; model_latency_ms: number | null; usage_reported: boolean;
  input_tokens: number; output_tokens: number; provider_charge_usd: Money | null;
  estimated_cost_usd: Money | null; validation_passed: boolean | null;
  requires_human_review: boolean | null; error_code: string | null;
  provider_request_id: string | null; pricing: Record<string, string> | null;
};
type Daily = { date: string } & Partial<Record<Outcome, number>>;
type Metrics = {
  attempts: number; processed: number; failed: number; review: number; passed: number;
  unclassified: number; observed_straight_through_rate: number | null;
  average_latency_ms: number | null; average_model_latency_ms: number | null;
  input_tokens: number; output_tokens: number; usage_reported_runs: number;
  provider_charge_runs: number; provider_charge_usd: Money; estimated_cost_runs: number;
  estimated_model_cost_usd: Money; unknown_model_cost_runs: number;
  covered_model_cost_usd: Money; model_cost_per_processed_usd: Money | null; daily: Daily[];
};
type Overview = { window: Window; metrics: Metrics; recent: Execution[] };
type Invoice = {
  filename: string; page_count: number; invoice: Record<string, string>;
  validation: { is_valid: boolean; discrepancies: string[]; requires_human_review: boolean };
  execution: Execution;
};
type Scenario = {
  label: string; manual_cost_usd: Money; review_cost_usd: Money; fallback_cost_usd: Money;
  model_cost_usd: Money; overhead_cost_usd: Money; operating_cost_usd: Money;
  operating_cost_per_processed_usd: Money | null; net_savings_usd: Money;
  roi_ratio: Money | null; human_minutes_saved: Money; human_effort_reduction_ratio: Money | null;
};
type Roi = {
  status: 'estimated' | 'missing_cost_assumption' | 'no_observations'; scenarios: Scenario[];
  window: Window; observed: Metrics; roi_ratio_range?: { low: Money; high: Money } | null;
};

const outcomes: Outcome[] = ['passed', 'review', 'failed', 'unclassified'];
const labels: Record<Outcome, string> = {
  passed: 'Validation passed', review: 'Review required', failed: 'Failed', unclassified: 'Unclassified',
};
const count = (value: number) => value.toLocaleString();
const usd = (value: Money | null | undefined) => {
  if (value == null) return '—';
  const n = Number(value);
  if (n !== 0 && Math.abs(n) < 0.000001) return '$' + n.toExponential(2);
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', maximumFractionDigits: Math.abs(n) < 1 ? 6 : 2,
  }).format(n);
};
const decimal = (value: Money) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const percent = (value: Money | null | undefined) =>
  value == null ? '—' : (Number(value) * 100).toLocaleString(undefined, { maximumFractionDigits: 1 }) + '%';
const time = (value: string) => new Date(value).toLocaleString(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
});
const duration = (value?: number | null) => value == null ? '—' : count(Math.round(value)) + ' ms';

async function api<T>(path: string, key: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (key) headers.set('X-Workspace-Key', key);
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) throw new Error('Enter a valid workspace key to access execution data.');
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const run = response.headers.get('X-Run-ID');
    const detail = typeof body?.detail === 'string' ? body.detail
      : Array.isArray(body?.detail) ? body.detail.map((issue: { msg: string }) => issue.msg).join(' ')
      : 'Request failed (' + response.status + ').';
    throw new Error(run ? detail + ' Run ID ' + run + '.' : detail);
  }
  return await response.json() as T;
}
const message = (error: unknown) => error instanceof Error ? error.message : 'An unexpected error occurred.';

function Panel({ id, title, sub, children }: { id?: string; title: string; sub?: string; children: ReactNode }) {
  return <section className="panel" id={id}>
    <div className="panel-heading"><h2>{title}</h2>{sub && <p>{sub}</p>}</div>
    {children}
  </section>;
}

function Trend({ metrics }: { metrics?: Metrics }) {
  const days = metrics?.daily ?? [];
  const max = Math.max(1, ...days.map(day => outcomes.reduce((sum, key) => sum + (day[key] ?? 0), 0)));
  return <Panel title="Execution activity" sub="Invoice attempts by outcome and UTC date">
    {days.length ? <>
      <div className="legend">{outcomes.map(key => <span key={key}><i className={key} />{labels[key]}</span>)}</div>
      <div className="chart" aria-label="Daily execution counts">
        {days.map(day => {
          const summary = day.date + ' · ' + outcomes.map(key => labels[key] + ' ' + (day[key] ?? 0)).join(' · ');
          return <div className="bar-column" tabIndex={0} key={day.date} title={summary} aria-label={summary}>
            <div className="bar-stack">{outcomes.map(key => day[key] ? <div key={key} className={key}
              style={{ height: (day[key]! / max * 100) + '%' }} /> : null)}</div>
            <time dateTime={day.date}>{day.date.slice(5)}</time>
          </div>;
        })}
      </div>
    </> : <div className="empty"><span className="empty-icon" aria-hidden="true">↗</span>
      <strong>No execution activity in this window</strong><span>Process a PDF to populate the activity chart.</span></div>}
  </Panel>;
}

function Runs({ runs }: { runs: Execution[] }) {
  const [active, setActive] = useState<string>();
  const selected = runs.find(run => run.run_id === active);
  return <Panel id="runs" title="Recent executions" sub="Up to 20 invoice attempts from the selected window">
    {runs.length ? <div className="table-scroll"><table>
      <thead><tr><th>Recorded</th><th>Extractor</th><th>Validation outcome</th><th>Latency</th><th>Model cost</th></tr></thead>
      <tbody>{runs.map(run => {
        const outcome = run.status === 'failure' ? 'failed' : run.requires_human_review ? 'review'
          : run.validation_passed ? 'passed' : 'unclassified';
        const cost = run.provider_charge_usd ?? run.estimated_cost_usd;
        return <tr key={run.run_id}>
          <td><button type="button" className="link" onClick={() => setActive(active === run.run_id ? undefined : run.run_id)}
            aria-expanded={active === run.run_id}>{time(run.created_at)}</button></td>
          <td><strong>{run.model}</strong><small>{run.provider}</small></td>
          <td><span className={'status ' + outcome}>{labels[outcome]}</span></td>
          <td>{duration(run.latency_ms)}</td>
          <td>{cost == null ? run.provider === 'rules' || run.model_latency_ms == null ? '$0.00' : 'Unknown' : usd(cost)}
            {cost != null && <small>{run.provider_charge_usd == null ? 'Estimated' : 'Provider reported'}</small>}</td>
        </tr>;
      })}</tbody>
    </table></div> : <div className="empty compact">Execution details will appear after the first invoice attempt.</div>}
    {selected && <dl className="detail-grid">
      <div><dt>Run ID</dt><dd>{selected.run_id}</dd></div>
      <div><dt>Provider request ID</dt><dd>{selected.provider_request_id ?? '—'}</dd></div>
      <div><dt>Model latency</dt><dd>{duration(selected.model_latency_ms)}</dd></div>
      <div><dt>Input / output tokens</dt><dd>{selected.usage_reported
        ? count(selected.input_tokens) + ' / ' + count(selected.output_tokens) : 'Usage unavailable'}</dd></div>
      <div><dt>Error code</dt><dd>{selected.error_code ?? '—'}</dd></div>
      <div><dt>Pricing evidence</dt><dd>{selected.pricing
        ? selected.pricing.source + ' · ' + usd(selected.pricing.input_per_million) + ' input / ' +
          usd(selected.pricing.output_per_million) + ' output per million tokens'
        : '—'}</dd></div>
    </dl>}
  </Panel>;
}

const assumptions = [
  ['manual_minutes', 'Manual handling', 'min / invoice'],
  ['review_minutes', 'Flagged invoice review', 'min / invoice'],
  ['hourly_labor_usd', 'Loaded labor rate', 'USD / hour'],
  ['overhead_usd_per_attempt', 'Operating overhead', 'USD / attempt'],
  ['unknown_model_cost_usd_per_attempt', 'Missing model cost', 'USD / uncovered attempt'],
] as const;

function RoiForm({ accessKey, days, revision }: { accessKey: string; days: number; revision: number }) {
  const [result, setResult] = useState<Roi>();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    setResult(undefined);
    setError('');
  }, [accessKey, days, revision]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setResult(undefined);
    const fields = new FormData(event.currentTarget);
    const body: Record<string, unknown> = { evidence_source: fields.get('evidence_source') };
    for (const [key] of assumptions) {
      const low = String(fields.get(key + '_low'));
      const high = String(fields.get(key + '_high'));
      if (!low && !high && key === 'unknown_model_cost_usd_per_attempt') continue;
      if (!low || !high || Number(low) > Number(high)) {
        setError('Provide both bounds with low less than or equal to high.');
        return;
      }
      body[key] = { low, high };
    }
    setPending(true);
    try {
      setResult(await api<Roi>('/analytics/roi?days=' + days, accessKey, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }));
    } catch (error) {
      setError(message(error));
    } finally {
      setPending(false);
    }
  }

  return <Panel id="roi" title="Counterfactual ROI" sub="Compare recorded automation with an evidence-backed manual workflow.">
    <form className="roi-form" onSubmit={submit}>
      <label>Evidence source<input name="evidence_source" required maxLength={500}
        placeholder="Reference to a time study, labor estimate, or overhead analysis" /></label>
      <div className="assumptions">
        {assumptions.map(([key, label, unit], index) => <fieldset key={key}>
          <legend>{label} <small>{unit}</small></legend>
          <div className="bounds">
            {['low', 'high'].map(bound => <label key={bound}>{bound === 'low' ? 'Low' : 'High'}
              <input type="number" name={key + '_' + bound} required={index < 4} min="0" max="1000000"
                step="any" aria-label={label + ' ' + bound + ' ' + unit} /></label>)}
          </div>
        </fieldset>)}
      </div>
      <div className="actions"><button className="primary" disabled={pending}>{pending ? 'Calculating…' : 'Estimate ROI'}</button>
        <small>Missing model cost bounds are required only when an attempt lacks pricing coverage.</small></div>
    </form>
    {error && <div className="notice warning" role="alert">{error}</div>}
    {result?.status === 'no_observations' && <div className="notice" role="status">Process an invoice in this window to estimate ROI.</div>}
    {result?.status === 'missing_cost_assumption' && <div className="notice warning" role="status">
      Supply missing model cost bounds for {count(result.observed.unknown_model_cost_runs)} uncovered attempts.
    </div>}
    {result?.status === 'estimated' && <>
      <div className="notice" role="status">
        Estimated ROI {result.roi_ratio_range ? percent(result.roi_ratio_range.low) + ' to ' + percent(result.roi_ratio_range.high) : 'unavailable'}.
        {' '}{count(result.observed.attempts)} recorded attempts through {time(result.window.end)}.
        {' '}Sensitivity bounds from supplied inputs. ROI is undefined where operating cost is zero.
      </div>
      <div className="scenarios">{result.scenarios.map(scenario => <article key={scenario.label}>
        <h3>{scenario.label}</h3><strong>{usd(scenario.net_savings_usd)}</strong><p>Estimated net savings</p>
        <dl>
          <div><dt>Manual baseline</dt><dd>{usd(scenario.manual_cost_usd)}</dd></div>
          <div><dt>Operating cost</dt><dd>{usd(scenario.operating_cost_usd)}</dd></div>
          <div><dt>Cost per processed invoice</dt><dd>{usd(scenario.operating_cost_per_processed_usd)}</dd></div>
          <div><dt>Model cost</dt><dd>{usd(scenario.model_cost_usd)}</dd></div>
          <div><dt>Human review</dt><dd>{usd(scenario.review_cost_usd)}</dd></div>
          <div><dt>Manual fallback</dt><dd>{usd(scenario.fallback_cost_usd)}</dd></div>
          <div><dt>Overhead</dt><dd>{usd(scenario.overhead_cost_usd)}</dd></div>
          <div><dt>Human effort reduction</dt><dd>{percent(scenario.human_effort_reduction_ratio)}</dd></div>
          <div><dt>Human minutes saved</dt><dd>{decimal(scenario.human_minutes_saved)}</dd></div>
        </dl>
      </article>)}</div>
    </>}
  </Panel>;
}

function Upload({ accessKey, onAttempt }: { accessKey: string; onAttempt: () => void }) {
  const [invoice, setInvoice] = useState<Invoice>();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setInvoice(undefined);
    setError('');
    const body = new FormData(event.currentTarget);
    setPending(true);
    try {
      setInvoice(await api<Invoice>('/invoices/process', accessKey, { method: 'POST', body }));
    } catch (error) {
      setError(message(error));
    } finally {
      setPending(false);
      onAttempt();
    }
  }
  return <Panel id="upload" title="Process an invoice" sub="Upload a text-based PDF up to 5 MB and 20 pages.">
    <form className="upload" onSubmit={submit}>
      <label className="file-label">Invoice PDF<input type="file" name="file" accept=".pdf,application/pdf" required /></label>
      <button className="primary" disabled={pending}>{pending ? 'Processing…' : 'Process PDF'}</button>
    </form>
    {error && <div className="notice warning" role="alert">{error}</div>}
    {invoice && <div className="invoice-result">
      <div className="invoice-summary">
        <strong>{invoice.filename}</strong>
        <span className={'status ' + (invoice.validation.is_valid ? 'passed' : 'review')}>
          {invoice.validation.is_valid ? labels.passed : labels.review}
        </span>
      </div>
      {invoice.validation.discrepancies.map(item => <div className="notice warning" key={item}>{item}</div>)}
      <dl className="detail-grid">{Object.entries(invoice.invoice).map(([key, value]) =>
        <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl>
    </div>}
  </Panel>;
}

export default function InvoiceTools() {
  const [days, setDays] = useState(30);
  const [accessKey, setAccessKey] = useState('');
  const [revision, setRevision] = useState(0);
  const [overview, setOverview] = useState<Overview>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const refresh = () => setRevision(value => value + 1);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setOverview(undefined);
    api<Overview>('/analytics/overview?days=' + days, accessKey, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setOverview(result); })
      .catch(error => { if (!controller.signal.aborted) setError(message(error)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [days, accessKey, revision]);

  const metrics = overview?.metrics;
  return <div className="app-shell invoice-tools">
    <AppSidebar activePage="workflows" prefix="/"/>
    <div className="workspace">
    <header className="topbar"><a className="subtle-link" href="/#workflows">? AI Workflows</a>
      <form className="key-form actions" onSubmit={event => {
        event.preventDefault();
        const target = event.currentTarget;
        setAccessKey(String(new FormData(target).get('key')).trim());
        target.reset();
      }}>
        <label>Workspace key<input type="password" name="key" autoComplete="off" placeholder={accessKey ? 'Key applied' : 'If required'}/></label>
        <button className="secondary">Apply key</button>
      </form>
    </header>
    <main className="stack" id="invoice-overview">
      <header className="page-head">
        <div><h1>Invoice processing</h1>
          <p>Track invoice outcomes, model spend, and estimated workflow economics.</p></div>
        <div className="filters"><label>Reporting window<select value={days} onChange={event => setDays(Number(event.target.value))}>
          <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </select></label><button className="secondary" onClick={refresh} disabled={loading}>Refresh</button></div>
      </header>
      {error && <div className="notice warning" role="alert">{error}</div>}
      {overview?.window.truncated && <div className="notice">Showing the latest {overview.window.limit.toLocaleString()} attempts in this window.</div>}
      {loading && <div className="notice" role="status">Loading executions…</div>}
      <div className="metrics">
        <article><h2>Invoice attempts</h2><strong>{metrics ? count(metrics.attempts) : '—'}</strong>
          <small>{metrics ? count(metrics.processed) + ' processed · ' + count(metrics.failed) + ' failed' : 'Observed runs'}</small></article>
        <article><h2>Straight-through rate</h2><strong>{percent(metrics?.observed_straight_through_rate)}</strong>
          <small>{metrics ? count(metrics.review) + ' flagged for review' : 'Validation passes per attempt'}</small></article>
        <article><h2>Covered model cost</h2><strong>{metrics?.attempts ? usd(metrics.covered_model_cost_usd) : '—'}</strong>
          <small>{metrics?.attempts ? count(metrics.unknown_model_cost_runs) + ' attempts with unknown cost' : 'USD'}</small></article>
        <article><h2>Average run latency</h2><strong>{duration(metrics?.average_latency_ms)}</strong>
          <small>Model request average {duration(metrics?.average_model_latency_ms)}</small></article>
      </div>
      <div className="analytics-grid">
        <Trend metrics={metrics} />
        <Panel title="Model cost & usage" sub="Recorded token usage and pricing coverage">
          <dl className="costs">
            <div><dt>Provider charges</dt><dd>{metrics?.provider_charge_runs ? usd(metrics.provider_charge_usd) : '—'}</dd></div>
            <div><dt>Priced estimates</dt><dd>{metrics?.estimated_cost_runs ? usd(metrics.estimated_model_cost_usd) : '—'}</dd></div>
            <div><dt>Model cost / processed</dt><dd>{usd(metrics?.model_cost_per_processed_usd)}</dd></div>
            <div><dt>Reported input / output</dt><dd>{metrics?.usage_reported_runs
              ? count(metrics.input_tokens) + ' / ' + count(metrics.output_tokens) : '—'}</dd></div>
            <div><dt>Attempts with usage</dt><dd>{metrics ? count(metrics.usage_reported_runs) + ' / ' + count(metrics.attempts) : '—'}</dd></div>
          </dl>
        </Panel>
      </div>
      <Runs runs={overview?.recent ?? []} />
      <Upload key={accessKey} accessKey={accessKey} onAttempt={refresh} />
      <RoiForm key={[accessKey, days, revision].join(':')} accessKey={accessKey} days={days} revision={revision} />
    </main>
    </div>
  </div>;
}
