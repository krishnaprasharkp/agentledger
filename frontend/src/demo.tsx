import { useEffect, useState } from 'react';
import { AppSidebar } from './portfolio';
import { Evaluator } from './evaluator';
import { Overview, Workflows, WorkflowDetails } from './pages';
import { Empty, Notice, PageHead, Panel } from './components';
import type { Api, Detail, Organization } from './data';

const previewApi: Api = async <T,>(path: string, options?: RequestInit) => {
  if (path !== '/forecasts/preview' || options?.method !== 'POST') throw new Error('Only forecast previews are available.');
  const response = await fetch('/demo/forecasts/preview', {
    method: 'POST', credentials: 'omit', body: options.body, headers: { 'Content-Type': 'application/json' },
  });
  if (response.status === 429) throw new Error('Too many previews. Wait a moment and try again.');
  if (!response.ok) throw new Error('The preview could not be calculated. Check your inputs and try again.');
  return response.json() as Promise<T>;
};

type Sample = { organization: Organization; details: Detail[] };
const route = () => location.hash.slice(1).split('/');
const noSave = () => {};

export default function Demo() {
  const [[page, workflow], setRoute] = useState(route);
  const [sample, setSample] = useState<Sample>();
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const change = () => {
      setRoute(route());
      document.getElementById('demo-content')?.focus();
      window.scrollTo(0, 0);
    };
    addEventListener('hashchange', change);
    return () => removeEventListener('hashchange', change);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    fetch('/demo/portfolio', { signal: controller.signal, credentials: 'omit' }).then(response => {
      if (!response.ok) throw new Error();
      return response.json() as Promise<Sample>;
    }).then(setSample).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => controller.abort();
  }, [retry]);

  const active = page === 'workflows' || page === 'evaluate' || page === 'reports' || page === 'settings' ? page : 'overview';
  const selected = sample?.details.find(item => item.workflow.id === workflow);
  return <div className="app-shell">
    <a className="skip" href="#demo-content" onClick={event => {
      event.preventDefault();
      document.getElementById('demo-content')?.focus();
    }}>Skip to content</a>
    <AppSidebar activePage={active}/>
    <div className="workspace">
      <header className="topbar"><strong>Public demo</strong><span>Synthetic data only</span></header>
      <main id="demo-content" tabIndex={-1}>
        {active === 'evaluate' ? <Evaluator publicDemo details={[]} api={previewApi} onSaved={noSave}/> :
          active === 'reports' ? <div className="stack"><PageHead title="Reports" description="This demo does not access saved reports."/>
            <Panel><a className="button primary" href="#evaluate">Calculate a preview</a></Panel></div> :
          active === 'settings' ? <div className="stack"><PageHead title="Demo settings" description="This installation uses fictional data and does not save changes."/>
            <Panel title="Public access"><p>Enter synthetic assumptions only. Workspace access, uploads, and provider execution are disabled.</p></Panel></div> :
          error ? <><Notice error>The sample workspace could not load.</Notice>
            <button className="secondary" onClick={() => setRetry(value => value + 1)}>Retry</button></> :
          !sample ? <Notice>Loading synthetic workspace…</Notice> :
          active === 'workflows' ? workflow ? selected ?
            <WorkflowDetails key={selected.workflow.id} readOnly detail={selected} org={sample.organization} api={previewApi} refresh={noSave}/> :
            <Empty title="Sample workflow unavailable"><a href="#workflows">Return to sample workflows</a></Empty> :
            <Workflows readOnly org={sample.organization} details={sample.details} api={previewApi} refresh={noSave}/> :
          <Overview readOnly org={sample.organization} details={sample.details}/>}
      </main>
    </div>
  </div>;
}
