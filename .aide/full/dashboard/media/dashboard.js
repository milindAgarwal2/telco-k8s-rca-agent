'use strict';

const vscode = acquireVsCodeApi();
const byId = id => document.getElementById(id);
const number = value => typeof value === 'number' && Number.isFinite(value) ?
  new Intl.NumberFormat().format(value) : 'Unavailable';

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = String(content);
  return node;
}

function date(value) {
  if (!value) return 'Unavailable';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'Unavailable' : parsed.toLocaleString();
}

function card(title, value, classification, note) {
  const box = element('article', 'card');
  box.append(element('div', 'card-label', title));
  box.append(element('div', 'card-value', value));
  const bottom = element('div', 'card-bottom');
  bottom.append(element('span', 'badge ' + classification.toLowerCase(), classification));
  bottom.append(element('span', 'card-note', note));
  box.append(bottom);
  return box;
}

function renderCards(data) {
  const k = data.kiro;
  const denominator = k.coverage.denominator;
  const coverage = field => `${k.coverage[field] || 0}/${denominator} responses`;
  const latency = k.response_time_ms.average;
  const cards = [
    card('Completed responses', number(k.completed_responses), 'Observed', 'Local Kiro hooks'),
    card('Average response time', latency === null ? 'Unavailable' :
      `${(latency / 1000).toFixed(1)} s`, 'Observed', 'Submit → stop'),
    card('Input tokens', number(k.input_tokens), 'Hook', coverage('input_tokens')),
    card('Output tokens', number(k.output_tokens), 'Hook', coverage('output_tokens')),
    card('Total tokens', number(k.total_tokens), 'Hook',
      k.total_tokens === null ? 'Requires every response to report both fields' :
        'Complete input and output coverage'),
    card('Context compactions', number(k.context_compactions), 'Hook', coverage('context_compactions')),
    card('Context tokens reduced', number(k.context_tokens_reduced_observed), 'Observed',
      coverage('paired_compaction_sizes')),
    card('Log tokens avoided', number(k.aide_log_savings_estimate.tokens_avoided_estimate),
      'Estimated', `${number(k.aide_log_savings_estimate.views)} bounded views`),
    card('Reported credits', number(data.reported_credits), 'Unavailable', 'Official import not connected')
  ];
  byId('cards').replaceChildren(...cards);
}

function table(headers, rows) {
  const node = element('table');
  const head = element('thead');
  const headerRow = element('tr');
  for (const header of headers) headerRow.append(element('th', '', header));
  head.append(headerRow);
  node.append(head);
  const body = element('tbody');
  for (const values of rows) {
    const row = element('tr');
    for (const value of values) row.append(element('td', '', value));
    body.append(row);
  }
  node.append(body);
  return node;
}

function renderTrend(data) {
  const daily = Array.isArray(data.kiro.daily) ? data.kiro.daily : [];
  const chart = byId('trend');
  const detail = byId('trend-table');
  if (!daily.length) {
    chart.replaceChildren(element('p', 'empty', 'No local response activity in this period.'));
    detail.replaceChildren();
    return;
  }
  const max = Math.max(1, ...daily.map(item => item.responses || 0));
  const bars = element('div', 'bars');
  bars.setAttribute('role', 'img');
  bars.setAttribute('aria-label', 'Completed responses per UTC day; exact values are in the table below');
  for (const item of daily) {
    const column = element('div', 'bar-column');
    const bar = element('div', 'bar');
    bar.style.height = `${Math.max(3, (item.responses || 0) / max * 100)}%`;
    bar.title = `${item.date}: ${number(item.responses)} responses`;
    column.append(bar, element('span', 'bar-label', item.date.slice(5)));
    bars.append(column);
  }
  chart.replaceChildren(bars);
  detail.replaceChildren(table(
    ['UTC day', 'Responses', 'Observed input', 'Observed output', 'Time (ms)'],
    daily.map(item => [item.date, number(item.responses),
      `${number(item.observed_input_tokens)} (${item.input_token_responses}/${item.responses})`,
      `${number(item.observed_output_tokens)} (${item.output_token_responses}/${item.responses})`,
      number(item.duration_ms)])
  ));
}

function renderModels(data) {
  const usage = data.kiro.model_usage || {};
  const entries = Object.entries(usage);
  const region = byId('models');
  if (!entries.length) {
    region.replaceChildren(element('p', 'empty', 'No model observations yet.'));
    return;
  }
  const max = Math.max(1, ...entries.map(([, count]) => count));
  const list = element('div', 'model-list');
  for (const [model, count] of entries) {
    const item = element('div', 'model-item');
    const top = element('div', 'model-top');
    top.append(element('span', '', model === 'unavailable' ? 'Model unavailable' : model));
    top.append(element('strong', '', number(count)));
    const rail = element('div', 'rail');
    const fill = element('div', 'fill');
    fill.style.width = `${count / max * 100}%`;
    rail.append(fill);
    item.append(top, rail);
    list.append(item);
  }
  region.replaceChildren(list);
}

