import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Empty, Notice, PageHead, Panel, Results } from './components';
import { errorText, exact, formatRange, human, num, modeName, modeOrigin, period, post } from './data';
import type { Analysis, Api, Detail, Estimates, Mode, Organization, Range } from './data';

type Fields = Record<string, FormDataEntryValue>;
const ExampleValues = createContext<Record<string, string>>({});
const supportExample: Record<string, string> = {
  baseline_name: 'Manual first-line support',
  evidence: 'Hypothetical support team handling common account and product questions. All inputs are illustrative.',
  months: '12', minutes: '6', minutes_high: '8', labor: '30', labor_high: '36',
  units: '900', units_high: '1200', model: '0.14', model_high: '0.23',
  review_pct: '25', review_pct_high: '40', review: '1.5', review_high: '2.1',
  setup: '8000', setup_high: '12000', fixed_infra: '80', fixed_infra_high: '120',
  maintenance: '250', maintenance_high: '400', infra: '0.04', infra_high: '0.08',
  rework: '3', rework_high: '5', rework_pct: '5', rework_pct_high: '10',
};
const exampleWorkflow: Detail = {
  workflow: {id: '', name: 'Customer support automation', department: 'Customer support', unit: 'ticket', benefit_pool: '', outcome_metrics: []},
  baselines: [], deployments: [], analyses: [],
};
const value = (fields: Fields, name: string) => String(fields[name] ?? '').trim();
export function readRange(fields: Fields, name: string, label: string, max = 1_000_000, optional = false): Range {
  const raw = value(fields, name), high = value(fields, name + '_high');
  if (!raw && !high && optional) return exact(0);
  if (!raw || !Number.isFinite(Number(raw)) || (high && !Number.isFinite(Number(high)))) throw new Error('Enter a number for ' + label + '.');
  if (Number(raw) < 0 || (high && Number(high) < Number(raw)) || Number(high || raw) > max)
    throw new Error(label + ' must be between 0 and ' + max.toLocaleString() + ', with the upper value at least as large.');
  return {low: raw, high: high || raw};
}
const scaled = (range: Range, scale: number): Range => ({
  low: String(Number((Number(range.low) * scale).toFixed(8))), high: String(Number((Number(range.high) * scale).toFixed(8))),
});
function Rate({ name, label, unit, help }: { name: string; label: string; unit: string; help?: string }) {
  const defaults = useContext(ExampleValues);
  return <div className="rate"><div><strong>{label}</strong>{help && <small>{help}</small>}</div><div className="rate-fields">
    <label><span>{unit}</span><input name={name} defaultValue={defaults[name]} type="number" min="0" step="any" aria-label={label + ' (' + unit + ')'}/></label>
    <label><span>Upper value · optional</span><input name={name + '_high'} defaultValue={defaults[name + '_high']} type="number" min="0" step="any" aria-label={label + ' upper value'}/></label>
  </div></div>;
}
function share(fields: Fields, name: string, label: string, optional = false) {
  return scaled(readRange(fields, name, label, 100, optional), .01);
}
function getContext(detail: Detail, mode: Mode, fields: Fields, newBaseline: boolean) {
  const evidence = value(fields, 'evidence');
  if (!evidence) throw new Error('Describe the source of your estimates or records.');
  if (newBaseline) {
    if (!value(fields, 'baseline_name')) throw new Error('Name your manual baseline.');
    const minutes = readRange(fields, 'minutes', 'manual processing time');
    const labor = readRange(fields, 'labor', 'hourly labor cost');
    const combined = {
      low: String(Number((Number(minutes.low) * Number(labor.low) / 60).toFixed(8))),
      high: String(Number((Number(minutes.high) * Number(labor.high) / 60).toFixed(8))),
    };
    if (Number(combined.high) > 1_000_000) throw new Error('Manual labor cost per unit exceeds the supported range.');
    return { evidence, baseline: {name: value(fields, 'baseline_name'), evidence, manual_cost_usd_per_unit: combined } };
  }
  if (!detail.baselines.some(item => item.id === value(fields, 'baseline'))) throw new Error('Choose a saved baseline.');
  return { evidence, baseline: undefined };
}
function observation(fields: Fields, mode: Mode) {
  if (mode === 'forecast') {
    const months = Number(value(fields, 'months'));
    if (!Number.isInteger(months) || months < 1 || months > 120) throw new Error('Enter a whole forecast horizon from 1 to 120 months.');
    return { months, units_monthly: readRange(fields, 'units', 'monthly workload') };
  }
  const start = new Date(value(fields, 'start')), end = new Date(value(fields, 'end'));
  if (!value(fields, 'deployment')) throw new Error('Choose a deployment to assess.');
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end || end > new Date())
    throw new Error('Enter a valid past observation window with the end after the start.');
  return { deployment_id: value(fields, 'deployment'), start: start.toISOString(), end: end.toISOString() };
}
function optionalRange(fields: Fields, name: string, label: string) {
  return value(fields, name) || value(fields, name + '_high') ? readRange(fields, name, label) : undefined;
}
function costInputs(fields: Fields, mode: Mode) {
  return {
    implementation_usd: readRange(fields, 'setup', 'implementation cost'),
    review_usd_per_unit: readRange(fields, 'review', 'cost per reviewed unit'),
    fixed_model_usd_monthly: readRange(fields, 'fixed_model', 'monthly model subscription', undefined, true),
    fixed_infrastructure_usd_monthly: readRange(fields, 'fixed_infra', 'monthly fixed infrastructure', undefined, true),
    maintenance_usd_monthly: readRange(fields, 'maintenance', 'monthly maintenance', undefined, true),
    rework_usd_per_unit: readRange(fields, 'rework', 'rework cost per unit', undefined, true),
    ...(mode === 'forecast' ? {
      model_usd_per_unit: readRange(fields, 'model', 'model cost per unit'),
      infrastructure_usd_per_unit: readRange(fields, 'infra', 'infrastructure usage per unit', undefined, true),
      review_fraction: share(fields, 'review_pct', 'work sent for review'),
      rework_fraction: share(fields, 'rework_pct', 'work needing correction', true),
    } : {
      missing_model_usd_per_execution: optionalRange(fields, 'missing_model', 'missing model usage cost'),
      missing_infrastructure_usd_per_execution: optionalRange(fields, 'missing_infra', 'missing infrastructure usage cost'),
    }),
  };
}
function extras(fields: Fields, detail: Detail, mode: Mode, newBaseline: boolean) {
  const outcome_per_unit: Record<string, Range> = {};
  const expected_outcomes_per_unit: Record<string, Range> = {};
  const outcome_valuation: Record<string, {direction: number; usd_per_metric_unit: Range}> = {};
  for (const metric of detail.workflow.outcome_metrics) {
    const direction = value(fields, metric + '_direction');
    if (!direction) continue;
    const label = human(metric);
    if (newBaseline) outcome_per_unit[metric] = readRange(fields, metric + '_baseline', label + ' baseline');
    if (mode === 'forecast') expected_outcomes_per_unit[metric] = readRange(fields, metric + '_expected', 'expected ' + label);
    outcome_valuation[metric] = { direction: Number(direction), usd_per_metric_unit: readRange(fields, metric + '_value', label + ' value') };
  }
  return { outcome_per_unit, ...mode === 'forecast' && { expected_outcomes_per_unit }, outcome_valuation };
}
function Wizard({ detail, mode, api, org, onSaved, example = false }: {
  detail: Detail; mode: Mode; api: Api; org?: Organization; onSaved: () => void; example?: boolean;
}) {
  const defaults = example ? supportExample : {};
  const [step, setStep] = useState(0), [newBaseline, setNewBaseline] = useState(!detail.baselines.length || mode === 'forecast');
  const [review, setReview] = useState<Fields>({});
  const [pending, setPending] = useState(false), [error, setError] = useState(''), [result, setResult] = useState<Analysis>();
  const [preview, setPreview] = useState<{ estimates: Estimates; months: string }>();
  const created = useRef<{ key: string; id: string } | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    form.current?.querySelector<HTMLElement>('fieldset:not([hidden]) > legend')?.focus();
  }, [step]);
  const steps = ['Manual baseline', 'Workload and AI costs', example ? 'Review and calculate' : 'Review and save'];
  function fields() { return Object.fromEntries(new FormData(form.current!)); }
  function checkNext() {
    setError('');
    try {
      const current = fields();
      if (step === 0) getContext(detail, mode, current, newBaseline);
      if (step === 1) { observation(current, mode); costInputs(current, mode); extras(current, detail, mode, newBaseline); setReview(current); }
      setStep(step + 1);
    } catch (problem) { setError(errorText(problem)); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step < 2) { checkNext(); return; }
    setError(''); setPending(true); setResult(undefined); setPreview(undefined);
    try {
      const current = fields(), context = getContext(detail, mode, current, newBaseline);
      const {outcome_per_unit, ...advanced} = extras(current, detail, mode, newBaseline);
      const payload = {...observation(current, mode), ...costInputs(current, mode), ...advanced, evidence: context.evidence};
      if (example && context.baseline) {
        const {estimates} = await api<{estimates: Estimates}>('/forecasts/preview', post({
          ...payload, baseline: {...context.baseline, outcome_per_unit},
        }));
        setPreview({estimates, months: value(current, 'months')});
        return;
      }
      const path = '/workflows/' + detail.workflow.id;
      let baseline_id = value(current, 'baseline');
      if (context.baseline) {
        const baseline = {...context.baseline, outcome_per_unit}, key = JSON.stringify(baseline);
        if (created.current?.key !== key) {
          const record = await api<{id: string}>(path + '/baselines', post(baseline));
          created.current = {key, id: record.id};
        }
        baseline_id = created.current.id;
      }
      setResult(await api<Analysis>(path + (mode === 'forecast' ? '/forecasts' : '/assessments'), post({...payload, baseline_id})));
      onSaved();
    } catch (problem) {
      setError(errorText(problem) + (created.current ? ' The manual baseline was saved and will be reused when you retry these inputs.' : ''));
    } finally { setPending(false); }
  }

  const advanced = (children: ReactNode) => <details><summary>Additional costs and business outcomes</summary>{children}</details>;
  return <ExampleValues.Provider value={defaults}><div className="stack">
    <Panel className="evaluation-panel" title="Your evaluation" description={(example ? "Hypothetical customer-support forecast" : modeName(mode)) + ' · All costs in USD'}>
      <div className="wizard-body"><ol className="steps">{steps.map((name, index) => <li key={name} aria-current={step === index ? 'step' : undefined}
        className={step >= index ? 'current' : ''}><span>{index + 1}</span>{name}</li>)}</ol>
      <form ref={form} className="form" aria-busy={pending} noValidate onChange={() => {setResult(undefined); setPreview(undefined);}} onSubmit={submit}>
        <fieldset hidden={step !== 0} disabled={pending}>
          <legend tabIndex={-1}>How does the work happen today?</legend>
          {detail.baselines.length > 0 && <label>Baseline source<select value={newBaseline ? 'new' : 'saved'} onChange={event => setNewBaseline(event.target.value === 'new')}>
            <option value="new">Enter manual processing time and labor cost</option><option value="saved">Use a saved baseline</option></select></label>}
          {newBaseline ? <>
            <label>Baseline name<input name="baseline_name" defaultValue={defaults.baseline_name} maxLength={160} placeholder="Manual process today"/></label>
            <Rate name="minutes" label="Manual processing time" unit={'Minutes per ' + detail.workflow.unit} help="Average hands-on time a person spends on one unit today."/>
            <Rate name="labor" label="Hourly labor cost" unit="USD per hour" help="Use an hourly rate that includes payroll overhead where applicable."/>
          </> : <label>Saved baseline<select name="baseline">{detail.baselines.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
          <label>Evidence and assumptions<textarea name="evidence" defaultValue={defaults.evidence} rows={2} maxLength={500} placeholder="For example, a time study, staffing estimate, or provider quote"/></label>
        </fieldset>
        <fieldset hidden={step !== 1} disabled={pending}>
          <legend tabIndex={-1}>{mode === 'forecast' ? 'What will AI cost to run?' : 'Which deployment period should be assessed?'}</legend>
          <p className="hint">Enter one value for a fixed estimate, or add an upper value to test a range.</p>
          {mode === 'forecast' ? <>
            <label>Forecast horizon (months)<input name="months" type="number" min="1" max="120" defaultValue={defaults.months ?? '12'}/></label>
            <Rate name="units" label="Monthly workload" unit={detail.workflow.unit + ' units per month'} help="Count only the work this project would handle."/>
            <Rate name="model" label="Model cost" unit="USD per unit" help="What the AI provider charges to handle one unit of work."/>
            <Rate name="review_pct" label="Work sent for review" unit="% of units" help="Out of every 100 items handled by AI, how many need a human check?"/>
          </> : <>
            <label>Deployment<select name="deployment">{detail.deployments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <div className="split"><label>Window start (local time)<input name="start" type="datetime-local"/></label>
              <label>Window end (local time)<input name="end" type="datetime-local"/></label></div>
            <p className="hint">Uses recorded workload, review, rework, and available usage costs during this window.</p>
          </>}
          <Rate name="setup" label="One-time implementation cost" unit="USD" help="Upfront spending for setup, integration, testing, and training."/>
          <Rate name="review" label="Cost per reviewed unit" unit="USD per reviewed unit" help="What it costs a person to check one item."/>
          {advanced(<>
            <p className="hint">Blank recurring and rework inputs are treated as zero. Enter costs that apply.</p>
            <Rate name="fixed_model" label="Model subscription" unit="USD per month"/>
            <Rate name="fixed_infra" label="Fixed infrastructure" unit="USD per month"/>
            <Rate name="maintenance" label="Maintenance" unit="USD per month"/>
            <Rate name="rework" label="Cost of correcting work" unit="USD per reworked unit"/>
            {mode === 'forecast' ? <><Rate name="infra" label="Infrastructure usage" unit="USD per unit"/>
              <Rate name="rework_pct" label="Work needing correction" unit="% of units"/></> :
              <><p className="hint">Enter bounds if the deployment is missing usage charges. Enter an explicit zero only when supported by your evidence.</p>
                <Rate name="missing_model" label="Missing model cost" unit="USD per execution"/>
                <Rate name="missing_infra" label="Missing infrastructure cost" unit="USD per execution"/></>}
            {detail.workflow.outcome_metrics.map(metric => <details key={metric}><summary>Value {human(metric)}</summary>
              <p className="hint">Include a financial impact only if its value is distinct from the labor benefit.</p>
              <label>Financial impact direction<select name={metric + '_direction'}><option value="">Do not monetize</option>
                <option value="1">Higher is better</option><option value="-1">Lower is better</option></select></label>
              {newBaseline && <Rate name={metric + '_baseline'} label={'Manual ' + human(metric)} unit="Outcome units per work unit"/>}
              {mode === 'forecast' && <Rate name={metric + '_expected'} label={'Expected ' + human(metric)} unit="Outcome units per work unit"/>}
              <Rate name={metric + '_value'} label={'Financial value of ' + human(metric)} unit="USD per outcome unit"/>
            </details>)}
          </>)}
        </fieldset>
        <fieldset hidden={step !== 2} disabled={pending}>
          <legend tabIndex={-1}>Review your inputs</legend>
          <p>{mode === 'forecast' ? 'This forecast estimates a future investment from your assumptions.' :
            'This assessment compares recorded deployment activity with a manual baseline and your cost assumptions.'}</p>
          <p>Operating cost includes ongoing AI and human work. Net benefit subtracts operating and one-time setup costs from modeled benefits.</p>
          {step === 2 && <dl className="breakdown">
            <div><dt>Manual baseline</dt><dd>{newBaseline ? value(review, 'baseline_name') : detail.baselines.find(item => item.id === value(review, 'baseline'))?.name}</dd></div>
            {mode === 'forecast' ? <>
              <div><dt>Evaluation horizon</dt><dd>{value(review, 'months')} months</dd></div>
              <div><dt>Workload per month</dt><dd>{formatRange(readRange(review, 'units', 'monthly workload'), num)}</dd></div>
              <div><dt>Work sent for review</dt><dd>{formatRange(readRange(review, 'review_pct', 'review share'), item => num(item) + '%')}</dd></div>
            </> : <div><dt>Deployment</dt><dd>{detail.deployments.find(item => item.id === value(review, 'deployment'))?.name}</dd></div>}
            <div><dt>One-time implementation cost</dt><dd>{formatRange(readRange(review, 'setup', 'implementation cost'))}</dd></div>
            <div><dt>Cost per reviewed unit</dt><dd>{formatRange(readRange(review, 'review', 'review cost'))}</dd></div>
          </dl>}
          <p className="hint">{example ? 'This calculation leaves your workspace records untouched. Go back to try different inputs.' : 'Saving adds an analysis to the workflow history. Go back to adjust any input.'}</p>
        </fieldset>
        {error && <Notice error>{error}</Notice>}
        <div className="actions">
          {step > 0 && <button type="button" className="secondary" disabled={pending} onClick={() => {setError(''); setStep(step - 1);}}>Back</button>}
          <button className="primary" type="submit" disabled={pending || (result !== undefined && step === 2)}>{pending ? (example ? 'Calculating' : 'Saving') : step === 2 ? example ? 'Calculate example' : result ? 'Analysis saved' : 'Calculate and save' : 'Continue'}</button>
        </div>
      </form></div>
    </Panel>
    {result && org && <Panel title="Evaluation result" className="report-output"><Notice>Analysis saved to this workflow.</Notice><Results estimates={result.snapshot.estimates} period={period(result)} source={modeOrigin(result, org)}/>
      <a className="button secondary" href={'#workflows/' + detail.workflow.id}>View workflow</a></Panel>}
    {preview && <Panel title="Hypothetical customer-support result" className="report-output">
      <Results estimates={preview.estimates} period={preview.months + '-month forecast'} source="Hypothetical example assumptions"/>
    </Panel>}
  </div></ExampleValues.Provider>;
}

export function Evaluator({ details, api, org, onSaved, initialWorkflow, publicDemo = false }: {publicDemo?: boolean; details: Detail[]; api: Api; org?: Organization; onSaved: () => void; initialWorkflow?: string}) {
  const [example, setExample] = useState(publicDemo);
  const [workflow, setWorkflow] = useState(initialWorkflow ?? ''), [mode, setMode] = useState<Mode>('forecast');
  const detail = details.find(item => item.workflow.id === workflow) ?? details[0];
  return <div className="stack">
    <PageHead title="Evaluate AI" description="Forecast an investment or assess a deployment using recorded activity."
      action={!example && <button className="secondary" onClick={() => setExample(true)}>Try an example</button>}/>
    {example && <>
      <Panel title="Customer support automation" description="A hypothetical support team uses AI to help handle routine questions. Change an assumption and recalculate to see how it affects the result.">
        <p className="hint">Open Additional costs and business outcomes to see the example's infrastructure, maintenance, and correction costs.</p>
        {!publicDemo && <button className="secondary" onClick={() => setExample(false)}>Exit example</button>}
      </Panel>
      <Wizard key="support-example" detail={exampleWorkflow} mode="forecast" api={api} onSaved={onSaved} example/>
    </>}
    {!publicDemo && <div className="stack" hidden={example}>
    {detail ? <>
      <Panel><div className="split">
        <label>Workflow<select value={detail.workflow.id} onChange={event => setWorkflow(event.target.value)}>{details.map(item =>
          <option key={item.workflow.id} value={item.workflow.id}>{item.workflow.name}</option>)}</select></label>
        <label>Evaluation type<select value={mode} onChange={event => setMode(event.target.value as Mode)}>
          <option value="forecast">Pre-adoption forecast</option><option value="assessment">Post-adoption assessment</option>
        </select></label>
      </div></Panel>
      {mode === 'assessment' && !detail.deployments.length ? <Panel><Empty title="A deployment is needed">Register a deployment on the workflow page to assess recorded activity.</Empty>
        <a className="button secondary" href={'#workflows/' + detail.workflow.id}>Open workflow</a></Panel>
        : <Wizard key={detail.workflow.id + mode} detail={detail} mode={mode} org={org} api={api} onSaved={onSaved}/>}
    </> : <Panel><Empty title="Create a workflow to get started">An evaluation is saved to a workflow, such as invoice processing or service desk triage.</Empty>
      <a className="button secondary" href="#workflows">Go to AI Workflows</a></Panel>}
    </div>}
  </div>;
}
