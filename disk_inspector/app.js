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
      ' · Webからの適用は現在無効（実機検証待ち）';
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
const originalCheckUpdate=checkUpdate;
async function updateStatus(){
 try{
  const r=await fetch('/api/update-status',{cache:'no-store'});
  if(!r.ok)return;
  const v=await r.json();
  $('update-progress').textContent='更新状況: '+v.state+(v.message?' — '+v.message:'');
  $('install-update').disabled=!v.available;
 }catch(e){$('update-progress').textContent='更新状況の取得失敗';}
}
$('install-update').addEventListener('click',async()=>{
 const tag=selectedRelease;
 if(!tag){$('update-progress').textContent='先に最新版を確認してください';return;}
 if(!confirm(tag+' のQPKGをこのNASにインストールします。処理中は一時的に接続できなくなります。続行しますか？'))return;
 const token=$('update-token').value;
 if(!token){$('update-progress').textContent='管理トークンを入力してください';return;}
 $('update-progress').textContent='更新を開始しています…';
 try{
  const r=await fetch('/api/install-update',{method:'POST',headers:{'Content-Type':'application/json','X-QCC-Admin-Token':token},body:JSON.stringify({tag})});
  const v=await r.json();
  $('update-progress').textContent=r.ok?'更新を開始しました。再起動後に再接続してください。':'更新開始エラー: '+(v.error||r.status);
 }catch(e){$('update-progress').textContent='更新通信に失敗: '+e.message;}
});
setInterval(updateStatus,5000);
updateStatus();
