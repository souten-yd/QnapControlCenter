const $ = id => document.getElementById(id);
function table(id, rows, keys) {
  const body = $(id);
  body.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const key of keys) {
      const td = document.createElement('td');
      td.textContent = String(row[key] ?? '—');
      tr.append(td);
    }
    body.append(tr);
  }
}
async function refresh() {
  try {
    const response = await fetch('/api/status', {cache:'no-store'});
    if (!response.ok) throw new Error('HTTP '+response.status);
    const {latest} = await response.json();
    $('state').textContent = latest.status === 'ok' ? '監視中' : latest.status === 'warming_up' ? '初回計測中' : '取得エラー';
    const mb = b => ((b||0)/1048576).toFixed(3);
    const kb = b => ((b||0)/1024).toFixed(1);
    table('disks', (latest.disks||[]).map(d=>({...d,read_bps:mb(d.read_bps),write_bps:mb(d.write_bps)})), ['device','read_bps','write_bps','read_iops','write_iops','busy_pct']);
    table('procs', (latest.processes||[]).map(p=>({...p,read_bps:kb(p.read_bps),write_bps:kb(p.write_bps)})), ['pid','name','read_bps','write_bps']);
    $('reads').textContent = mb((latest.disks||[]).reduce((a,d)=>a+d.read_bps,0));
    $('writes').textContent = mb((latest.disks||[]).reduce((a,d)=>a+d.write_bps,0));
    $('busy').textContent = Math.max(0,...(latest.disks||[]).map(d=>d.busy_pct)).toFixed(1);
    $('count').textContent = (latest.processes||[]).length;
  } catch(e) {$('state').textContent = '監視APIに接続できません: '+e.message;}
}
refresh(); setInterval(refresh,5000);
let selectedRelease = null;
let releaseInstallable = false;
let lanEnabled = false;
let updateBusy = false;
let updateSubmitting = false;
let updateUncertain = false;

async function updateJson(path, body) {
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET', cache:'no-store',
    headers: body ? {'Content-Type':'application/json','X-QCC-Update-Intent':'1'} : {},
    body: body ? JSON.stringify(body) : undefined
  });
  let value;
  try { value = await response.json(); }
  catch (_) { throw new Error('更新APIがJSONを返しませんでした (HTTP ' + response.status + ')'); }
  if (!response.ok || value.error) {
    const error = new Error(value.error || value.message || 'HTTP '+response.status);
    error.http = true;
    throw error;
  }
  return value;
}

function updateButton() {
  $('install-update').disabled = !(selectedRelease && releaseInstallable &&
    lanEnabled && !updateBusy && !updateSubmitting && !updateUncertain);
}

async function checkUpdate() {
  const target = $('update');
  target.textContent = 'GitHub Releasesを確認中…';
  selectedRelease = null; releaseInstallable = false;
  updateButton();
  try {
    const result = await updateJson('/api/update');
    selectedRelease = result.tag;
    releaseInstallable = Boolean(result.install_supported);
    target.replaceChildren();
    const info = document.createElement('span');
    info.textContent = result.tag
      ? '最新リリース: ' + result.tag + ' · QPKG: ' +
        ((result.qpkg || []).map(a => a.name).join(', ') || '未公開') +
        (releaseInstallable ? '' : '（更新用ファイル不足）')
      : '公開済みの更新候補がありません';
    target.append(info, document.createTextNode(' '));
    if (result.release_url && result.release_url.startsWith('https://github.com/souten-yd/QnapControlCenter/releases/')) {
      const link = document.createElement('a');
      link.href = result.release_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = 'GitHubのリリースページ';
      target.append(link);
    }
  } catch (error) { target.textContent = '更新確認に失敗: ' + error.message; }
  updateButton();
}
$('check-update').addEventListener('click', checkUpdate);

