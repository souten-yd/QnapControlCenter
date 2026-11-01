/* Browser-side, on-demand read diagnostic export. No NAS-side report writes. */
(function (root) {
  'use strict';
  const numeric = value => Number.isFinite(Number(value)) && Number(value) >= 0
    ? Number(value) : 0;
  const bytes = n => numeric(n).toLocaleString('en-US') + ' B';
  const clean = value => value == null || value === ''
    ? '未取得' : String(value).replace(/[\r\n\t]+/g, ' ');
  const date = ts => Number.isFinite(Number(ts)) && Number(ts) > 0
    ? new Date(Number(ts)*1000).toISOString() : '未取得';
  function format(snapshot, runtime, exportedAt) {
    if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot))
      throw new Error('読み込み診断データが不正です');
    const info = runtime && typeof runtime === 'object' && !Array.isArray(runtime) ? runtime : {};
    const created = exportedAt instanceof Date && !Number.isNaN(exportedAt.getTime())
      ? exportedAt.toISOString() : new Date().toISOString();
    const devices = Array.isArray(snapshot.physical_disks) ? snapshot.physical_disks : [];
    const processes = Array.isArray(snapshot.top_processes) ? snapshot.top_processes : [];
    const timeline = Array.isArray(snapshot.timeline) ? snapshot.timeline : [];
    const out = [
      'QnapControlCenter | AI向けディスク読み込み診断レポート',
      'report_schema: qcc-read-diagnostics-v1',
      '生成日時 (UTC): ' + created,
      '生成元: GET /api/read-log のRAMスナップショット',
      '保存先: ブラウザ側（NASに診断ファイルを書き込まない）',
      '稼働バージョン: ' + clean(info.running_version),
      'ビルドID: ' + clean(info.build_id),
      '',
      '=== 診断目的 ===',
      'HDDのシーク音の原因候補を読み込みと書き込みを区別して分析する。',
      '物理読み込み量、読み込み操作数、時系列の小さなランダムアクセスを優先評価する。',
      'read_opsは物理デバイスの読み込み操作回数でありシーク回数ではない。',
      '物理ディスクとプロセスの読み込み量は足さない。RAIDで同じ読み込みが複数ドライブに現れる場合がある。',
      'プロセスのread_bytesはカーネルI/O会計値であり、どのファイルを読んだかは証明しない。',
      'ページキャッシュによりプロセスの読み込みが物理ディスクI/Oなしで完結することがある。',
      '自動停止・設定変更は許可しない。追加調査はまず読み取り専用で行う。',
      '',
      '=== 計測範囲 ===',
      '保持上限: ' + numeric(snapshot.window_seconds) + '秒',
      'サンプル数: ' + numeric(snapshot.sample_count),
      '開始時刻: ' + date(snapshot.window_start),
      '終了時刻: ' + date(snapshot.window_end),
      '0件は未計測。5分未満なら途中経過であり、0 Bと断定しない。',
      '',
      '=== 読み込み合計 ===',
      '物理デバイス読み込み（RAIDメンバ単純合算）: ' + bytes(snapshot.disk_read_bytes),
      '物理デバイス読み込み操作数（単純合算）: ' + numeric(snapshot.disk_read_ops),
      'プロセスread_bytes合計: ' + bytes(snapshot.process_read_bytes),
      '上位32件外のプロセスread_bytes合計: ' + bytes(snapshot.other_process_bytes),
      '監視自身のread_bytes: ' + bytes(snapshot.monitor_read_bytes),
      '採取処理実行時間累計: ' + numeric(snapshot.collector_wall_ms) + ' ms',
      '',
      '=== 物理ディスク別 ==='
    ];
    if (!devices.length) out.push('データなし');
    for (const d of devices)
      out.push('- ' + clean(d.device) + ': ' + bytes(d.read_bytes) + ', ' +
        numeric(d.read_ops) + ' operations');
    out.push('', '=== 読み込みが多いプロセス ===');
    if (!processes.length) out.push('データなし');
    for (const p of processes) {
      out.push('- ' + clean(p.name) + ' (PID ' + clean(p.pid) + ', start=' +
        clean(p.starttime) + ') ' + bytes(p.read_bytes));
      out.push('  推定QPKG: ' + clean(p.package_hint));
      out.push('  実行ファイル: ' + clean(p.executable));
      out.push('  作業ディレクトリ: ' + clean(p.cwd));
      out.push('  パス候補確認時刻: ' + date(p.candidate_observed_at));
      out.push('  上記パスは読み込み対象のファイルではなくプロセス特定のヒント');
    }
    out.push('', '=== 5秒ごとの読み込み推移 ===',
      'timestamp_utc | physical_read_bytes | physical_read_operations | process_read_bytes');
    if (!timeline.length) out.push('データなし');
    for (const p of timeline) out.push(date(p.timestamp) + ' | ' +
      numeric(p.disk_read_bytes) + ' | ' + numeric(p.disk_read_ops) +
      ' | ' + numeric(p.process_read_bytes));
    out.push('', '=== 計測限界 ===', clean(snapshot.limitations),
      '機密情報を含み得るプロセス名やパスは外部送信前に確認すること。',
      '', '=== 原データJSON ===', 'BEGIN_QCC_READ_SNAPSHOT_JSON',
      JSON.stringify({report_schema: 'qcc-read-diagnostics-v1',
        exported_at_utc: created, runtime: info, read_log: snapshot}, null, 2),
      'END_QCC_READ_SNAPSHOT_JSON', '');
    return out.join('\n');
  }
  function fileName(now) {
    const d = now instanceof Date && !Number.isNaN(now.getTime()) ? now : new Date();
    return 'QnapControlCenter-read-diagnostics-' +
      d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z') + '.txt';
  }
  const api = {format, fileName};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.QCCReadReport = api;
})(typeof window !== 'undefined' ? window : globalThis);
