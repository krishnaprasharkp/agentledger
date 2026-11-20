import './finance.css';
import { useId, useState } from 'react';
import { formatRange, human, money } from './data';
import type { Estimates, Range } from './data';

export const financialLabels: Record<string, string> = {
  fixed_model: 'Model subscriptions', fixed_infrastructure: 'Fixed hosting and infrastructure', maintenance: 'Maintenance',
  variable_model: 'Model usage', variable_infrastructure: 'Infrastructure usage', review: 'Human review', rework: 'Corrections and rework',
  counterfactual_manual_cost: 'Modeled value of manual effort', implementation: 'One-time implementation',
};
export const financialLabel = (key: string) => financialLabels[key] ?? human(key);
const inputDrivers: Record<string, string> = {
  counterfactual_manual_cost: 'manual handling time, hourly labor cost, and work volume',
  variable_model: 'model cost per unit, work volume, and any missing model-cost assumptions',
  variable_infrastructure: 'infrastructure cost per unit, work volume, and any missing infrastructure-cost assumptions',
  review: 'the amount of work reviewed and the cost of each review',
  rework: 'the amount of work corrected and the cost of each correction',
  maintenance: 'monthly maintenance cost',
  fixed_model: 'monthly subscription cost',
  fixed_infrastructure: 'monthly fixed infrastructure cost',
  implementation: 'upfront setup, testing, and training costs',
};

export function decision(range: Range) {
  const low = Number(range.low), high = Number(range.high);
  if (low > 0) return 'Modeled benefits exceed operating and setup costs throughout the range.';
  if (high < 0) return 'Operating and setup costs exceed modeled benefits throughout the range.';
  if (low === 0 && high === 0) return 'Modeled benefits equal total costs under these inputs.';
  if (low === 0) return 'These assumptions range from breaking even to a modeled gain.';
  if (high === 0) return 'These assumptions range from a modeled loss to breaking even.';
  return 'The range crosses break-even. The workflow could produce a modeled gain or loss depending on the assumptions.';
}
function largest(items: Record<string, Range>) {
  const magnitude = (range: Range) => Math.max(Math.abs(Number(range.low)), Math.abs(Number(range.high)));
  return Object.entries(items).filter(([, range]) => magnitude(range) > 0)
    .sort((a, b) => magnitude(b[1]) - magnitude(a[1]))[0];
}
export function drivers(estimate: Estimates) {
  return {
    cost: estimate.cost_breakdown_usd && largest({...estimate.cost_breakdown_usd, implementation: estimate.implementation_usd}),
    benefit: estimate.benefit_breakdown_usd && largest(estimate.benefit_breakdown_usd),
    sensitivity: Object.entries(estimate.component_sensitivity_span_usd ?? {})
      .filter(([, span]) => Number(span) > 0).sort((a, b) => Number(b[1]) - Number(a[1])),
  };
}
export function DecisionNote({ estimates, synthetic }: {
  estimates: Estimates; synthetic: boolean;
}) {
  const {cost, benefit, sensitivity} = drivers(estimates);
  const widest = sensitivity[0];
  return <div className="decision-note">
    <p>{decision(estimates.period_net_benefit_usd)}{synthetic && ' These hypothetical figures do not represent company savings.'}</p>
    {(cost || benefit) && <p>{cost && <>Largest cost: <b>{financialLabel(cost[0])}</b> ({formatRange(cost[1])}). </>}
      {benefit && <>Largest modeled benefit: <b>{financialLabel(benefit[0])}</b> ({formatRange(benefit[1])}).</>}</p>}
    <p>{widest && <>The widest component range is <b>{financialLabel(widest[0])}</b> ({money(widest[1])} between its bounds). Check {inputDrivers[widest[0]] ?? 'how this outcome was measured and valued'} first. </>}
      Use the estimate alongside evidence about service quality, implementation risk, and how much staff capacity could be put to other use.</p>
  </div>;
}

