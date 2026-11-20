import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Empty, Icon, Notice, PageHead, Panel, Results, Signal, Stat } from './components';
import { date, describeWindow, errorText, formatRange, human, latest, modeName, modeOrigin, money, num, paybackText, pct, period, post } from './data';
import type { Analysis, Api, Detail, Mode, Organization, Report, Workflow } from './data';
import { readRange } from './evaluator';
import { decision, FinancialChart } from './finance';
import { AppWindow } from './appWindow';

export type PortfolioReport = { result: Report; origin: string };
type PageProps = { org: Organization; details: Detail[] };
const flowLink = (detail: Detail) => '#workflows/' + detail.workflow.id;
const evaluationLink = (detail: Detail) => '#evaluate/' + detail.workflow.id;
const modes = [['assessment', 'Post-adoption'], ['forecast', 'Pre-adoption']] as const;

export function Overview({ org, details, report, readOnly = false }: PageProps & { report?: PortfolioReport; readOnly?: boolean }) {
  const [mode, setMode] = useState<Mode>(details.some(item => latest(item, 'assessment')) ? 'assessment' : 'forecast');
  const [focus, setFocus] = useState('');
  const selectedReport = report?.result.mode === mode ? report : undefined;
  const rows = details.map(detail => ({ detail, analysis: latest(detail, mode) }));
  const selected = rows.find(row => row.detail.workflow.id === focus && row.analysis) ?? rows.find(row => row.analysis);
  const analysis = selected?.analysis;
  const comparable = rows.filter(row => row.analysis && analysis &&
    (mode === 'forecast' ? row.analysis.snapshot.assumptions.months === analysis.snapshot.assumptions.months :
      row.analysis.snapshot.assumptions.start === analysis.snapshot.assumptions.start &&
      row.analysis.snapshot.assumptions.end === analysis.snapshot.assumptions.end) &&
    modeOrigin(row.analysis, org) === modeOrigin(analysis, org));
  const e = selectedReport?.result.estimates ?? analysis?.snapshot.estimates;
  const scope = selectedReport ? selectedReport.result.analysis_ids.length + ' workflows in calculated report' : selected?.detail.workflow.name;
  const source = selectedReport ? selectedReport.origin : analysis ? modeOrigin(analysis, org) : '';
  const rangeContext = selectedReport ? describeWindow(mode, selectedReport.result.window) : analysis ? period(analysis) : 'No saved analysis';
  return <div className="stack overview-page">
    <PageHead title="AI investment performance" description="Understand what your AI costs, what it could return, and where the numbers come from."
      action={<a className="button primary" href="#evaluate">Evaluate AI</a>}/>
    <div className="scope-bar">
      <div className="segments" aria-label="Analysis type">{modes.map(([key,label]) =>
        <button type="button" key={key} aria-pressed={mode === key} onClick={() => setMode(key)}>{label}</button>)}</div>
      <div className="scope-select">
        {selectedReport ? <a href="#reports" className="subtle-link">View portfolio report</a> : rows.some(row => row.analysis) &&
          <label>Summary scope<select value={selected?.detail.workflow.id ?? ''} onChange={event => setFocus(event.target.value)}>
            {rows.filter(row => row.analysis).map(row => <option key={row.detail.workflow.id} value={row.detail.workflow.id}>{row.detail.workflow.name}</option>)}</select></label>}
      </div>
    </div>
    <section className="overview-summary surface" aria-label="Financial summary">
      <div className="context-line"><span>{modeName(mode)}</span><span>{scope ?? org.name}</span><span>{rangeContext}</span><span>USD</span>
        {source && <span>{source}</span>}</div>
      <div className="investment-summary">
        <div className="investment-lead">
          <Stat title="Estimated net benefit" value={e ? formatRange(e.period_net_benefit_usd) : '—'} note="Benefits less operating and setup costs"/>
          {e && <Signal range={e.period_net_benefit_usd}/>}
        </div>
        <div className="investment-facts">
          <Stat title="Estimated ROI" value={e ? formatRange(e.roi_ratio, pct) : '—'} note="Net benefit / total cost"/>
          <Stat title="Estimated payback" value={e ? paybackText(e.payback_months) : '—'} note="At the assumed recurring rate"/>
          <Stat title="AI operating costs" value={e ? formatRange(e.period_operating_usd) : '—'} note="Ongoing AI and human costs"/>
          <Stat title="Modeled benefits" value={e ? formatRange(e.period_benefit_usd) : '—'} note="Compared with manual work"/>
        </div>
      </div>
    </section>
    {analysis && comparable.length > 0 && <div className="overview-grid">
      <section className="chart-surface surface" aria-label="Financial comparison">
        <FinancialChart
          groups={comparable.map(row => ({name: row.detail.workflow.name, estimates: row.analysis!.snapshot.estimates}))}
          period={period(analysis)} source={modeOrigin(analysis, org)}/>
        {comparable.length < rows.filter(row => row.analysis).length &&
          <p className="hint">The chart compares workflows that share the selected period and data source.</p>}
      </section>
      <Panel title="Reading the result" className="overview-notes surface">
        {e && <p>{decision(e.period_net_benefit_usd)}</p>}
        <ul className="evidence-list"><li><b>Forecast</b><span>Uses assumptions about future activity and costs.</span></li>
          <li><b>Assessment</b><span>Combines recorded activity with baseline and cost assumptions.</span></li>
          <li><b>Sensitivity range</b><span>Shows how the estimate changes as assumptions vary.</span></li></ul>
        {!readOnly && !selectedReport && <a className="subtle-link" href="#reports">Build a portfolio report</a>}
      </Panel>
    </div>}
      <Panel title="Workflow comparison" className="table-panel" description={num(details.length) + (details.length === 1 ? " workflow" : " workflows") + " in this organization. Figures use the latest saved analysis for each workflow."}>
        {rows.length ? <div className="table-scroll" role="region" aria-label="Workflow comparison table" tabIndex={0}><table className="overview-table"><thead><tr><th scope="col">Workflow</th><th scope="col" className="amount">Estimated net benefit</th><th scope="col">Financial outlook</th></tr></thead>
          <tbody>{rows.map(({detail, analysis: item}) => <tr key={detail.workflow.id}>
            <td><a className="table-link" href={flowLink(detail)}>{detail.workflow.name}</a><small>{detail.workflow.department}</small></td>
            <td className="amount">{item ? <><b>{formatRange(item.snapshot.estimates.period_net_benefit_usd)}</b><small>{period(item)}</small></> : '—'}</td>
            <td>{item ? <><Signal range={item.snapshot.estimates.period_net_benefit_usd}/><small>{modeOrigin(item, org)}</small></> : <small>No saved analysis</small>}</td>
          </tr>)}</tbody></table></div> : <Empty title="No workflows yet">Add a workflow from AI Workflows to begin.</Empty>}
      </Panel>
  </div>;
}

