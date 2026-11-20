import './portfolio.css';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { apiFor, ApiError, errorText, post } from './data';
import type { Api, Detail, Organization, Workflow } from './data';
import { Empty, Icon, Notice, PageHead, Panel } from './components';
import { Overview, Reports, WorkflowDetails, Workflows } from './pages';
import type { PortfolioReport } from './pages';
import { Evaluator } from './evaluator';

const pages = [
  ['overview','Overview'], ['workflows','AI Workflows'], ['evaluate','Evaluate AI'], ['reports','Reports'], ['settings','Settings'],
] as const;
type Page = typeof pages[number][0];
function route() {
  const [page, id] = location.hash.slice(1).split('/');
  return {page: (pages.some(item => item[0] === page) ? page : 'overview') as Page, id};
}

function Settings({ api, accessKey, apply, org, saved, authError, accessStatus }: { api: Api; accessKey: string; apply: (value: string) => void;
  org?: Organization; saved: (value: Organization) => void; authError: boolean; accessStatus: string;
}) {
  const [error, setError] = useState(''), [working,setWorking] = useState(false);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const target = event.currentTarget;
    const name = String(new FormData(target).get('name') ?? '').trim();
    if (!name) {setError('Enter an organization name.');return;}
    setWorking(true);setError('');
    try {saved(await api<Organization>('/organizations',post({name})));target.reset();}
    catch (problem) {setError(errorText(problem));}
    finally {setWorking(false);}
  }
  return <div className="stack"><PageHead title="Settings" description="Manage access, organizations, and integrations."/><div className="stack settings-sections">
    <Panel title="Workspace access" description="The key stays in this tab until you reload.">
      <form className="form bounded" onSubmit={event => {
        event.preventDefault(); const form = event.currentTarget;
        apply(String(new FormData(form).get('key') ?? '').trim()); form.reset();
      }}>
        <label>Workspace key<input name="key" type="password" autoComplete="off" placeholder="Required for protected workspaces"/></label>
        {accessStatus && <Notice>{accessStatus}</Notice>}
        <div className="actions"><button className="primary">Apply key</button>{accessKey && <button type="button" className="secondary" onClick={() => apply('')}>Clear access key</button>}</div>
      </form>
    </Panel>
    {!authError && <Panel title="Organizations" description={org ? 'Current organization: ' + org.name : 'Create an organization to group its AI workflows.'}>
      <form className="form bounded" onSubmit={create}>
        <label>New organization name<input name="name" maxLength={160} required/></label>
        {error && <Notice error>{error}</Notice>}<div><button className="primary" disabled={working}>{working ? 'Creating…' : 'Create organization'}</button></div>
      </form></Panel>}
    <Panel title="Developer integrations" description="API schemas for telemetry, provider configuration, and automation.">
      <a className="button secondary" href="/docs">Open API reference</a>
    </Panel>
  </div></div>;
}

export function AppSidebar({activePage, prefix = ''}: {activePage: Page; prefix?: string}) {
  return (
    <aside className="sidebar">
      <a href={prefix + '#overview'} className="brand">
        <img className="brand-logo" src="/assets/agentledger-final-logo.png" alt="AgentLedger" width="2170" height="725"/>
      </a>
      <nav aria-label="Main navigation">{pages.map(([page,label]) => <a key={page} href={prefix + '#' + page} aria-current={activePage === page ? 'page' : undefined}>
        <Icon name={page}/><span>{label}</span></a>)}</nav>
    </aside>
  );
}