const axisMoney = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
});

const series = [
  ['period_operating_usd', 'Operating costs', 'operating'],
  ['period_benefit_usd', 'Modeled benefits', 'benefits'],
  ['period_net_benefit_usd', 'Estimated net benefit', 'net'],
] as const;

export function rangeAxis(ranges: Range[]) {
  const points = ranges.flatMap(range => [Number(range.low), Number(range.high)]);
  const low = Math.min(0, ...points);
  const high = Math.max(0, ...points);
  return {low, high, position: (point: number) => high === low ? 50 : (point - low) / (high - low) * 100};
}

export function FinancialChart({ groups, period, source }: {
  groups: {name: string; estimates: Estimates}[];
  period: string;
  source: string;
}) {
  const id = useId();
  const [active, setActive] = useState<string>();
  const [dismissed, setDismissed] = useState<string>();
  const axis = rangeAxis(groups.flatMap(group => series.map(([key]) => group.estimates[key])));
  const zeroPosition = axis.position(0);
  const showZeroLabel = axis.low === 0 || axis.high === 0 || (zeroPosition > 22 && zeroPosition < 78);
  return <figure className="financial-chart" aria-labelledby={id + '-caption'}>
    <figcaption><strong id={id + '-caption'}>{groups.length > 1 ? 'Financial ranges by workflow' : 'Financial ranges' + (groups[0].name === 'Selected analysis' ? '' : ' | ' + groups[0].name)}</strong>
      <small>{period} · USD · {source} · Estimated finances</small></figcaption>
    <p className="hint">Lines show sensitivity ranges. Dots show single values. The vertical rule marks zero.</p>
    <div className="financial-scale" aria-hidden="true"><div className="financial-axis">
      {axis.low !== 0 && <span className="axis-low">{axisMoney.format(axis.low)}</span>}
      {showZeroLabel && <span className={axis.low === 0 && axis.high !== 0 ? 'axis-low' : axis.high === 0 && axis.low !== 0 ? 'axis-high' : 'axis-center'}
        style={{left: zeroPosition + '%'}}>{axisMoney.format(0)}</span>}
      {axis.high !== 0 && <span className="axis-high">{axisMoney.format(axis.high)}</span>}
    </div></div>
    {groups.map((group, groupIndex) => <div className="financial-group" key={group.name}>
      {groups.length > 1 && <h3>{group.name}</h3>}
      {series.map(([key, label, tone]) => {
        const value = group.estimates[key], low = axis.position(Number(value.low)), high = axis.position(Number(value.high));
        const rangeId = id + '-' + groupIndex + '-' + key;
        return <div className="financial-row" key={key}>
          <span>{label}</span>
          <button className={'financial-track ' + tone + (dismissed === rangeId ? ' tooltip-dismissed' : '')} type="button" aria-label={group.name + ' · ' + label + ' · ' + formatRange(value)}
            aria-describedby={rangeId}
            onClick={() => {
              setDismissed(undefined);
              setActive(previous => previous === rangeId ? undefined : rangeId);
            }}
            onPointerEnter={() => setDismissed(previous => previous === rangeId ? undefined : previous)}
            onBlur={() => { setActive(undefined); setDismissed(undefined); }}
            onKeyDown={event => {
              if (event.key === 'Escape') {
                setActive(undefined);
                setDismissed(rangeId);
              }
            }}>
            <i className="financial-zero" style={{left: axis.position(0) + '%'}}/>
            <i className={'financial-interval' + (low === high ? ' point' : '')} style={{left: low + '%', width: (high - low) + '%'}}/>
            <span className={'financial-tooltip' + (active === rangeId ? ' open' : '')} role="tooltip" id={rangeId}>
              {group.name} · {label} · {formatRange(value)} · {period} · {source}
            </span>
          </button>
          <strong>{formatRange(value)}</strong>
        </div>;
      })}
    </div>)}
  </figure>;
}
