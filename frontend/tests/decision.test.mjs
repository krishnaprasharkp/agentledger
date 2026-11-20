import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { createElement, act } from 'react';
import { createRoot } from 'react-dom/client';
import { createServer } from 'vite';

let vite;
let finance;
let Evaluator;
let AppWindow;
let WorkflowDetails;
let Reports;
let Demo;
const bounds = (low, high) => ({low: String(low), high: String(high)});
const estimates = {
  period_operating_usd: bounds(20, 40), period_benefit_usd: bounds(30, 60),
  period_net_benefit_usd: bounds(-25, 30), implementation_usd: bounds(10, 15), roi_ratio: bounds(-.5, .8),
  payback_months: { earliest: '2', latest: null }, months: '12',
  cost_breakdown_usd: { review: bounds(5, 30), maintenance: bounds(15, 15) },
  benefit_breakdown_usd: { counterfactual_manual_cost: bounds(30, 60) },
  component_sensitivity_span_usd: { review: '25', maintenance: '0', counterfactual_manual_cost: '30' },
};

before(async () => {
  vite = await createServer({configFile: false, optimizeDeps: {noDiscovery: true, include: []},
    server: {middlewareMode: true, ws: false}, appType: 'custom'});
  finance = await vite.ssrLoadModule('/src/finance.tsx');
  ({ Evaluator } = await vite.ssrLoadModule('/src/evaluator.tsx'));
  ({ default: Demo } = await vite.ssrLoadModule('/src/demo.tsx'));
  ({ AppWindow } = await vite.ssrLoadModule('/src/appWindow.tsx'));
  ({ WorkflowDetails, Reports } = await vite.ssrLoadModule('/src/pages.tsx'));
});
after(async () => { await vite?.close(); });

async function withDom(run) {
  const { window } = new JSDOM('<div id="root"></div>');
  window.scrollTo = () => {};
  const globals = {window, document: window.document, location: window.location, FormData: window.FormData,
    addEventListener: window.addEventListener.bind(window), removeEventListener: window.removeEventListener.bind(window), IS_REACT_ACT_ENVIRONMENT: true};
  const previous = Object.fromEntries(Object.keys(globals).map(key => [key, globalThis[key]]));
  Object.assign(globalThis, globals);
  const container = document.getElementById('root'), root = createRoot(container);
  try { await run(root, container); }
  finally {
    await act(async () => root.unmount());
    window.close();
    Object.assign(globalThis, previous);
  }
}

test('decision explanations preserve losses, break-even, and uncertainty', () => {
  assert.match(finance.decision(bounds(-12, -5)), /costs exceed/);
  assert.match(finance.decision(bounds(-12, 5)), /crosses break-even/);
  assert.match(finance.decision(bounds(0, 0)), /equal total costs/);
  assert.match(finance.decision(bounds(1, 5)), /benefits exceed/);
  assert.equal(finance.drivers(estimates).cost[0], 'review');
  assert.deepEqual(finance.drivers(estimates).sensitivity.map(([key]) => key), ['counterfactual_manual_cost','review']);
  const axis = finance.rangeAxis([bounds(-25, 75)]);
  assert.equal(axis.position(0), 25);
  assert.equal(axis.position(-25), 0);
  assert.equal(axis.position(75), 100);
});

test('financial chart exposes exact signed bounds, provenance and a toggleable tooltip', async () => {
  await withDom(async (root, container) => {
    await act(async () => root.render(createElement(finance.FinancialChart,
      {groups: [{name: 'Support', estimates}], period: '12-month forecast', source: 'Synthetic assumptions'})));
    assert.match(container.textContent, /USD.*Synthetic assumptions/);
    const track = container.querySelector('.financial-track.net');
    assert.match(track.getAttribute('aria-label'), /-\$25\.00 to \$30\.00/);
    await act(async () => track.click());
    assert.match(track.querySelector('.financial-tooltip.open').textContent, /12-month forecast/);
    await act(async () => track.click());
    assert.equal(track.querySelector('.financial-tooltip.open'), null);
    await act(async () => track.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})));
    assert.ok(track.classList.contains('tooltip-dismissed'));
    await act(async () => track.click());
    assert.ok(!track.classList.contains('tooltip-dismissed'));
    assert.ok(track.querySelector('.financial-tooltip.open'));
  });
});

