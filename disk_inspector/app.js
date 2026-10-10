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
    $('metrics').textContent = latest.note || '';
  } catch(e) {$('state').textContent = '監視APIに接続できません: '+e.message;}
}
refresh(); setInterval(refresh,5000);