import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

const root = createRoot(document.getElementById('root')!);
root.render(<p role="status">Loading AgentLedger…</p>);

async function launch() {
  const response = await fetch('/app-mode', {cache: 'no-store'});
  if (!response.ok) throw new Error('Mode unavailable');
  const {public_demo} = await response.json();
  if (typeof public_demo !== 'boolean') throw new Error('Invalid application mode');
  const {default: App} = public_demo ? await import('./demo') :
    new URLSearchParams(location.search).get('view') === 'invoice' ? await import('./invoice') : await import('./portfolio');
  root.render(<StrictMode><App/></StrictMode>);
}

void launch().catch(() => root.render(<p role="alert">AgentLedger could not start. Reload to try again.</p>));