test('customer-support example is editable and calculates without saving records', async () => {
  await withDom(async (root, container) => {
    const calls = [];
    const api = async (path, request) => {
      calls.push([path, JSON.parse(request.body)]);
      const base = process.env.AGENTLEDGER_TEST_API;
      if (!base) return {estimates};
      const response = await fetch(base + '/portfolio' + path, {...request, headers: {'Content-Type': 'application/json'}});
      assert.ok(response.ok, await response.clone().text());
      return response.json();
    };
    await act(async () => root.render(createElement(Evaluator, {details: [], api, onSaved: () => assert.fail('Example saved')})));
    const click = async label => {
      const button = [...container.querySelectorAll('button')].find(element => element.textContent === label && !element.closest('[hidden]'));
      assert.ok(button, label);
      await act(async () => button.click());
    };
    await click('Try an example');
    assert.match(container.textContent, /Customer support automation/);
    const minutes = container.querySelector('[name=minutes]');
    assert.equal(minutes.value, '6');
    minutes.value = '7';
    await click('Continue');
    assert.equal(container.querySelector('[name=units]').value, '900');
    await click('Continue');
    await click('Calculate example');
    for (let attempt = 0; attempt < 100 && !container.querySelector('.financial-chart') && !container.querySelector('[role=alert]'); attempt++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
    }
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], '/forecasts/preview');
    assert.equal(calls[0][1].baseline.manual_cost_usd_per_unit.low, '3.5');
    assert.equal(calls[0][1].review_fraction.high, '0.4');
    assert.match(container.textContent, /Hypothetical customer-support result/);
    assert.match(container.textContent, /could produce a modeled gain or loss/);
    assert.match(container.textContent, /do not represent company savings/);
    assert.match(container.textContent, /How the estimate is calculated/);
    await click('Exit example');
    assert.doesNotMatch(container.textContent, /Hypothetical customer-support result/);
  });
});


test('opening and exiting the example preserves a regular forecast draft', async () => {
  await withDom(async (root, container) => {
    const details = [{workflow: {id: 'invoice', name: 'Invoices', unit: 'invoice', outcome_metrics: []},
      deployments: [], baselines: [], analyses: []}];
    await act(async () => root.render(createElement(Evaluator, {
      details, org: {id: 'org', name: 'Organization'}, onSaved: () => {},
      api: async () => assert.fail('Switching examples must not call the API'),
    })));
    const click = async label => {
      const button = [...container.querySelectorAll('button')].find(element => element.textContent === label && !element.closest('[hidden]'));
      assert.ok(button, label);
      await act(async () => button.click());
    };
    const draft = container.querySelector('[name=baseline_name]');
    draft.value = 'Draft invoice baseline';
    await click('Try an example');
    assert.ok(draft.closest('[hidden]'));
    await click('Exit example');
    assert.equal(draft.value, 'Draft invoice baseline');
    assert.equal(draft.closest('[hidden]'), null);
  });
});


const windowButton = (container, name) => {
  const match = [...container.querySelectorAll('button')].find(button =>
    (button.getAttribute('aria-label') ?? button.textContent) === name);
  assert.ok(match, name);
  return match;
};
const clickWindow = (container, name) => act(async () => windowButton(container, name).click());

test('window restores and expands without remounting its form', async () => {
  await withDom(async (root, container) => {
    let closed = false;
    await act(async () => root.render(createElement(AppWindow, {title: 'Example', onClose: () => {closed = true;}},
      createElement('input', {'aria-label': 'Draft'}))));
    const input = container.querySelector('input');
    input.value = 'Unsaved example';
    await clickWindow(container, 'Minimize Example');
    assert.equal(input.closest('.app-window-body').hidden, true);
    assert.equal(windowButton(container, 'Restore Example').getAttribute('aria-expanded'), 'false');
    await clickWindow(container, 'Restore window');
    assert.equal(input.closest('.app-window-body').hidden, false);
    assert.equal(document.activeElement, windowButton(container, 'Minimize Example'));
    await clickWindow(container, 'Expand Example');
    assert.equal(container.querySelector('.app-window').dataset.expanded, 'true');
    await clickWindow(container, 'Minimize Example');
    await clickWindow(container, 'Restore Example');
    assert.equal(container.querySelector('.app-window').dataset.expanded, 'true');
    await clickWindow(container, 'Restore size of Example');
    assert.equal(container.querySelector('.app-window').dataset.expanded, 'false');
    assert.equal(container.querySelector('input'), input);
    assert.equal(input.value, 'Unsaved example');
    await clickWindow(container, 'Close Example');
    assert.equal(closed, true);
  });
});