async function updateStatus() {
  try {
    const v = await updateJson('/api/update-status');
    updateBusy = Boolean(v.busy);
    updateUncertain = false;
    const phases = {idle:'待機中',queued:'受付済み',checking:'確認中',
      downloading:'ダウンロード・検証中',stopping:'旧サービス停止中',
      installing:'QPKGインストール中',verifying:'起動・バージョン検証中',
      success:'更新完了',error:'更新失敗'};
    $('update-progress').textContent = '更新状況: ' +
      (phases[v.state] || v.state || '不明') + (v.message ? ' — ' + v.message : '');
    lanEnabled = Boolean(v.lan_available);
    $('lan-update-explanation').textContent = !lanEnabled
      ? 'LAN内のNAS IPアドレスでアクセスしてください（公開接続は不可）。'
      : v.available
        ? 'LAN更新が利用できます。管理トークンは不要です。'
        : 'Web更新は利用できません: ' + (v.unsupported_reason || 'QTSの更新環境を確認してください');
    if (!v.available) lanEnabled = false;
    updateButton();
  } catch (error) {
    updateUncertain = true;
    updateButton();
    $('update-progress').textContent = '更新状態を取得できません。受付済みの可能性があるため自動で再実行しません: ' + error.message;
  }
}

$('install-update').addEventListener('click', async () => {
  const tag = selectedRelease;
  if (!tag || !releaseInstallable || !lanEnabled || updateBusy || updateSubmitting || updateUncertain) return;
  if (!confirm(tag + ' の公式QPKGで更新します。Web接続が一時的に切れます。続行しますか？')) return;
  updateSubmitting = true; updateButton();
  $('update-progress').textContent = '更新を受け付けています…';
  try {
    const prepared = await updateJson('/api/prepare-update', {tag});
    await updateJson('/api/install-update', {tag, nonce: prepared.nonce});
    $('update-progress').textContent = '更新ワーカーに受付されました。自動で進捗を確認します。';
  } catch (error) {
    updateUncertain = !error.http;
    $('update-progress').textContent = error.http
      ? '更新開始に失敗: ' + error.message
      : '更新中に接続が切れました。重複実行せず更新状態を確認します。';
  } finally {
    updateSubmitting = false; updateButton();
    // Do not assume a successful version merely because the install call returned.
    setTimeout(updateStatus, 500);
  }
});

async function refreshUpdateLog() {
  try {
    const value = await updateJson('/api/update-log');
    $('update-log').textContent = value.log || '更新ログはまだありません';
  } catch(error) {
    $('update-log').textContent = '更新ログの取得に失敗: ' + error.message;
  }
}
$('refresh-update-log').addEventListener('click', refreshUpdateLog);
$('update-log-panel').addEventListener('toggle', () => {
  if ($('update-log-panel').open) void refreshUpdateLog();
});
checkUpdate();
updateStatus();
setInterval(() => {
  void updateStatus();
  if ($('update-log-panel').open) void refreshUpdateLog();
}, 5000);

// Reset only the server-side RAM window; monitoring stays active and keeps its
// existing /proc sampling baseline. Requires the same private-LAN origin policy.
$('reset-write-log').addEventListener('click', async () => {
  if (!confirm('5分間の書き込み診断履歴を消去して、今から計測し直しますか？')) return;
  const button = $('reset-write-log');
  const status = $('reset-write-state');
  button.disabled = true;
  status.textContent = 'RAM診断履歴をリセット中…';
  try {
    const response = await fetch('/api/write-log/reset', {
      method:'POST', cache:'no-store',
      headers:{'Content-Type':'application/json','X-QCC-Write-Intent':'1'},
      body:'{}'
    });
    const data = await response.json();
    if (!response.ok || !data.reset) throw Error(data.error || 'HTTP ' + response.status);
    status.textContent = 'リセットしました。次の5秒計測から再集計します。';
    await refreshWriteLog();
  } catch (error) {
    status.textContent = 'リセットに失敗: ' + error.message;
  } finally {
    button.disabled = false;
  }
});