export default function Portfolio() {
  const [nav,setNav] = useState(route);
  const previousRoute = useRef(nav);
  const [key,setKey] = useState(''), [revision,setRevision] = useState(0), [keyRetry,setKeyRetry] = useState(0);
  const [organizations,setOrgs] = useState<Organization[]>([]), [organization,setOrg] = useState('');
  const [details,setDetails] = useState<Detail[]>([]), [report,setReport] = useState<PortfolioReport>();
  const [orgLoading,setOrgLoading] = useState(true), [detailsLoading,setDetailsLoading] = useState(false);
  const [orgError,setOrgError] = useState<unknown>(), [detailError,setDetailError] = useState<unknown>();
  const api = useMemo(() => apiFor(key), [key]);
  const active = organizations.find(item => item.id === organization);
  const refresh = () => setRevision(value => value + 1);

  useEffect(() => {
    function changed() {setNav(route()); window.scrollTo(0,0);}
    addEventListener('hashchange',changed);
    return () => removeEventListener('hashchange',changed);
  },[]);
  useEffect(() => {
    document.title = pages.find(item => item[0] === nav.page)?.[1] + ' | AgentLedger';
    if (nav !== previousRoute.current) {
      document.getElementById('main-content')?.focus({preventScroll: true});
      previousRoute.current = nav;
    }
  },[nav]);

  useEffect(() => {
    const control = new AbortController();
    setOrgLoading(true); setOrgError(undefined);
    api<Organization[]>('/organizations',{signal:control.signal}).then(items => {
      if (control.signal.aborted) return;
      setOrgs(items);
      setOrg(current => items.some(item => item.id === current) ? current : items[0]?.id ?? '');
    }).catch(problem => {if (!control.signal.aborted) setOrgError(problem);})
      .finally(() => {if (!control.signal.aborted) setOrgLoading(false);});
    return () => control.abort();
  },[api,keyRetry]);
  useEffect(() => {
    if (!organization) {setDetails([]);setDetailsLoading(false);return;}
    const control = new AbortController();
    setDetailsLoading(true);setDetailError(undefined);
    api<Workflow[]>('/organizations/' + organization + '/workflows',{signal:control.signal})
      .then(items => Promise.all(items.map(item => api<Detail>('/workflows/' + item.id,{signal:control.signal}))))
      .then(items => {if (!control.signal.aborted) setDetails(items);})
      .catch(problem => {if (!control.signal.aborted) setDetailError(problem);})
      .finally(() => {if (!control.signal.aborted) setDetailsLoading(false);});
    return () => control.abort();
  },[organization,api,revision]);

  function selectOrg(id: string) {
    if (id === organization) return;
    setDetailsLoading(true); setDetails([]);setDetailError(undefined); setReport(undefined); setOrg(id);
    if (nav.id) location.hash = nav.page;
  }
  function applyKey(value: string) {
    if (value !== key) {setOrgs([]);setOrg('');setDetails([]);setReport(undefined);setKey(value);}
    setKeyRetry(current => current + 1);
  }
  const error = orgError ?? detailError;
  const denied = error instanceof ApiError && error.status === 401;
  const detail = details.find(item => item.workflow.id === nav.id);
  const home = orgLoading || (detailsLoading && !details.length) ? <Notice>Loading workspace…</Notice>
    : !active ? <Panel><Empty title="Set up your organization">Add an organization to start evaluating AI workflows.</Empty>
      <a className="button primary" href="#settings">Open Settings</a></Panel> : null;

  let content;
  if (nav.page === 'settings') content = <Settings api={api} accessKey={key} apply={applyKey} org={active} authError={denied}
    accessStatus={keyRetry && orgLoading ? 'Checking access…' : keyRetry && !orgError && key ? 'Workspace access verified.' : ''}
    saved={item => {
    setOrgs(items => [...items,item]); selectOrg(item.id);
  }}/>;
  else if (nav.page === 'evaluate' && !active && !orgLoading && !error)
    content = <Evaluator details={[]} api={api} onSaved={refresh}/>;
  else if (error || home) content = home;
  else if (active) {
    switch (nav.page) {
      case 'overview': content = <Overview key={active.id} org={active} details={details} report={report}/>; break;
      case 'workflows': content = nav.id ? detail ? <WorkflowDetails key={detail.workflow.id} org={active} detail={detail} api={api} refresh={refresh}/>
        : detailsLoading ? <Notice>Loading workflow…</Notice> : <Panel><Empty title="Workflow unavailable">Check the selected organization.</Empty>
          <a className="subtle-link" href="#workflows">Return to workflows</a></Panel>
        : <Workflows key={active.id} org={active} details={details} api={api} refresh={refresh}/>; break;
      case 'evaluate': content = <Evaluator key={active.id + (nav.id ?? '')} org={active} details={details} api={api} onSaved={refresh} initialWorkflow={nav.id}/>; break;
      case 'reports': content = <Reports key={active.id} org={active} details={details} api={api} onReport={setReport} report={report}/>; break;
    }
  }
  return <div className="app-shell">
    <a href="#main-content" className="skip" onClick={event => {event.preventDefault(); document.getElementById("main-content")?.focus();}}>Skip to content</a>
    <AppSidebar activePage={nav.page}/>
    <div className="workspace">
      <header className="topbar">
        {organizations.length ? <label className="org-select"><span>Organization</span><select value={organization} onChange={event => selectOrg(event.target.value)}>
          {organizations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : <span>Organization workspace</span>}
        <button className="secondary refresh" disabled={orgLoading || detailsLoading} onClick={() => {if (orgError || !organization) setKeyRetry(value => value + 1);else refresh();}}><Icon name="refresh"/> Refresh</button>
      </header>
      <main id="main-content" tabIndex={-1} aria-busy={orgLoading || detailsLoading}>
        {error !== undefined && <Notice error>{errorText(error)} {denied && nav.page !== 'settings' && <a href="#settings">Open Settings</a>}</Notice>}
        {content}
      </main>
    </div>
  </div>;
}
