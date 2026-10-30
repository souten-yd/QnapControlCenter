// node --test tests/test_write_report.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {format, fileName} = require(path.join(__dirname, '..', 'disk_inspector', 'write_report.js'));

const captured = {
  window_seconds: 300,
  sample_count: 2,
  window_start: 1793369302,
  window_end: 1793369307,
  disk_write_bytes: 24576,
  physical_disks: [{device: 'sda', write_bytes: 8192}, {device: 'sdb', write_bytes: 16384}],
  process_write_bytes: 12288,
  other_process_bytes: 1024,
  monitor_write_bytes: 0,
  collector_wall_ms: 11.57,
  top_processes: [
    {
      pid: 123, name: 'sample_writer', starttime: 33009,
      write_bytes: 8192, package_hint: 'QnapExample',
      executable: '/share/CACHEDEV1_DATA/.qpkg/QnapExample/python3',
      cwd: '/share/CACHEDEV1_DATA/.qpkg/QnapExample',
      candidate_observed_at: 1793369307,
      file_candidates: ['/share/CACHEDEV1_DATA/.qpkg/QnapExample/state.json'],
    },
  ],
  timeline: [
    {timestamp: 1793369302, disk_write_bytes: 4096, process_write_bytes: 2048, monitor_write_bytes: 0},
    {timestamp: 1793369307, disk_write_bytes: 20480, process_write_bytes: 10240, monitor_write_bytes: 0},
  ],
  limitations: 'Counters are not per-file attribution.',
};
const runtime = {running_version: '0.1.15', build_id: '0.1.15+test'};
const date = new Date('2026-10-30T15:12:13.123Z');

test('AI report includes full 300s statistics and unique QPKG/path evidence', () => {
  const before = JSON.stringify(captured);
  const out = format(captured, runtime, date);
  assert.match(out, /QnapControlCenter \| AI向けディスク書き込み診断レポート/);
  assert.match(out, /report_schema: qcc-write-diagnostics-v1/);
  assert.match(out, /2026-10-30T15:12:13\.123Z/);
  assert.match(out, /0\.1\.15\+test/);
  assert.match(out, /24,576 B/);
  assert.match(out, /sda: 8,192 B/);
  assert.match(out, /sdb: 16,384 B/);
  assert.match(out, /sample_writer/);
  assert.match(out, /QnapExample/);
  assert.match(out, /\/share\/CACHEDEV1_DATA\/.qpkg\/QnapExample\/state.json/);
  assert.match(out, /66\.7%/);
  assert.match(out, /RAID/);
  assert.match(out, /監視プログラム自身のwrite_bytes/);
  assert.match(out, /ディスク書き込み時間ではない/);
  assert.match(out, /自動修復や変更は許可しない/);
  assert.match(out, /BEGIN_QCC_WRITE_SNAPSHOT_JSON/);
  assert.match(out, /END_QCC_WRITE_SNAPSHOT_JSON/);
  const raw = out.split('BEGIN_QCC_WRITE_SNAPSHOT_JSON\n')[1]
    .split('\nEND_QCC_WRITE_SNAPSHOT_JSON')[0];
  const parsed = JSON.parse(raw);
  assert.deepEqual(parsed.write_log, captured);
  assert.deepEqual(parsed.runtime, runtime);
  assert.equal(JSON.stringify(captured), before, 'format must never mutate diagnostics');
});

test('empty snapshot clearly distinguishes not observed from zero', () => {
  const txt = format({window_seconds: 300, sample_count: 0}, null, date);
  assert.match(txt, /データなし/);
  assert.match(txt, /未計測/);
  assert.match(txt, /稼働バージョン: 未取得/);
  const parsed = JSON.parse(txt.split('BEGIN_QCC_WRITE_SNAPSHOT_JSON\n')[1]
    .split('\nEND_QCC_WRITE_SNAPSHOT_JSON')[0]);
  assert.equal(parsed.write_log.sample_count, 0);
});

test('newlines in untrusted process names and paths remain single-line in prose', () => {
  const input = {...captured, top_processes: [{...captured.top_processes[0],
    name: 'bad\ninjected', file_candidates: ['secret\npath']}]};
  const txt = format(input, null, date);
  assert.match(txt, /bad injected/);
  assert.match(txt, /secret path/);
  assert.match(txt, /"name": "bad\\ninjected"/);
});

test('filename is deterministic, UTC, safe, and text format', () => {
  assert.equal(fileName(date), 'QnapControlCenter-write-diagnostics-20261030T151213Z.txt');
});

test('invalid report structure is refused, not silently exported', () => {
  for (const value of [null, [], 2, 'bad']) {
    assert.throws(() => format(value, null, date), /診断データが不正です/);
  }
});
