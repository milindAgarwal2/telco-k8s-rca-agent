'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const { execFile, spawn } = require('child_process');

const PERIODS = new Set([7, 30, 90]);
const REFRESH_MS = 10000;
let activePanel;

function within(parent, child) {
  const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(child));
  return relative !== '..' && !relative.startsWith('..' + path.sep) &&
    !path.isAbsolute(relative);
}

function runtimeFor(root) {
  const runtime = path.join(root, '.aide', 'full', 'mcp-servers', 'aide-token-saver');
  const python = path.join(runtime, '.venv', process.platform === 'win32' ?
    'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python');
  if (!fs.existsSync(runtime) || !within(root, runtime)) {
    throw new Error('Full AIDE metrics runtime is not installed in this workspace.');
  }
  if (!fs.existsSync(python) || !within(runtime, python)) {
    throw new Error('AIDE metrics environment is missing. Run Full installation verification.');
  }
  return { runtime, python };
}

function managerSupportsRepair(manager) {
  try {
    const label = fs.readFileSync(path.join(path.dirname(manager), 'baseline',
      'VERSION'), 'utf8').trim();
    const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(label);
    if (!match) return false;
    const [major, minor, patch] = match.slice(1).map(Number);
    return major > 0 || minor > 16 || (minor === 16 && patch >= 6);
  } catch (_) {
    return false;
  }
}

