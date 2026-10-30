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
async function checkUpdate() {
  const target = $('update');
  target.textContent = 'GitHub Releasesを確認中…';
  try {
    const response = await fetch('/api/update', {cache:'no-store'});
    if (!response.ok) throw Error('HTTP '+response.status);
    const result = await response.json();
    if (result.error) throw Error(result.message);
    selectedRelease=result.tag;
    target.replaceChildren();
    const info = document.createElement('span');
    info.textContent = '最新リリース: ' + result.tag + ' · QPKG: ' +
      (result.qpkg.length ? result.qpkg.map(a => a.name).join(', ') : '未公開') +
      ' · インストール可否は下記の更新状態で確認';
    target.append(info, document.createTextNode(' '));
    if (result.release_url && result.release_url.startsWith('https://github.com/souten-yd/QnapControlCenter/releases/')) {
      const link = document.createElement('a');
      link.href = result.release_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = 'GitHubのリリースページ';
      target.append(link);
    }
  } catch (error) { target.textContent = '更新確認に失敗: ' + error.message; }
}
$('check-update').addEventListener('click', checkUpdate);
checkUpdate();

let selectedRelease=null;
let lanEnabled=false;
const originalCheckUpdate=checkUpdate;
async function updateStatus(){
 try{
  const r=await fetch('/api/update-status',{cache:'no-store'});
  if(!r.ok)return;
  const v=await r.json();
  $('update-progress').textContent='更新状況: '+v.state+(v.message?' — '+v.message:'');
  lanEnabled=Boolean(v.lan_available);
  $('manual-token').hidden=lanEnabled;
  $('install-update').disabled=!v.available;
  if(!v.available){$('update-progress').textContent='Web更新は利用できません: QTSインストーラー（qpkg_cli）または更新権限を確認してください';}
 }catch(e){$('update-progress').textContent='更新状況の取得失敗';}
}
$('install-update').addEventListener('click',async()=>{
 const tag=selectedRelease;
 if(!tag){$('update-progress').textContent='先に最新版を確認してください';return;}
 if(!confirm(tag+' のQPKGをこのNASにインストールします。処理中は一時的に接続できなくなります。続行しますか？'))return;
 const token=lanEnabled?'':$('update-token').value;
 if(!lanEnabled&&!token){$('update-progress').textContent='管理トークンを入力してください';return;}
 $('update-progress').textContent='更新を開始しています…';
 try{
  const headers={'Content-Type':'application/json'};
  let args={tag};
  if(lanEnabled){
    headers['X-QCC-Update-Intent']='1';
    const prepared=await fetch('/api/prepare-update',{
      method:'POST',headers,body:JSON.stringify({tag})
    });
    const p=await prepared.json();
    if(!prepared.ok)throw new Error(p.error||'更新準備エラー: '+prepared.status);
    args={tag,nonce:p.nonce};
  }else{
    headers['X-QCC-Admin-Token']=token;
  }
  const r=await fetch('/api/install-update',{method:'POST',headers,body:JSON.stringify(args)});
  const v=await r.json();
  $('update-progress').textContent=r.ok?'更新を開始しました。再起動後に再接続してください。':'更新開始エラー: '+(v.error||r.status);
 }catch(e){$('update-progress').textContent='更新通信に失敗: '+e.message;}
});
setInterval(updateStatus,5000);
updateStatus();

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
    $('diag-state').textContent = info.features && info.features.write_diagnostics
      ? '常時計測中 / RAM保存300秒 / 稼働版 ' + version
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