// Generate an AI-ready text file entirely in the browser on explicit click.
$('download-write-report').addEventListener('click', async () => {
  const button = $('download-write-report');
  const status = $('write-report-status');
  button.disabled = true;
  status.textContent = 'RAM診断の最新スナップショットを取得中…';
  try {
    const response = await fetch('/api/write-log', {cache: 'no-store'});
    if (!response.ok) throw Error('書込診断 API HTTP ' + response.status);
    const data = await response.json();
    if (!Number(data.sample_count)) {
      throw Error('正常サンプルがまだありません。数秒後に再度実行してください');
    }
    // Runtime identity is helpful metadata but must not block report export.
    let runtime = null;
    try {
      const identity = await fetch('/api/runtime', {cache: 'no-store'});
      if (identity.ok) runtime = await identity.json();
    } catch (_) { /* Report remains usable even when version endpoint fails. */ }
    const now = new Date();
    const output = window.QCCWriteReport.format(data, runtime, now);
    const blob = new Blob(['\uFEFF', output], {type: 'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = window.QCCWriteReport.fileName(now);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      status.textContent = 'ダウンロードを開始しました。AIに渡す前にファイルパス等を確認してください。';
    } finally {
      // Release the client-side Blob after the browser starts downloading.
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  } catch (error) {
    status.textContent = 'テキスト出力に失敗: ' + error.message;
  } finally {
    button.disabled = false;
  }
});

const bytesLabel = bytes => {
  const n = Number(bytes) || 0;
  if (n >= 1048576) return (n/1048576).toFixed(2) + ' MiB';
  if (n >= 1024) return (n/1024).toFixed(1) + ' KiB';
  return Math.round(n) + ' B';
};
const shortTime = value => value ? new Date(value * 1000).toLocaleTimeString('ja-JP') : '—';
async function refreshWriteLog() {
  try {
    const response = await fetch('/api/write-log', {cache:'no-store'});
    if (!response.ok) throw Error('HTTP ' + response.status);
    const data = await response.json();
    $('log-disk').textContent = bytesLabel(data.disk_write_bytes);
    $('log-process').textContent = bytesLabel(data.process_write_bytes);
    $('log-self').textContent = bytesLabel(data.monitor_write_bytes);
    $('log-cost').textContent = Number(data.collector_wall_ms || 0).toFixed(0) + ' ms';
    $('log-meta').textContent = 'RAMに保持: ' + data.sample_count + '回 / 直近' +
      data.window_seconds + '秒 · ' + shortTime(data.window_start) + ' ～ ' +
      shortTime(data.window_end) + ' · ディスク記録なし';
    const body = $('write-procs');
    body.replaceChildren();
    for (const p of data.top_processes || []) {
      const tr = document.createElement('tr');
      const pname = document.createElement('td');
      pname.textContent = p.name + ' (PID ' + p.pid + ')';
      const pkg = document.createElement('td');
      pkg.textContent = p.package_hint || '未特定';
      const count = document.createElement('td');
      count.textContent = bytesLabel(p.write_bytes);
      const detail = document.createElement('td');
      const disclosure = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = (p.file_candidates || []).length +
        '件の書込可能FD候補を表示';
      disclosure.append(summary);
      const lines = [];
      if (p.executable) lines.push('実行ファイル: ' + p.executable);
      if (p.cwd) lines.push('作業ディレクトリ: ' + p.cwd);
      if (p.candidate_observed_at)
        lines.push('候補確認時刻: ' + shortTime(p.candidate_observed_at));
      for (const path of p.file_candidates || [])
        lines.push('開かれたファイル候補: ' + path);
      const pre = document.createElement('pre');
      pre.textContent = lines.length ? lines.join('\n') : '確認できた候補なし（権限・短時間アクセス・FD調査上限）';
      disclosure.append(pre);
      detail.append(disclosure);
      tr.append(pname, pkg, count, detail);
      body.append(tr);
    }
    if (!body.childNodes.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4;
      td.textContent = '書き込みプロセスの検出待ち、または取得権限不足';
      tr.append(td); body.append(tr);
    }
    const timeline = $('write-timeline');
    timeline.replaceChildren();
    const series = data.timeline || [];
    const max = Math.max(1, ...series.map(row => row.disk_write_bytes));
    for (const point of series) {
      const item = document.createElement('div');
      item.className = 'write-interval';
      const name = document.createElement('span');
      name.textContent = shortTime(point.timestamp);
      const track = document.createElement('div');
      track.className = 'write-track';
      const bar = document.createElement('div');
      bar.className = 'write-bar';
      bar.style.width = (100 * point.disk_write_bytes / max).toFixed(1) + '%';
      track.append(bar);
      const number = document.createElement('span');
      number.textContent = bytesLabel(point.disk_write_bytes);
      item.append(name, track, number);
      timeline.append(item);
    }
    $('log-note').textContent = data.limitations + ' · ' +
      '複数の物理ディスクを合算するとRAIDで二重計上される可能性があります。' +
      ' プロセス計測の上位記録外: ' + bytesLabel(data.other_process_bytes);
  } catch(error) {
    $('log-meta').textContent = '書き込み診断に接続できません: ' + error.message;
  }
}
refreshWriteLog();
setInterval(refreshWriteLog, 15000);


// Separate 300-second READ dashboard. No extra process scan; GET the RAM cache.
function readEmptyRow(body, cols, message) {
  if (body.childNodes.length) return;
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.colSpan = cols;
  td.textContent = message;
  tr.append(td);
  body.append(tr);
}
async function refreshReadLog() {
  try {
    const response = await fetch('/api/read-log', {cache:'no-store'});
    if (!response.ok) throw Error('HTTP ' + response.status);
    const data = await response.json();
    $('read-disk').textContent = bytesLabel(data.disk_read_bytes);
    $('read-ops').textContent = Number(data.disk_read_ops || 0).toLocaleString('ja-JP') + ' 回';
    $('read-process').textContent = bytesLabel(data.process_read_bytes);
    $('read-self').textContent = bytesLabel(data.monitor_read_bytes);
    $('read-meta').textContent = 'RAMに保持: ' + data.sample_count + '回 / 直近' +
      data.window_seconds + '秒 · ' + shortTime(data.window_start) + ' ～ ' +
      shortTime(data.window_end) + ' · ディスク記録なし';

    const disks = $('read-disks');
    disks.replaceChildren();
    for (const d of data.physical_disks || []) {
      const tr = document.createElement('tr');
      for (const cellText of [d.device, bytesLabel(d.read_bytes),
        Number(d.read_ops || 0).toLocaleString('ja-JP')]) {
        const td = document.createElement('td');
        td.textContent = cellText;
        tr.append(td);
      }
      disks.append(tr);
    }
    readEmptyRow(disks, 3, '物理ディスク読み込みの取得待ち');

    const body = $('read-procs');
    body.replaceChildren();
    for (const p of data.top_processes || []) {
      const tr = document.createElement('tr');
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'プロセス情報を表示';
      const pre = document.createElement('pre');
      pre.textContent = [
        p.executable ? '実行ファイル: ' + p.executable : '',
        p.cwd ? '作業ディレクトリ: ' + p.cwd : '',
        p.candidate_observed_at ? '観測: ' + shortTime(p.candidate_observed_at) : ''
      ].filter(Boolean).join('\n') || '実行場所は特定できませんでした';
      details.append(summary, pre);
      for (const label of [p.name + ' (PID ' + p.pid + ')',
        p.package_hint || '未特定', bytesLabel(p.read_bytes)]) {
        const td = document.createElement('td');
        td.textContent = label;
        tr.append(td);
      }
      const td = document.createElement('td');
      td.append(details);
      tr.append(td);
      body.append(tr);
    }
    readEmptyRow(body, 4, '読み込みプロセスの検出待ち、または権限不足');
    const timeline = $('read-timeline');
    timeline.replaceChildren();
    const series = data.timeline || [];
    const max = Math.max(1, ...series.map(row => row.disk_read_bytes || 0));
    for (const point of series) {
      const item = document.createElement('div');
      item.className = 'write-interval';
      const when = document.createElement('span');
      when.textContent = shortTime(point.timestamp);
      const track = document.createElement('div');
      track.className = 'write-track';
      const bar = document.createElement('div');
      bar.className = 'write-bar read-bar';
      bar.style.width = (100 * Number(point.disk_read_bytes || 0) / max).toFixed(1) + '%';
      track.append(bar);
      const amount = document.createElement('span');
      amount.textContent = bytesLabel(point.disk_read_bytes) +
        ' / ' + Number(point.disk_read_ops || 0) + '回';
      item.append(when, track, amount);
      timeline.append(item);
    }
    $('read-note').textContent = data.limitations + ' · ' +
      'プロセスの読み込み量上位32件外: ' + bytesLabel(data.other_process_bytes) +
      ' · read_opsはシーク回数ではありません。';
  } catch (error) {
    $('read-meta').textContent = '読み込み診断に接続できません: ' + error.message;
  }
}
refreshReadLog();
setInterval(refreshReadLog, 15000);

$('reset-read-log').addEventListener('click', async () => {
  if (!confirm('読み込み診断のRAM履歴だけを消去して、新たに5分間計測しますか？書き込み履歴は残ります。')) return;
  const button = $('reset-read-log');
  const status = $('reset-read-state');
  button.disabled = true;
  status.textContent = 'RAM読み込み履歴をリセット中…';
  try {
    const response = await fetch('/api/read-log/reset', {
      method:'POST',cache:'no-store',
      headers:{'Content-Type':'application/json','X-QCC-Read-Intent':'1'},
      body:'{}'
    });
    const result = await response.json();
    if (!response.ok || !result.reset) throw Error(result.error || 'HTTP ' + response.status);
    status.textContent = '読み込み履歴をリセットしました。次の5秒計測から集計します。';
    await refreshReadLog();
  } catch (error) {
    status.textContent = 'リセット失敗: ' + error.message;
  } finally {
    button.disabled = false;
  }
});

$('download-read-report').addEventListener('click', async () => {
  const button = $('download-read-report'), status = $('read-report-status');
  button.disabled = true;
  status.textContent = '最新のRAM読み込み診断を取得中…';
  try {
    const response = await fetch('/api/read-log', {cache:'no-store'});
    if (!response.ok) throw Error('読込診断API HTTP ' + response.status);
    const data = await response.json();
    if (!Number(data.sample_count))
      throw Error('正常な読み込み計測がありません。数秒後に再試行してください');
    let runtime = null;
    try {
      const identity = await fetch('/api/runtime', {cache:'no-store'});
      if (identity.ok) runtime = await identity.json();
    } catch (_) { /* Export remains available without runtime metadata. */ }
    const now = new Date();
    const output = window.QCCReadReport.format(data, runtime, now);
    const blob = new Blob(['\uFEFF', output], {type:'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = window.QCCReadReport.fileName(now);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      status.textContent = '読み込み診断レポートをダウンロードしました。パス等を確認して共有してください。';
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  } catch(error) {
    status.textContent = '読み込み診断の出力失敗: ' + error.message;
  } finally {
    button.disabled = false;
  }
});

$('open-read-log').addEventListener('click', () => {
  $('read-log').scrollIntoView({behavior:'smooth',block:'start'});
  refreshReadLog();
});

async function showRunningVersion() {
  try {
    const response = await fetch('/api/runtime', {cache:'no-store'});
    if (!response.ok) throw Error('HTTP ' + response.status);
    const info = await response.json();
    const version = info.running_version || '不明';
    const commit = String(info.commit || 'local');
    const suffix = commit === 'local' ? 'local' : commit.slice(0, 12);
    $('running-version').textContent = '稼働版 ' + version + ' (' + suffix + ')';
    $('current-version').textContent = version + ' / build ' + (info.build_id || '不明');
    $('diag-state').textContent = info.features && info.features.write_diagnostics && info.features.read_diagnostics
      ? '読み書き常時計測中 / RAM保存300秒 / 稼働版 ' + version
      : 'この稼働サーバーに診断機能なし / QTS App Centerから再起動してください';
    if (!info.features || !info.features.write_diagnostics) {
      $('log-meta').textContent = 'この稼働サーバーには書込診断がありません。QTS App Centerで再起動・更新してください。';
    }
  } catch (error) {
    $('running-version').textContent = '稼働版不明';
    $('current-version').textContent = '稼働版API未対応 / サーバー再起動を確認';
    $('diag-state').textContent = '実行中のバージョンを確認できません';
  }
}
showRunningVersion();

// Keep the diagnosis entry point visible independent of narrow navigation menus.
$('open-write-log').addEventListener('click', () => {
  const section = $('write-log');
  section.scrollIntoView({behavior:'smooth',block:'start'});
  refreshWriteLog();
});


// Explicit, LAN-only fixed Container Station quiet-log maintenance.
// Never send sudo passwords, file paths, shell commands, or user-defined flags.
let lowioLatest = null;
async function lowioRefresh() {
  const state = $('lowio-status');
  const apply = $('lowio-apply');
  const restart = $('lowio-restart');
  apply.disabled = true;
  restart.disabled = true;
  try {
    const response = await fetch('/api/container-lowio', {cache: 'no-store'});
    if (!response.ok) throw Error('HTTP ' + response.status);
    const data = await response.json();
    lowioLatest = data;
    state.textContent = ({
      needs_apply: 'Container Station更新でログ抑制設定が戻っています。',
      restart_required: '設定変更済み・Container Station再起動待ち。',
      applied: 'ログ抑制の設定ファイルは適用済みです。',
      unsupported: 'このContainer Station構成は安全な自動修正の対象外です。'
    })[data.state] || data.state;
    const runtime = data.runtime || {};
    const d = runtime['docker.json'] || {};
    const sd = runtime['system-docker.json'] || {};
    $('lowio-details').textContent =
      '通常Docker: ' + (d.running ? (d.debug ? 'DEBUG有効' : 'DEBUG無効') : '稼働未検出') +
      ' · system-docker: ' + (sd.running ? (sd.debug ? 'DEBUG有効' : 'DEBUG無効') : '稼働未検出') +
      ' · ' + (data.message || '') +
      ' · 再起動操作: ' + (data.restart_available ? 'Web利用可' : 'QTS App Centerを使用');
    apply.disabled = !(data.lan_available && data.writable && data.needs_apply);
    const busy = data.restart_status && data.restart_status.state === 'running';
    restart.disabled = !(data.lan_available && data.restart_available &&
                         !data.needs_apply && data.state !== 'unsupported' && !busy);
    if (busy) $('lowio-result').textContent = data.restart_status.message || '再起動中';
    if (data.restart_status && ['complete','error'].includes(data.restart_status.state)) {
      $('lowio-result').textContent = '再起動結果: ' + data.restart_status.message;
    }
  } catch (error) {
    lowioLatest = null;
    state.textContent = '設定取得失敗: ' + error.message;
    $('lowio-details').textContent = '';
  }
}
async function lowioPost(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-QCC-Lowio-Intent': '1'},
    body: JSON.stringify(body)
  });
  let result = {};
  try { result = await response.json(); } catch (_) {}
  if (!response.ok) throw Error(result.error || 'HTTP ' + response.status);
  return result;
}
$('lowio-check').addEventListener('click', lowioRefresh);
$('lowio-apply').addEventListener('click', async () => {
  if (!lowioLatest || !lowioLatest.needs_apply) return;
  if (!confirm('Container StationのDocker DEBUGログとSupervisor INFOログを抑制します。2ファイルをバックアップし、修正します。コンテナは再起動しません。続行しますか？')) return;
  $('lowio-apply').disabled = true;
  $('lowio-result').textContent = '設定の整合性を検証しています…';
  try {
    const p = await lowioPost('/api/container-lowio/prepare', {});
    const v = await lowioPost('/api/container-lowio/apply', {
      fingerprint: p.fingerprint, nonce: p.nonce
    });
    $('lowio-result').textContent = '適用完了。バックアップ: ' + (v.backup || '変更なし') +
      '。反映にはContainer Station再起動が必要です。';
  } catch (error) {
    $('lowio-result').textContent = '適用失敗（対象を確認してください）: ' + error.message;
  } finally {
    await lowioRefresh();
  }
});
$('lowio-restart').addEventListener('click', async () => {
  if (!lowioLatest || lowioLatest.needs_apply || !lowioLatest.restart_available) return;
  if (!confirm('Container Stationを再起動します。実行中の全コンテナが停止・再起動する可能性があります。重要な処理とデータ保存を確認しましたか？')) return;
  if (!confirm('最終確認: Container Stationを今すぐ再起動しますか？')) return;
  $('lowio-restart').disabled = true;
  $('lowio-result').textContent = '再起動の準備中…';
  try {
    const prepared = await lowioPost('/api/container-lowio/prepare-restart', {});
    const result = await lowioPost('/api/container-lowio/restart', {nonce: prepared.nonce});
    $('lowio-result').textContent = result.message || '再起動を要求しました';
  } catch (error) {
    $('lowio-result').textContent = '再起動要求失敗: ' + error.message;
  } finally {
    await lowioRefresh();
  }
});
// No recurring disk reads or writes: inspect only when the user opens this feature.
lowioRefresh();
