import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { JSDOM } from 'jsdom';
import { createElement, act } from 'react';
import { createRoot } from 'react-dom/client';
import { createServer } from 'vite';

const base = process.argv[2] ?? 'http://localhost:8001';
const out = resolve(process.argv[3] ?? '../verification');
const results = [];
const previews = [];
const request = globalThis.fetch;
let blockNextOrganization = false;
let releaseInitial;
const initialGate = new Promise(resolve => { releaseInitial = resolve; });
let held = false;

async function check(name, run) {
  try { const evidence = await run(); results.push({name, result:'Pass', evidence}); }
  catch (error) { results.push({name, result:'Fail', evidence:error instanceof Error ? error.message : String(error)}); }
}
async function read(path) {
  const response = await request(new URL(path, base));
  assert.ok(response.ok, path + ' returned HTTP ' + response.status);
  return response.json();
}

const breakpoints = [];
await check('Running deployment and forecast preview contract', async () => {
  const response = await request(new URL('/', base));
  assert.equal(response.status, 200);
  const html = await response.text();
  const entry = html.match(/src="(\/assets\/[^"]+)"/)?.[1];
  assert.ok(entry);
  const asset = await request(new URL(entry,base));
  assert.equal(asset.status,200);
  const body = await asset.text();
  const dependencyPaths = [...new Set([...body.matchAll(/assets\/[a-zA-Z0-9_.-]+\.(?:css|js)/g)].map(match=>match[0]))];
  let servedEscapeFix = false;
  for (const path of dependencyPaths) {
    const file = await request(new URL('/' + path,base));
    assert.equal(file.status,200,path);
    const content = await file.text();
    if (path.endsWith('.css') && content.includes('tooltip-dismissed')) servedEscapeFix = true;
    if (path.endsWith('.css')) breakpoints.push(...[...content.matchAll(/@media\(max-width:\s*(\d+)px\)/g)].map(match=>match[1]));
  }
  const schema = await read('/openapi.json');
  assert.ok(schema.paths['/portfolio/forecasts/preview']);
  return 'HTTP 200 for the HTML, entry script, and ' + dependencyPaths.length +
    ' discovered assets. Entry bundle ' + entry.split('/').at(-1) +
    '. OpenAPI lists the read-only forecast preview route. ' +
    (servedEscapeFix ? 'Served CSS contains the Escape dismissal fix.' : 'The served CSS does not yet contain the Escape dismissal fix.');
});

const vite = await createServer({configFile:false,optimizeDeps:{noDiscovery:true,include:[]},
  server:{middlewareMode:true,ws:false},appType:'custom'});
const {window} = new JSDOM('<div id="root"></div>', {url: base});
Object.assign(globalThis,{window,document:window.document,location:window.location,FormData:window.FormData,
  addEventListener:window.addEventListener.bind(window),removeEventListener:window.removeEventListener.bind(window),
  IS_REACT_ACT_ENVIRONMENT:true});
window.scrollTo=()=>{};
window.HTMLElement.prototype.scrollIntoView=()=>{};
const appRoot = createRoot(document.getElementById('root'));
const mount = document.getElementById('root');