function renderOptimization(data) {
  const report = data.optimization;
  const region = byId('optimization');
  const outcome = report.measured_outcome || {};
  const lead = element('p', 'outcome', outcome.explanation || 'No optimization measurements yet.');
  const methods = Array.isArray(report.optimization_techniques) ?
    report.optimization_techniques : [];
  const rows = methods.map(method => [method.technique, number(method.attempts),
    method.estimated_tokens_avoided === null ? 'Unavailable' :
      number(method.estimated_tokens_avoided)]);
  region.replaceChildren(lead, table(['Technique', 'Attempts', 'Scoped estimate'], rows));
  region.append(element('p', 'hint',
    'Attempt counts are activity, not savings. Positive estimates apply only to selected log pages.'));
}

function renderCoverage(data) {
  const c = data.kiro.coverage;
  const region = byId('coverage');
  const fields = [
    ['Model ID', 'model'], ['Input tokens', 'input_tokens'],
    ['Output tokens', 'output_tokens'], ['Compactions', 'context_compactions'],
    ['Context before/after', 'paired_compaction_sizes'],
    ['Cache read', 'cache_read_tokens'], ['Cache write', 'cache_write_tokens']
  ];
  const list = element('div', 'coverage-list');
  for (const [name, key] of fields) {
    const item = element('div', 'coverage-item');
    const top = element('div', 'model-top');
    top.append(element('span', '', name));
    top.append(element('strong', '', `${c[key] || 0}/${c.denominator}`));
    const rail = element('div', 'rail');
    const fill = element('div', 'fill coverage-fill');
    fill.style.width = `${c.denominator ? (c[key] || 0) / c.denominator * 100 : 0}%`;
    rail.append(fill);
    item.append(top, rail);
    list.append(item);
  }
  region.replaceChildren(list, element('p', 'hint',
    'Unavailable fields are not zero usage. Kiro may omit them from hook events.'));
}

function showSnapshot(message) {
  const data = message.data;
  if (!data || !data.kiro || !data.optimization || !data.collector) return;
  byId('workspace').textContent = `${message.workspace} · local-only · ${data.kiro.period_days}-day view`;
  byId('updated').textContent = `Updated ${date(data.generated_at_utc)}`;
  const notice = byId('notice');
  notice.className = data.collector.enabled ? 'notice healthy' : 'notice warning';
  notice.textContent = data.collector.enabled ?
    `Collector active · 90-day local retention · last hook ${date(data.collector.last_observed_hook_utc)}` :
    'Collector disabled by local policy. Existing observations remain readable.';
  renderCards(data);
  renderTrend(data);
  renderModels(data);
  renderOptimization(data);
  renderCoverage(data);
  byId('source').textContent =
    `Source: workspace hooks and AIDE SQLite · project ${data.kiro.project_id}`;
}

function showDoctor(message) {
  const panel = byId('doctor-panel');
  const details = byId('doctor-details');
  const button = byId('doctor');
  const repair = byId('repair');
  panel.hidden = false;
  button.disabled = false;
  if (message.type === 'doctorRunning') {
    button.disabled = true;
    repair.hidden = true;
    byId('doctor-status').textContent = 'RUNNING';
    details.replaceChildren(element('p', 'hint', 'Checking the local collector and dashboard reader…'));
    return;
  }
  const doctor = message.doctor;
  const reader = message.reader;
  const overall = reader && reader.status === 'FAIL' ? 'WARN' : message.status;
  byId('doctor-status').textContent = overall;
  const rows = [];
  if (doctor) {
    rows.push(['Collector doctor', doctor.status]);
    rows.push(['Database integrity', doctor.database_integrity || 'Unavailable']);
    rows.push(['Metrics enabled', doctor.kiro_metrics_enabled === undefined ?
      'Unavailable' : String(doctor.kiro_metrics_enabled)]);
    rows.push(['Retention', doctor.retention_days === undefined ?
      'Unavailable' : `${doctor.retention_days} days`]);
    rows.push(['State path', doctor.state_path || 'Unavailable']);
  }
  if (reader) rows.push(['Dashboard reader', reader.status]);
  const note = reader && reader.message ? reader.message : message.message;
  const children = [];
  if (rows.length) children.push(table(['Check', 'Result'], rows));
  if (note) children.push(element('p', 'doctor-note', note));
  if (doctor && doctor.status === 'FAIL') {
    children.push(element('p', 'doctor-note',
      'The collector reported a failed integrity check. Review the local state before retrying.'));
  }
  details.replaceChildren(...children);
  repair.hidden = false;
}

byId('refresh').addEventListener('click', () => vscode.postMessage({
  type: 'refresh', days: Number(byId('period').value)
}));
byId('period').addEventListener('change', () => vscode.postMessage({
  type: 'refresh', days: Number(byId('period').value)
}));
byId('doctor').addEventListener('click', () => vscode.postMessage({ type: 'doctor' }));
byId('repair').addEventListener('click', () => vscode.postMessage({ type: 'repair' }));
window.addEventListener('message', event => {
  const message = event.data;
  if (!message || typeof message !== 'object') return;
  if (message.type === 'snapshot') showSnapshot(message);
  if (message.type === 'doctorRunning' || message.type === 'doctorResult') showDoctor(message);
  if (message.type === 'repairResult' && typeof message.message === 'string') {
    byId('doctor-details').append(element('p', 'doctor-note', message.message));
  }
  if (message.type === 'error' && typeof message.message === 'string') {
    const notice = byId('notice');
    notice.className = 'notice warning';
    notice.textContent = `Data is stale: ${message.message}`;
  }
});
vscode.postMessage({ type: 'ready' });