function WorkflowForm({ org, api, saved }: { org: Organization; api: Api; saved: (id: string) => void }) {
  const [error, setError] = useState(''), [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const field = (key: string) => String(form.get(key) ?? '').trim();
    setError(''); setPending(true);
    try {
      const workflow = await api<Workflow>('/organizations/' + org.id + '/workflows', post({
        name: field('name'), department: field('department'), unit: field('unit'), benefit_pool: field('benefit_pool'),
        outcome_metrics: field('metrics').split(',').map(metric => metric.trim()).filter(Boolean),
      }));
      saved(workflow.id);
    } catch (problem) { setError(errorText(problem)); }
    finally { setPending(false); }
  }
  return <details><summary>Add workflow</summary>
    <form className="form" onSubmit={submit}><div className="split">
      <label>Workflow name<input name="name" required maxLength={160}/></label><label>Department<input name="department" required maxLength={160}/></label>
      <label>One unit of work<input name="unit" required maxLength={80} placeholder="For example, invoice"/></label>
      <label>Unique benefit key<input name="benefit_pool" required maxLength={160} pattern="[a-z][a-z0-9_\-]*" placeholder="finance_invoice_capacity"/></label>
    </div><label>Outcome metric keys (optional)<input name="metrics" placeholder="For example, accuracy_checks, escalations"/></label>
    <p className="hint">Use lowercase keys. The benefit key identifies a distinct source of value for portfolio reporting.</p>
    {error && <Notice error>{error}</Notice>}<div><button className="primary" disabled={pending}>{pending ? 'Adding…' : 'Add workflow'}</button></div></form>
  </details>;
}
export function Workflows({ org, details, api, refresh, readOnly = false }: PageProps & {api: Api; refresh: () => void; readOnly?: boolean}) {
  const [filter, setFilter] = useState('');
  const matches = details.filter(({workflow: item}) => (item.name + ' ' + item.department).toLowerCase().includes(filter.trim().toLowerCase()));
  return <div className="stack"><PageHead title="AI Workflows" description="Review saved forecasts, assessments, and deployment activity."/>
    <Panel title="Registered workflows" className="table-panel" action={<label className="search">Search workflows<input type="search" value={filter}
      onChange={event => setFilter(event.target.value)} placeholder="Workflow or department"/></label>}>
      {matches.length ? <div className="table-scroll" role="region" aria-label="Registered workflows table" tabIndex={0}>
        <table className="workflows-table">
          <thead><tr><th scope="col">Workflow</th><th scope="col">Department</th>
            <th scope="col">Evaluation status</th><th scope="col" className="amount">Estimated net benefit</th>
            <th scope="col">Latest analysis</th><th scope="col">Action</th></tr></thead>
          <tbody>{matches.map(detail => {
            const forecast = latest(detail, 'forecast'), assessment = latest(detail, 'assessment');
            const analysis = detail.analyses[0];
            return <tr key={detail.workflow.id}>
              <td><a className="table-link" href={flowLink(detail)}>{detail.workflow.name}</a>
                <small>{detail.workflow.unit} / {num(detail.deployments.length)} {detail.deployments.length === 1 ? 'deployment' : 'deployments'}</small></td>
              <td>{detail.workflow.department}</td>
              <td>{assessment && forecast ? 'Forecast and assessment' : assessment ? 'Assessment' : forecast ? 'Forecast' : 'No saved analysis'}</td>
              <td className="amount">{analysis ? <><b>{formatRange(analysis.snapshot.estimates.period_net_benefit_usd)}</b>
                <small>{modeName(analysis.mode)} / {modeOrigin(analysis, org)}</small></> : '—'}</td>
              <td>{analysis ? <time dateTime={analysis.created_at}>{date(analysis.created_at)}</time> : '—'}</td>
              <td><a className="subtle-link" href={evaluationLink(detail)} aria-label={'Evaluate ' + detail.workflow.name}>Evaluate</a></td>
            </tr>;
          })}</tbody>
        </table>
      </div> : <Empty title={details.length ? 'No matching workflows' : 'No workflows registered'}>{details.length ? 'Try a different name or department.' : 'Add a workflow to compare its costs and benefits.'}</Empty>}
      {!readOnly && <WorkflowForm org={org} api={api} saved={id => {refresh(); location.hash = 'workflows/' + id;}}/>}
    </Panel>
    {!readOnly && <Panel className="integrations-bar" title="Invoice processing" description="Upload PDFs, check validation results, and review model usage."
      action={<a className="button secondary" href="/?view=invoice">Open invoice tools</a>}><></></Panel>}
  </div>;
}

