const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {format, fileName} = require(path.join(__dirname, '..', 'disk_inspector', 'read_report.js'));
const snapshot = {
  window_seconds: 300, sample_count: 2,
  window_start: 1793369302, window_end: 1793369307,
  disk_read_bytes: 16384, disk_read_ops: 11,
  physical_disks: [{device:'sda',read_bytes:8192,read_ops:8},
                   {device:'sdb',read_bytes:8192,read_ops:3}],
  process_read_bytes: 8192, other_process_bytes: 512,
  monitor_read_bytes: 0, collector_wall_ms: 6.7,
  top_processes: [{
    pid:111, name:'reader', starttime:220, read_bytes:7168,
    package_hint:'QnapExample',
    executable:'/share/.qpkg/QnapExample/python3',
    cwd:'/share/.qpkg/QnapExample',
    candidate_observed_at:1793369307
  }],
  timeline: [{timestamp:1793369302,disk_read_bytes:8192,disk_read_ops:5,process_read_bytes:4096},
             {timestamp:1793369307,disk_read_bytes:8192,disk_read_ops:6,process_read_bytes:4096}],
  limitations:'Page-cache and RAID cautions'
};
const now = new Date('2026-11-01T04:00:00.000Z');

test('read report has independent schema, ops, original JSON and no write confusion', () => {
  const before = JSON.stringify(snapshot);
  const out = format(snapshot, {running_version:'0.1.18'}, now);
  assert.match(out, /qcc-read-diagnostics-v1/);
  assert.match(out, /ディスク読み込み診断レポート/);
  assert.match(out, /16,384 B/);
  assert.match(out, /11/);
  assert.match(out, /シーク回数ではない/);
  assert.match(out, /\/share\/.qpkg\/QnapExample\/python3/);
  assert.match(out, /BEGIN_QCC_READ_SNAPSHOT_JSON/);
  const raw = out.split('BEGIN_QCC_READ_SNAPSHOT_JSON\n')[1]
    .split('\nEND_QCC_READ_SNAPSHOT_JSON')[0];
  assert.deepEqual(JSON.parse(raw).read_log, snapshot);
  assert.equal(JSON.stringify(snapshot), before);
});
test('empty read report is not confused with zero physical activity', () => {
  const out = format({window_seconds:300,sample_count:0},null,now);
  assert.match(out,/未計測/);
  assert.match(out,/データなし/);
});
test('malformed snapshots fail closed', () => {
  for(const value of [null, [], 2, 'bad'])
    assert.throws(()=>format(value,null,now),/読み込み診断データが不正/);
});
test('untrusted linebreaks are escaped in prose', () => {
  const out = format({...snapshot,top_processes:[{...snapshot.top_processes[0],name:'bad\nline'}]},null,now);
  assert.match(out,/bad line/);
  assert.match(out,/"name": "bad\\nline"/);
});
test('filename deterministic', () => {
  assert.equal(fileName(now), 'QnapControlCenter-read-diagnostics-20261101T040000Z.txt');
});