test('closing workflow details guards an unsaved deployment and allows keyboard cancellation', async () => {
  await withDom(async (root, container) => {
    location.hash = '#workflows/support';
    const detail = { workflow: {id: 'support', name: 'Support', department: 'Operations', unit: 'ticket'},
      baselines: [], deployments: [], analyses: [] };
    await act(async () => root.render(createElement(WorkflowDetails, {
      detail, org: {id: 'org', name: 'Organization'}, refresh: () => {},
      api: async () => assert.fail('Editing or closing the draft must not send any request'),
    })));
    container.querySelector('details').open = true;
    const draft = container.querySelector('[name=name]');
    draft.value = 'Draft deployment';
    const integration = container.querySelector('[name=adapter]');
    await act(async () => {
      integration.value = 'invoice';
      integration.dispatchEvent(new window.Event('change', {bubbles: true}));
    });
    await clickWindow(container, 'Minimize Workflow details');
    await clickWindow(container, 'Expand Workflow details');
    assert.equal(draft.value, 'Draft deployment');
    assert.equal(integration.value, 'invoice');
    await clickWindow(container, 'All workflows');
    assert.match(container.querySelector('[role=alert]').textContent, /Unsaved changes/);
    assert.equal(document.activeElement, windowButton(container, 'Keep editing'));
    await act(async () => document.activeElement.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})));
    assert.equal(container.querySelector('[role=alert]'), null);
    assert.equal(location.hash, '#workflows/support');
    assert.equal(document.activeElement, windowButton(container, 'Close Workflow details'));
    await clickWindow(container, 'Close Workflow details');
    await clickWindow(container, 'Close without saving');
    assert.equal(location.hash, '#workflows');
  });
});

test('closing and reopening a report retains the calculated result and moves focus', async () => {
  await withDom(async (root, container) => {
    const report = {result: {mode: 'forecast', window: {months: 12}, analysis_ids: ['analysis'],
      estimates, shared_items: []}, origin: 'User assumptions'};
    await act(async () => root.render(createElement(Reports, {
      report, details: [], org: {id: 'org', name: 'Organization'},
      api: async () => assert.fail('Reopening should not recalculate'), onReport: () => {},
    })));
    await clickWindow(container, 'Close Report preview');
    assert.doesNotMatch(container.textContent, /Calculated organization report/);
    assert.equal(document.activeElement, windowButton(container, 'Reopen report preview'));
    await clickWindow(container, 'Reopen report preview');
    assert.match(container.textContent, /Calculated organization report/);
    assert.match(container.textContent, /Estimated net benefit/);
    assert.equal(document.activeElement.getAttribute('aria-label'), 'Calculated report');
  });
});


test('public demo exposes preview only and sends no workspace credentials', async () => {
  await withDom(async (root, container) => {
    const calls = [];
    const original = globalThis.fetch;
    location.hash = '#evaluate';
    globalThis.fetch = async (url, options) => {
      calls.push([url, options]);
      if (url === '/demo/portfolio') return Response.json({ organization: {id: 'demo', name: 'Synthetic demo'}, details: [] });
      assert.equal(url, '/demo/forecasts/preview');
      return Response.json({estimates});
    };
    try {
      await act(async () => root.render(createElement(Demo)));
      assert.match(container.textContent, /Synthetic data only/);
      assert.equal(container.querySelector('input[type=password]'), null);
      await clickWindow(container, 'Continue');
      await clickWindow(container, 'Continue');
      await clickWindow(container, 'Calculate example');
      assert.match(container.textContent, /Hypothetical customer-support result/);
      const [preview] = calls.filter(([url]) => url === '/demo/forecasts/preview');
      assert.equal(preview[1].method, 'POST');
      assert.equal(new Headers(preview[1].headers).has('X-Workspace-Key'), false);
      assert.ok(calls.every(([url]) => url.startsWith('/demo/')));
    } finally {
      globalThis.fetch = original;
    }
  });
});