function runCollector(root, command, args = []) {
  const { runtime, python } = runtimeFor(root);
  const commandArgs = ['-I', '-X', 'utf8', '-m', 'aide_token_saver.cli', command,
    '--workspace', root, ...args];
  const env = {
    ...process.env,
    AIDE_TOKEN_SAVER_POLICY: path.join(runtime, 'policy.json'),
    AIDE_TOKEN_SAVER_STATE_DIR: path.join(root, '.aide', 'local', 'token-saver')
  };
  return new Promise((resolve, reject) => {
    execFile(python, commandArgs, {
      cwd: root, env, windowsHide: true, timeout: 15000,
      maxBuffer: 1024 * 1024, encoding: 'utf8'
    }, (error, stdout, stderr) => {
      if (error && !stdout.trim()) {
        if (command === 'dashboard-data' &&
            /No such command ['"]?dashboard-data/i.test(stderr)) {
          reject(new Error('This Full AIDE runtime predates the dashboard reader. Update the Full overlay and rerun installation verification.'));
          return;
        }
        reject(new Error(error.killed ? 'The local collector timed out.' :
          `The local collector could not run ${command}. Check its runtime with Run doctor.`));
        return;
      }
      try {
        const value = JSON.parse(stdout);
        resolve({ value, exitCode: error ? error.code : 0 });
      } catch (_) {
        reject(new Error(`The local collector returned an invalid ${command} result.`));
      }
    });
  });
}

async function readSnapshot(root, days) {
  if (!PERIODS.has(days)) throw new Error('Unsupported reporting period.');
  const { value, exitCode } = await runCollector(root, 'dashboard-data',
    ['--days', String(days)]);
  if (exitCode !== 0 || value.schema_version !== '1.0' ||
      !value.kiro || !value.optimization) {
    throw new Error('The local metrics collector returned an incompatible dashboard snapshot.');
  }
  return value;
}

async function readDoctor(root) {
  const { value, exitCode } = await runCollector(root, 'doctor');
  if (!value || typeof value !== 'object' ||
      !['PASS', 'FAIL'].includes(value.status)) {
    throw new Error('The local metrics collector returned an invalid doctor result.');
  }
  return { ...value, status: exitCode === 0 ? value.status : 'FAIL' };
}

async function selectWorkspace() {
  const folders = (vscode.workspace.workspaceFolders || []).filter(folder =>
    fs.existsSync(path.join(folder.uri.fsPath, '.aide', 'full', 'mcp-servers',
      'aide-token-saver')) ||
    fs.existsSync(path.join(folder.uri.fsPath, '.aide', 'local', 'token-saver')));
  if (folders.length === 0) {
    vscode.window.showInformationMessage('Open an AIDE workspace to view or repair metrics.');
    return undefined;
  }
  if (folders.length === 1) return folders[0];
  const selected = await vscode.window.showQuickPick(
    folders.map(folder => ({ label: folder.name, description: folder.uri.fsPath, folder })),
    { placeHolder: 'Select the AIDE workspace to inspect' }
  );
  return selected && selected.folder;
}

function html(webview, extensionUri) {
  const media = vscode.Uri.joinPath(extensionUri, 'media');
  const css = webview.asWebviewUri(vscode.Uri.joinPath(media, 'dashboard.css'));
  const js = webview.asWebviewUri(vscode.Uri.joinPath(media, 'dashboard.js'));
  return `<!doctype html><html lang="en"><head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src ${webview.cspSource}; img-src ${webview.cspSource};">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>BOS AIDE Metrics</title><link rel="stylesheet" href="${css}">
    </head><body>
    <main class="shell">
      <header class="hero">
        <div><div class="eyebrow">MACS BOS AIDE · DEVELOPER INTELLIGENCE</div>
          <h1>Workspace metrics</h1><p id="workspace">Loading local observations…</p></div>
        <div class="controls"><label for="period">Period</label>
          <select id="period" aria-label="Reporting period"><option value="7">7 days</option>
          <option value="30" selected>30 days</option><option value="90">90 days</option></select>
          <button id="refresh" type="button">Refresh</button>
          <button id="doctor" class="secondary" type="button">Run doctor</button></div>
      </header>
      <div id="notice" class="notice" role="status" aria-live="polite">Connecting to local collector…</div>
      <section id="doctor-panel" class="doctor-panel" aria-label="Collector diagnostics" hidden>
        <div class="section-title"><h2>Collector diagnostics</h2><span id="doctor-status"></span></div>
        <div id="doctor-details" class="doctor-details"></div>
        <button id="repair" class="secondary" type="button" hidden>Repair metrics</button>
      </section>
      <section aria-label="Overview" class="overview">
        <div class="section-title"><h2>At a glance</h2><span id="updated"></span></div>
        <div id="cards" class="cards"></div>
      </section>
      <div class="columns">
        <section class="panel" aria-label="Local activity trend"><h2>Local activity</h2>
          <p class="hint">Observed completed responses by UTC day</p>
          <div id="trend" class="chart"></div><div id="trend-table" class="table-wrap"></div></section>
        <section class="panel" aria-label="Models"><h2>Models used</h2>
          <p class="hint">Hook-supplied model IDs, with unknown coverage shown</p>
          <div id="models"></div></section>
      </div>
      <div class="columns">
        <section class="panel" aria-label="Optimization"><h2>Optimization activity</h2>
          <div id="optimization"></div></section>
        <section class="panel" aria-label="Coverage"><h2>Measurement coverage</h2>
          <div id="coverage"></div></section>
      </div>
      <footer><span id="source"></span><p>Provider-wide token savings and credits remain unavailable without an authoritative source. Estimates cover selected AIDE log pages only.</p></footer>
    </main><script src="${js}"></script></body></html>`;
}

async function openDashboard(context) {
  if (activePanel) {
    activePanel.reveal();
    return;
  }
  const folder = await selectWorkspace();
  if (!folder) return;
  const root = folder.uri.fsPath;
  const media = vscode.Uri.joinPath(context.extensionUri, 'media');
  const panel = vscode.window.createWebviewPanel(
    'bosAideMetrics', 'BOS AIDE · Metrics', vscode.ViewColumn.One,
    { enableScripts: true, localResourceRoots: [media], retainContextWhenHidden: true }
  );
  activePanel = panel;
  panel.webview.html = html(panel.webview, context.extensionUri);
  let days = 30;
  let reading = false;
  let doctorRunning = false;
  let repairRunning = false;
  let disposed = false;
  async function refresh() {
    if (reading || disposed || !panel.visible) return;
    if (!vscode.workspace.isTrusted) {
      panel.webview.postMessage({ type: 'error', message: 'Trust this workspace before running its local AIDE metrics runtime.' });
      return;
    }
    reading = true;
    try {
      const data = await readSnapshot(root, days);
      if (!disposed) panel.webview.postMessage({ type: 'snapshot', workspace: folder.name, data });
    } catch (error) {
      if (!disposed) panel.webview.postMessage({ type: 'error', message: error.message });
    } finally {
      reading = false;
    }
  }
  async function diagnose() {
    if (doctorRunning || disposed) return;
    if (!vscode.workspace.isTrusted) {
      panel.webview.postMessage({ type: 'doctorResult', status: 'ERROR',
        message: 'Trust this workspace before running its local AIDE metrics runtime.' });
      return;
    }
    doctorRunning = true;
    panel.webview.postMessage({ type: 'doctorRunning' });
    try {
      const doctor = await readDoctor(root);
      let reader = { status: 'NOT RUN' };
      if (doctor.status === 'PASS') {
        try {
          const data = await readSnapshot(root, days);
          reader = { status: 'PASS' };
          if (!disposed) panel.webview.postMessage({ type: 'snapshot',
            workspace: folder.name, data });
        } catch (error) {
          reader = { status: 'FAIL', message: error.message };
        }
      }
      if (!disposed) panel.webview.postMessage({ type: 'doctorResult',
        status: doctor.status, doctor, reader });
    } catch (error) {
      if (!disposed) panel.webview.postMessage({ type: 'doctorResult',
        status: 'ERROR', message: error.message });
    } finally {
      doctorRunning = false;
    }
  }
  async function repair() {
    if (repairRunning || disposed) return;
    if (!vscode.workspace.isTrusted) {
      panel.webview.postMessage({ type: 'repairResult',
        message: 'Trust this workspace before starting metrics repair.' });
      return;
    }
    repairRunning = true;
    const manager = path.join(process.env.LOCALAPPDATA || '', 'Programs',
      'MACS BOS AIDE', 'MACSBOSAIDE.exe');
    if (!process.env.LOCALAPPDATA || !fs.existsSync(manager)) {
      panel.webview.postMessage({ type: 'repairResult',
        message: 'Install MACS BOS AIDE Configuration Manager, then run Repair metrics again.' });
      repairRunning = false;
      return;
    }
    if (!managerSupportsRepair(manager)) {
      panel.webview.postMessage({ type: 'repairResult',
        message: 'Update MACS BOS AIDE Configuration Manager to version 0.16.6 or newer, then run Repair metrics again.' });
      repairRunning = false;
      return;
    }
    try {
      const child = await new Promise((resolve, reject) => {
        const process = spawn(manager, ['--repair-metrics', '--target', root], {
          cwd: path.dirname(manager), detached: true, stdio: 'ignore',
          windowsHide: false, shell: false
        });
        process.once('spawn', () => resolve(process));
        process.once('error', reject);
      });
      child.unref();
      if (!disposed) panel.webview.postMessage({ type: 'repairResult',
        message: 'Configuration Manager opened for this workspace. Close Kiro before Apply, then preview and apply the Full repair. Reopen Kiro when verification finishes.' });
    } catch (error) {
      if (!disposed) panel.webview.postMessage({ type: 'repairResult',
        message: `Could not open Configuration Manager: ${error.message}` });
    } finally {
      repairRunning = false;
    }
  }
  const receiver = panel.webview.onDidReceiveMessage(message => {
    if (!message || typeof message !== 'object') return;
    if (message.type === 'ready') refresh();
    if (message.type === 'refresh' && PERIODS.has(message.days)) {
      days = message.days;
      refresh();
    }
    if (message.type === 'doctor') diagnose();
    if (message.type === 'repair') repair();
  });
  const viewListener = panel.onDidChangeViewState(() => { if (panel.visible) refresh(); });
  const timer = setInterval(refresh, REFRESH_MS);
  panel.onDidDispose(() => {
    disposed = true;
    clearInterval(timer);
    receiver.dispose();
    viewListener.dispose();
    activePanel = undefined;
  });
}

function activate(context) {
  context.subscriptions.push(vscode.commands.registerCommand(
    'bosAide.openDashboard', () => openDashboard(context)
  ));
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.text = '$(graph) BOS AIDE Metrics';
  status.tooltip = 'Open the workspace-local BOS AIDE metrics dashboard';
  status.command = 'bosAide.openDashboard';
  const updateStatus = () => {
    const available = (vscode.workspace.workspaceFolders || []).some(folder =>
      fs.existsSync(path.join(folder.uri.fsPath, '.aide', 'full', 'mcp-servers',
        'aide-token-saver')) ||
      fs.existsSync(path.join(folder.uri.fsPath, '.aide', 'local', 'token-saver')));
    if (available) status.show(); else status.hide();
  };
  updateStatus();
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(updateStatus));
  context.subscriptions.push(status);
}

function deactivate() {}

module.exports = { activate, deactivate };