globalThis.fetch=async (url, options)=>{
  if (url === '/portfolio/organizations' && !held) {
    held = true;
    await initialGate;
  }
  if (url === '/portfolio/organizations' && blockNextOrganization) {
    blockNextOrganization = false;
    return new Response(null,{status:401});
  }
  // Let only the two calculation routes use POST. Both return results without persisting records.
  if (options?.method && options.method !== 'GET') {
    assert.match(url,/^\/portfolio\/(forecasts\/preview|organizations\/[\w-]+\/rollup)$/);
  }
  const response = await request(new URL(url,base),options);
  if (url === '/portfolio/forecasts/preview' && response.ok) {
    const result = await response.clone().json();
    const sent = JSON.parse(options.body);
    previews.push({months:sent.months, laborPerTicket:sent.baseline.manual_cost_usd_per_unit,
      operating:result.estimates.period_operating_usd, benefits:result.estimates.period_benefit_usd,
      roi:result.estimates.roi_ratio, net:result.estimates.period_net_benefit_usd, payback:result.estimates.payback_months});
  }
  return response;
};
const see = text => mount.textContent.includes(text);
function visible(element) { return !element.closest('[hidden]'); }
async function until(predicate, message) {
  for (let i=0; i<100; i++) {
    if (predicate()) return;
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,40));});
  }
  throw Error(message);
}
async function click(name) {
  const button = [...mount.querySelectorAll('button')].find(el=>visible(el)&&el.textContent.trim()===name);
  assert.ok(button, 'Button unavailable: '+name);
  await act(async()=>button.click());
}
async function navigate(hash) {
  await act(async()=>{location.hash=hash;await new Promise(resolve=>setTimeout(resolve,30));});
}
async function select(element,value) {
  assert.ok(element);
  await act(async()=>{element.value=value;element.dispatchEvent(new window.Event('change',{bubbles:true}));});
}
const field = name => [...mount.querySelectorAll('[name="'+name+'"]')].find(visible);
let org;
let flows = [];
try {
  const {default:App}=await vite.ssrLoadModule('/src/portfolio.tsx');
  await check('Loading state and navigation', async()=>{
    await act(async()=>appRoot.render(createElement(App)));
    assert.ok(see('Loading workspace'));
    assert.deepEqual([...mount.querySelectorAll('nav a')].map(el=>el.textContent.trim()),
      ['Overview','AI Workflows','Evaluate AI','Reports','Settings']);
    await act(async()=>releaseInitial());
    org=(await read('/portfolio/organizations')).find(item=>/synthetic/i.test(item.name));
    assert.ok(org,'A synthetic demo organization was not available.');
    await until(()=>!see('Loading workspace'),'Workspace did not finish loading.');
    await select(mount.querySelector('.org-select select'),org.id);
    await until(()=>see('Workflow comparison')&&!see('Loading workspace'),'Synthetic overview did not load.');
    flows=await read('/portfolio/organizations/'+org.id+'/workflows');
    return 'Delayed the real organization response to observe the loading state, then selected an existing synthetic workspace.';
  });
  await check('Overview and chart controls',async()=>{
    assert.equal(mount.querySelector('h1')?.textContent, 'AI investment performance');
    const summary = mount.querySelector('[aria-label="Financial summary"]')?.textContent;
    for (const label of ['Estimated net benefit','Estimated ROI','Estimated payback','AI operating costs','Modeled benefits']) {
      assert.ok(summary?.includes(label), label);
    }
    assert.ok(see('Synthetic'));
    const track=mount.querySelector('.financial-track.net');
    assert.ok(track);
    assert.ok(track.getAttribute('aria-describedby'));
    await act(async()=>track.click());
    assert.ok(track.querySelector('.financial-tooltip.open'));
    await act(async()=>track.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
    assert.equal(track.querySelector('.financial-tooltip.open'),null);
    assert.ok(track.classList.contains('tooltip-dismissed'));
    await click('Pre-adoption');
    assert.ok(see('forecast'));
    return 'Synthetic investment summary with ROI and payback, comparison chart, tooltip toggle and Escape suppression state, and mode switch exercised. The DOM cannot verify whether CSS actually hides the tooltip.';
  });
  await check('AI Workflows and saved analysis',async()=>{
    await navigate('workflows');
    assert.ok(see('Registered workflows'));
    const search=mount.querySelector('input[type=search]');
    assert.ok(search);
    assert.ok(see('Add workflow'));
    const links=[...mount.querySelectorAll('.workflows-table a.table-link')];
    assert.ok(links.length > 0);
    const headings = [...mount.querySelectorAll('.workflows-table thead th')].map(node=>node.textContent.trim());
    assert.deepEqual(headings, ['Workflow','Department','Evaluation status','Estimated net benefit','Latest analysis','Action']);
    assert.ok(mount.querySelector('.workflows-table time[datetime]'));
    assert.ok(mount.querySelector('.workflows-table a[href^="#evaluate/"]'));
    await navigate('workflows/'+flows[0].id);
    await until(()=>see('Forecast versus assessment'),'Workflow detail never loaded.');
    assert.ok(see('Workflow performance'));
    assert.ok(see('Deployments and activity'));
    return 'Workflow table with latest-analysis date and evaluation links, search field, workflow detail, forecast-versus-assessment view, and deployment section rendered against live data.';
  });
  await check('Evaluate AI example and recalculation',async()=>{
    await navigate('evaluate');
    await click('Try an example');
    assert.equal(field('minutes').value,'6');
    await click('Continue');
    assert.equal(field('units').value,'900');
    await click('Continue');
    await click('Calculate example');
    await until(()=>see('Hypothetical customer-support result')||mount.querySelector('[role=alert]'),'Example preview did not complete.');
    assert.ok(see('Hypothetical customer-support result'),mount.querySelector('[role=alert]')?.textContent);
    assert.ok(see('do not represent company savings'));
    await click('Back'); await click('Back');
    field('minutes').value='-1';
    await click('Continue');
    assert.ok(mount.querySelector('[role=alert]'),'Negative input should fail validation.');
    assert.equal(previews.length,1);
    field('minutes').value='7';
    await click('Continue'); await click('Continue');
    await click('Calculate example');
    await until(()=>previews.length===2&&see('Hypothetical customer-support result'),'Recalculation did not complete.');
    assert.notDeepEqual(previews[0].roi,previews[1].roi);
    await click('Exit example');
    assert.ok(!see('Hypothetical customer-support result'));
    return 'Calculated the default scenario, confirmed a negative handling-time error without an API request, changed the lower handling-time input from 6 to 7 minutes, and confirmed the live engine returned a different ROI range. No portfolio records were created.';
  });
  await check('Reports and attribution',async()=>{
    await navigate('reports');
    assert.ok(see('Build an organization report'));
    const first=flows[0];
    const detail=await read('/portfolio/workflows/'+first.id);
    const forecast=detail.analyses.find(item=>item.mode==='forecast');
    assert.ok(forecast,'No saved forecast for the synthetic workflow.');
    await select(field(first.id),forecast.id);
    await click('Add shared item');
    field('key0').value='audit_example_shared';
    field('amount0').value='10';
    field('evidence0').value='Hypothetical QA attribution';
    assert.ok(field('confirmation').validity.valueMissing,'Confirmation should block submission while unchecked.');
    field('confirmation').checked=true;
    await click('Calculate report');
    await until(()=>see('Calculated organization report')||mount.querySelector('[role=alert]'),'Roll-up did not complete.');
    assert.ok(see('Calculated organization report'),mount.querySelector('[role=alert]')?.textContent);
    const originalClick=window.HTMLAnchorElement.prototype.click;
    const originalObjectUrl=URL.createObjectURL, originalRevokeUrl=URL.revokeObjectURL;
    let blob, filename;
    try {
      URL.createObjectURL=value=>{blob=value;return 'blob:agentledger-audit';};
      URL.revokeObjectURL=()=>{};
      window.HTMLAnchorElement.prototype.click=function(){filename=this.download;};
      await click('Download JSON');
      assert.equal(filename,'agentledger-portfolio-report.json');
      const document=JSON.parse(await blob.text());
      assert.ok(document.result.estimates.period_net_benefit_usd);
    } finally {
      window.HTMLAnchorElement.prototype.click=originalClick;
      URL.createObjectURL=originalObjectUrl;
      URL.revokeObjectURL=originalRevokeUrl;
    }
    return 'Selected a saved forecast, added a hypothetical shared item, checked the attribution requirement, and obtained a live report. The download control generated a JSON report in the DOM harness. Native file download remains a browser check.';
  });
  await check('Settings and authentication error handling',async()=>{
    await navigate('settings');
    assert.ok(see('Workspace access'));
    assert.ok(see('Create organization'));
    blockNextOrganization=true;
    await click('Apply key');
    await until(()=>see('Enter a valid workspace key'),'Injected 401 did not show a recoverable error.');
    await click('Apply key');
    await until(()=>!see('Enter a valid workspace key')&&see('Current organization'),'Settings did not recover after retry.');
    return 'Injected a 401 locally, checked the user-facing error, and retried against the real API. No credentials were supplied and no organization was created.';
  });
} finally {
  await act(async()=>appRoot.unmount());
  window.close();
  await vite.close();
}

const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const percent = value => value ? (Number(value.low)*100).toFixed(2)+'% to '+(Number(value.high)*100).toFixed(2)+'%' : 'Unavailable';
const money = new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
const usd = value => money.format(value.low)+' to '+money.format(value.high);
await mkdir(out,{recursive:true});
await writeFile(resolve(out,'agentledger-review.html'),`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>AgentLedger verification report</title>
<style>body{font:16px/1.55 system-ui;color:#172642;margin:2rem auto;padding:0 1rem;max-width:960px}h1,h2{line-height:1.15}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:.55rem;border-bottom:1px solid #dae3f0}th{background:#edf3ff}.note{padding:1rem;background:#f3f6fb;border-radius:.5rem}.pass{color:#126b50}.fail{color:#a53232}code{font-size:.9em}</style>
<h1>AgentLedger verification report</h1><p>Target <code>${escape(base)}</code>. Checked ${escape(new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata',timeZoneName:'short'}))}.</p>
<p class="note"><strong>Verification method.</strong> HTTP checks used the running service. Interaction checks rendered the repository’s React source in jsdom and called that service. Browser access was unavailable. This report contains test evidence and no screenshots. It excludes organization names, credentials, and real financial values.</p>
<table><thead><tr><th>Journey</th><th>Result</th><th>Evidence</th></tr></thead><tbody>${results.map(item=>`<tr><td>${escape(item.name)}</td><td class="${item.result.toLowerCase()}">${item.result}</td><td>${escape(item.evidence)}</td></tr>`).join('')}</tbody></table>
<h2>Hypothetical customer-support calculations</h2><p>These results are illustrative forecast calculations in USD. They do not represent company savings.</p>
${previews.length ? `<table><thead><tr><th>Run</th><th>Forecast</th><th>Manual cost / ticket</th><th>Operating cost</th><th>Modeled benefits</th><th>Net benefit</th><th>ROI</th></tr></thead><tbody>${previews.map((p,i)=>`<tr><td>${i+1}</td><td>${p.months} months</td><td>${usd(p.laborPerTicket)}</td><td>${usd(p.operating)}</td><td>${usd(p.benefits)}</td><td>${usd(p.net)}</td><td>${percent(p.roi)}</td></tr>`).join('')}</tbody></table>`: '<p>No successful preview returned.</p>'}
<h2>External browser review</h2><ul><li>Capture desktop Overview and mobile Overview at 390 px. Look for clipped comparison labels, chart marks, or horizontal overflow outside scrollable tables.</li><li>Check workflow detail at desktop and tablet widths. Inspect chart tooltip placement by mouse, keyboard, and touch, including Escape dismissal and negative endpoints.</li><li>Capture the example before and after recalculation. Confirm the edited input and updated net benefit and ROI stay visible on narrow screens.</li><li>Open Reports on mobile, exercise attribution and test the native JSON download. Review Settings keyboard focus and the workspace-key response.</li></ul><p>Stylesheet breakpoint values found in served assets (px): ${escape([...new Set(breakpoints)].sort((a,b)=>Number(b)-Number(a)).join(', ')||'none found')}. Their presence does not verify responsive rendering.</p></html>`);
console.log(results.map(item=>item.result+' '+item.name+': '+item.evidence).join('\n'));
console.log('Report: '+resolve(out,'agentledger-review.html'));
if (results.some(item=>item.result==='Fail')) process.exitCode=1;