type DeploymentDraft = 'clean' | 'dirty' | 'saving';

function DeploymentTools({ detail, api, refresh, onDraftChange }: {
  detail: Detail; api: Api; refresh: () => void; onDraftChange: (state: DeploymentDraft) => void;
}) {
  const [deployment, setDeployment] = useState(''), [error, setError] = useState(''), [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(false), [runError, setRunError] = useState('');
  type Run = {execution: {id: string; occurred_at: string; telemetry: {data_origin?: string; units: number; reviewed_units: number; latency_ms?: number}};
    outcomes: Record<string,string>};
  const [runs,setRuns] = useState<Run[]>([]);
  useEffect(() => {
    if (!deployment) return;
    const control = new AbortController();
    setLoading(true); setRunError(''); setRuns([]);
    api<Run[]>('/deployments/' + deployment + '/executions', {signal: control.signal}).then(setRuns)
      .catch(problem => {if (!control.signal.aborted) setRunError(errorText(problem));})
      .finally(() => {if (!control.signal.aborted) setLoading(false);});
    return () => control.abort();
  }, [deployment,api]);
  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const target = event.currentTarget, fields = new FormData(target);
    setError(''); setPending(true); onDraftChange('saving');
    try {
      await api('/workflows/' + detail.workflow.id + '/deployments', post({name: fields.get('name'), adapter: fields.get('adapter')}));
      target.reset(); onDraftChange('clean'); refresh();
    } catch (problem) { onDraftChange('dirty'); setError(errorText(problem)); }
    finally { setPending(false); }
  }
  return <Panel title="Deployments and activity" description="Inspect recent records or register a deployment for assessment.">
    <div className="context-line">{detail.deployments.map(item => <span key={item.id}>{item.name} · {human(item.adapter)}</span>)}</div>
    {!!detail.deployments.length && <label className="bounded">Inspect recorded activity<select value={deployment}
      onChange={event => setDeployment(event.target.value)}><option value="">Select a deployment</option>
      {detail.deployments.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}
    {deployment && (loading ? <Notice>Loading activity…</Notice> : runError ? <Notice error>{runError}</Notice> : runs.length ?
      <div className="table-scroll"><table><thead><tr><th>Recorded (UTC)</th><th>Work units</th><th>Reviewed</th><th>Latency</th><th>Data source</th><th>Outcomes</th></tr></thead>
        <tbody>{runs.map(({execution: run,outcomes}) => <tr key={run.id}><td>{new Date(run.occurred_at.endsWith('Z') ||
          /[+-]\d\d:\d\d$/.test(run.occurred_at) ? run.occurred_at : run.occurred_at + 'Z').toLocaleString(undefined,{timeZone:'UTC'})}</td>
          <td>{num(run.telemetry.units)}</td><td>{num(run.telemetry.reviewed_units)}</td><td>{run.telemetry.latency_ms == null ? '—' : num(run.telemetry.latency_ms) + ' ms'}</td>
          <td>{run.telemetry.data_origin === 'synthetic' ? 'Synthetic' : 'Recorded'}</td>
          <td>{Object.entries(outcomes).map(([key,value]) => human(key) + ' ' + num(value)).join(', ') || '—'}</td></tr>)}</tbody></table></div> :
      <Notice>No execution activity recorded for this deployment.</Notice>)}
    <details><summary>Register a deployment</summary><form className="form" onSubmit={add} onChange={event => {
      const fields = new FormData(event.currentTarget);
      onDraftChange(fields.get('name') || fields.get('adapter') !== 'generic' ? 'dirty' : 'clean');
    }}>
      <fieldset disabled={pending}>
      <div className="split"><label>Name<input required name="name" maxLength={160}/></label>
        <label>Integration<select name="adapter"><option value="generic">Generic telemetry</option><option value="invoice">Invoice processing</option>
          <option value="service_desk">IT service desk</option></select></label></div>
      {error && <Notice error>{error}</Notice>}<div><button className="primary" disabled={pending}>{pending ? 'Registering…' : 'Register deployment'}</button></div></fieldset></form></details>
  </Panel>;
}

export function WorkflowDetails({ detail, org, api, refresh, readOnly = false }: {detail: Detail; org: Organization; api: Api; refresh: () => void; readOnly?: boolean}) {
  const [selection, setSelection] = useState('');
  const [draft, setDraft] = useState<DeploymentDraft>('clean');
  const forecast = latest(detail,'forecast'), assessment = latest(detail,'assessment');
  const selected = detail.analyses.find(item => item.id === selection) ?? assessment ?? forecast;
  const measured = selected?.snapshot.measured;
  return <AppWindow title="Workflow details" backLabel="All workflows" dirty={draft === 'dirty'} saving={draft === 'saving'}
    onClose={() => { location.hash = 'workflows'; }}><div className="stack">
    <PageHead title={detail.workflow.name} description={detail.workflow.department + ' · Work unit: ' + detail.workflow.unit}
      action={<a className="button primary" href={evaluationLink(detail)}>Evaluate workflow</a>}/>
    <Panel title="Forecast versus assessment" description="Forecasts use assumptions about future work. Assessments use activity recorded in the stated period.">
      <div className="split">{[forecast,assessment].map((item,index) => <article className="comparison" key={index}>
        <small>{index === 0 ? 'Pre-adoption forecast' : 'Post-adoption assessment'}</small>
        {item ? <><strong>{formatRange(item.snapshot.estimates.period_net_benefit_usd)}</strong>
          <span>Estimated net benefit · USD</span><span>{period(item)} · {modeOrigin(item,org)}</span>
          <Signal range={item.snapshot.estimates.period_net_benefit_usd}/>
          <button className="secondary" onClick={() => {setSelection(item.id); document.getElementById('analysis-detail')?.scrollIntoView({block:'start'});}}>Inspect analysis</button></> :
          <p>No saved {index === 0 ? 'forecast' : 'assessment'}.</p>}</article>)}</div>
    </Panel>
    {selected && <div id="analysis-detail"><Panel title="Financial analysis" action={<label>Saved analysis<select value={selected.id}
      onChange={event => setSelection(event.target.value)}>{detail.analyses.map(item =>
        <option key={item.id} value={item.id}>{modeName(item.mode)} · {period(item)} · {modeOrigin(item,org)}</option>)}</select></label>}>
      <Results estimates={selected.snapshot.estimates} period={period(selected)} source={modeOrigin(selected,org)}/>
      <details><summary>Evidence and assumptions</summary>
        <dl className="breakdown"><div><dt>Manual baseline</dt><dd>{selected.snapshot.baseline.name}</dd></div>
          <div><dt>Baseline evidence</dt><dd>{selected.snapshot.baseline.evidence}</dd></div>
          <div><dt>Analysis evidence</dt><dd>{selected.snapshot.assumptions.evidence}</dd></div></dl>
        <pre>{JSON.stringify({baseline:selected.snapshot.baseline, assumptions:selected.snapshot.assumptions,
          prior_cost_estimates:selected.snapshot.prior_estimates},null,2)}</pre>
      </details>
    </Panel></div>}
    <Panel title="Workflow performance" description={measured && selected ? period(selected) + ' · ' + modeOrigin(selected,org) : 'Performance metrics are available for saved assessments.'}>
      {measured ? <><div className="stats compact">
        <Stat title="Work units" value={num(measured.units)} note={num(measured.executions) + ' recorded executions'}/>
        <Stat title="Reviewed work" value={num(measured.reviewed_units)} note="Units receiving human review"/>
        <Stat title="Reworked units" value={num(measured.reworked_units)} note="Units requiring correction"/></div>
        <dl className="breakdown"><div><dt>Reported model charges (USD)</dt><dd>{measured.model_charge_runs ? money(measured.model_charge_usd) : 'Unavailable'}</dd></div>
          <div><dt>Reported infrastructure charges (USD)</dt><dd>{measured.infrastructure_charge_runs ? money(measured.infrastructure_charge_usd) : 'Unavailable'}</dd></div>
          <div><dt>Successful executions</dt><dd>{num(measured.successful_executions)}</dd></div>
          {Object.entries(measured.outcomes).map(([key,item]) => <div key={key}><dt>{human(key)}</dt><dd>{num(item)}</dd></div>)}</dl></> :
        <Empty title="No observations in this analysis">Select a post-adoption assessment to see recorded metrics.</Empty>}
    </Panel>
    {!readOnly && <DeploymentTools detail={detail} api={api} refresh={refresh} onDraftChange={setDraft}/>}
  </div></AppWindow>;
}

function download(value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)], {type:'application/json'}));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'agentledger-portfolio-report.json'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
export function Reports({ org, details, api, onReport, report }: PageProps & {api: Api; onReport: (value: PortfolioReport) => void; report?: PortfolioReport}) {
  const [mode,setMode] = useState<Mode>(report?.result.mode ?? 'forecast');
  const [rows,setRows] = useState<number[]>([]), [nextId,setNextId] = useState(0);
  const [error,setError] = useState(''), [pending,setPending] = useState(false);
  const [current,setCurrent] = useState(report);
  const [previewClosed, setPreviewClosed] = useState(false);
  const reopenButton = useRef<HTMLButtonElement>(null);
  const previewRegion = useRef<HTMLDivElement>(null);
  const returningToPreview = useRef(false);
  useEffect(() => {
    if (previewClosed) reopenButton.current?.focus();
    else if (returningToPreview.current) {
      previewRegion.current?.focus();
      returningToPreview.current = false;
    }
  }, [previewClosed]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(event.currentTarget));
    const analysis_ids = details.map(item => String(fields[item.workflow.id] ?? '')).filter(Boolean);
    setPending(true); setError(''); setCurrent(undefined);
    try {
      if (!analysis_ids.length) throw new Error('Choose at least one saved analysis.');
      const selected = details.flatMap(item => item.analyses).filter(item => analysis_ids.includes(item.id));
      const selectedOrigins = [...new Set(selected.map(item => modeOrigin(item,org)))];
      const shared_items = rows.map(i => ({key: fields['key' + i], kind:fields['kind' + i],
        evidence:fields['evidence' + i], usd:readRange(fields,'amount' + i,'shared item amount')}));
      const result = await api<Report>('/organizations/' + org.id + '/rollup', post({
        analysis_ids, shared_items, disjoint_attribution_confirmed: fields.confirmation === 'on',
      }));
      const built = {result,origin:selectedOrigins.join(' · ')};
      setCurrent(built); setPreviewClosed(false); onReport(built);
    } catch (problem) { setError(errorText(problem)); }
    finally { setPending(false); }
  }
  return <div className="stack"><PageHead title="Reports" description="Combine comparable analyses and account for shared costs and benefits."/>
    <Panel className="report-config" title="Build an organization report" description="Choose one analysis per workflow, using the same type and reporting period.">
      {!details.some(item => item.analyses.length) ? <Empty title="No analyses to report">Save an evaluation before building an organization report.</Empty> :
        <form className="form report-form" onSubmit={submit} aria-busy={pending}>
          <label className="bounded">Analysis type<select value={mode} onChange={event => {setMode(event.target.value as Mode); setCurrent(undefined); setError('');}}>
            <option value="forecast">Pre-adoption forecast</option><option value="assessment">Post-adoption assessment</option></select></label>
          <div className="split" key={mode}>{details.map(detail => <label key={detail.workflow.id}>{detail.workflow.name}
            <select name={detail.workflow.id}><option value="">Exclude workflow</option>{detail.analyses.filter(item => item.mode === mode).map(item =>
              <option key={item.id} value={item.id}>{period(item)} · {modeOrigin(item,org)}</option>)}</select></label>)}</div>
          {rows.map(i => <fieldset key={i}><legend>Shared cost or benefit</legend><div className="split">
            <label>Unique attribution key<input name={'key' + i} required maxLength={160} pattern="[a-z][a-z0-9_\-]*"/></label>
            <label>Category<select name={'kind' + i}><option value="recurring_cost">Operating cost for the period</option>
              <option value="recurring_benefit">Benefit for the period</option><option value="implementation">One-time setup cost</option></select></label>
            <label>Amount (USD)<input name={'amount' + i} type="number" required min="0" step="any"/></label>
            <label>Upper amount (optional)<input name={'amount' + i + '_high'} type="number" min="0" step="any"/></label>
          </div><label>Evidence<input name={'evidence' + i} required maxLength={500}/></label>
            <button type="button" className="secondary" onClick={() => setRows(rows.filter(row => row !== i))}>Remove item</button></fieldset>)}
          <div><button type="button" className="secondary" onClick={() => {setRows([...rows,nextId]); setNextId(nextId + 1);}}>Add shared item</button></div>
          <label className="checkbox"><input type="checkbox" name="confirmation" required/>I confirm that the selected analyses cover distinct costs and benefits. Shared items listed above are excluded from those analyses.</label>
          {error && <Notice error>{error}</Notice>}<div><button className="primary" disabled={pending}>{pending ? 'Calculating…' : 'Calculate report'}</button></div>
        </form>}
    </Panel>
    {current && (previewClosed ? <button className="secondary" type="button" ref={reopenButton}
      onClick={() => { returningToPreview.current = true; setPreviewClosed(false); }}>Reopen report preview</button> :
      <div ref={previewRegion} tabIndex={-1} role="region" aria-label="Calculated report">
        <AppWindow title="Report preview" onClose={() => setPreviewClosed(true)}>
          <Panel title="Calculated organization report" className="report-output" description={current.result.analysis_ids.length + ' included workflows · ' + modeName(current.result.mode)}
      action={<button className="secondary" onClick={() => download({organization:org, ...current})}><Icon name="download"/> Download JSON</button>}>
      <p className="hint">{current.result.shared_items.length
        ? `${current.result.shared_items.length} shared ${current.result.shared_items.length === 1 ? 'item' : 'items'} counted once across the report.`
        : 'No shared costs or benefits were added.'}</p>
      <Results estimates={current.result.estimates} period={describeWindow(current.result.mode,current.result.window)} source={current.origin}/>
          </Panel>
        </AppWindow>
      </div>)}
  </div>;
}
