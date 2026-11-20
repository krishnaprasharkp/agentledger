import type { ReactNode } from 'react';
import { favorability, formatRange, money, paybackText, pct } from './data';
import type { Estimates, Range } from './data';
import { DecisionNote, FinancialChart, drivers, financialLabel } from './finance';

const paths: Record<string, string> = {
  overview: 'M4 5h16v14H4zM8 15v-3m4 3V9m4 6v-5',
  workflows: 'M4 7h6l2 2h8v10H4zM7 13h10m-10 3h6',
  evaluate: 'M6 4h12v16H6zM9 8h6m-6 4h1m4 0h1m-6 4h1m4 0h1',
  reports: 'M6 4h8l4 4v12H6zM14 4v5h4M9 13h6m-6 3h6',
  settings: 'M5 7h14M5 12h14M5 17h14M9 5v4m6 1v4m-6 1v4',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  download: 'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4',
  refresh: 'M20 11a8 8 0 1 0-2 6m2-12v6h-6',
};
export function Icon({ name }: { name: string }) {
  return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.arrow} /></svg>;
}
export function PageHead({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <header className="page-head"><div><h1>{title}</h1><p>{description}</p></div>{action}</header>;
}
export function Panel({ title, description, action, children, className }: { title?: string; description?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={className ? `panel ${className}` : "panel"}>{title && <header className="panel-head"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</header>}{children}</section>;
}
export function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={'notice' + (error ? ' error' : '')} role={error ? 'alert' : 'status'}>{children}</div>;
}
export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty"><strong>{title}</strong><p>{children}</p></div>;
}
export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={'pill ' + tone}>{children}</span>;
}
export function Signal({ range }: { range: Range }) {
  const [label, tone] = favorability(range);
  const uncertain = Number(range.low) <= 0 && Number(range.high) >= 0 && Number(range.low) !== Number(range.high);
  return <Pill tone={uncertain ? 'uncertain' : tone}>{label}</Pill>;
}
export function Stat({ title, value, note, highlight = false }: {title: string; value: ReactNode; note: string; highlight?: boolean}) {
  return <article className={'stat' + (highlight ? ' highlight' : '')}><span className="stat-label">{title}</span><strong>{value}</strong><p>{note}</p></article>;
}
export function Breakdown({ items }: { items: Record<string, Range> }) {
  return <dl className="breakdown">{Object.entries(items).map(([key, value]) => <div key={key}>
    <dt>{financialLabel(key)}</dt><dd>{formatRange(value)}</dd>
  </div>)}</dl>;
}
export function Results({ estimates, period, source }: { estimates: Estimates; period: string; source: string }) {
  const range = estimates.period_net_benefit_usd;
  const {sensitivity} = drivers(estimates);
  const synthetic = /synthetic|hypothetical/i.test(source);
  return <>
    <div className="result-context"><Signal range={range}/><span>{period} · {source} · USD · Estimated results</span></div>
    <div className="stats compact result-metrics">
      <Stat title="Estimated net benefit" value={formatRange(range)} note="Benefits less operating and setup costs" highlight/>
      <Stat title="Estimated ROI" value={formatRange(estimates.roi_ratio, pct)} note="Net benefit as a share of total cost"/>
      <Stat title="Estimated payback" value={paybackText(estimates.payback_months)} note={
        estimates.payback_months.latest === null && estimates.payback_months.earliest !== null
          ? 'Some assumptions do not reach payback' : 'Assumes recurring rates stay steady'}/>
    </div>
    <DecisionNote estimates={estimates} synthetic={synthetic}/>
    <FinancialChart groups={[{name: 'Selected analysis', estimates}]} period={period} source={source}/>
    <div className="result-totals">
      <span><b>{formatRange(estimates.period_operating_usd)}</b> Operating costs</span>
      <span><b>{formatRange(estimates.period_benefit_usd)}</b> Modeled benefits</span>
      <span><b>{formatRange(estimates.implementation_usd)}</b> One-time setup</span>
    </div>
    {estimates.cost_breakdown_usd && <details><summary>Cost and benefit breakdown</summary><div className="split">
      <div><h3>Operating costs</h3><Breakdown items={estimates.cost_breakdown_usd}/></div>
      <div><h3>Modeled benefits</h3><Breakdown items={estimates.benefit_breakdown_usd ?? {}}/></div>
    </div></details>}
    <details><summary>How the estimate is calculated</summary>
      <ul className="calculation-list">
        <li>Manual effort value = manual cost per work unit × work volume. Manual cost can come from handling minutes ÷ 60 × hourly labor cost.</li>
        <li>Modeled benefits = manual effort value plus any separately valued business outcomes.</li>
        <li>Operating cost = model and infrastructure usage, subscriptions, maintenance, human review, and rework that apply.</li>
        <li>Net benefit = modeled benefits minus operating and one-time implementation costs. ROI is net benefit divided by total cost when defined.</li>
        <li>Payback estimates how long recurring net benefit takes to cover implementation, assuming steady rates.</li>
      </ul>
    </details>
    {estimates.component_sensitivity_span_usd && <details><summary>What drives uncertainty?</summary>
      <p>These are sensitivity ranges. Each amount is the difference between a component’s low and high estimate. A wide range shows where to check your assumptions first. Inputs such as work volume can affect several components at once.</p>
      {sensitivity.length ? <dl className="breakdown">{sensitivity.map(([key,value]) =>
        <div key={key}><dt>{financialLabel(key)}</dt><dd>{money(value)}</dd></div>)}</dl> :
        <p>The supplied inputs produce fixed values for these components.</p>}
    </details>}
  </>;
}
