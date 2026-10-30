/* AI-readable, download-only report from the existing RAM snapshot.
 * Pure formatter: no server write, mutation, trace, or extra sampler.
 */
(function (root) {
  'use strict';

  const number = value => Number.isFinite(Number(value)) && Number(value) >= 0
    ? Number(value) : 0;
  const bytes = value => {
    const n = number(value);
    return n.toLocaleString('en-US', {maximumFractionDigits: 0}) +
      ' B (' + (n / 1048576).toFixed(3) + ' MiB)';
  };
  const timestamp = value => {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return '未取得';
    return new Date(n * 1000).toISOString();
  };
  const plain = value => value == null || value === ''
    ? '未取得' : String(value).replace(/[\r\n\t]+/g, ' ');
  const percent = (part, total) => number(total) > 0
    ? (number(part) / number(total) * 100).toFixed(1) + '%'
    : '算出不可';

  function format(snapshot, runtime, exportedAt) {
    if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) {
      throw new Error('書き込み診断データが不正です');
    }
    const disks = Array.isArray(snapshot.physical_disks) ? snapshot.physical_disks : [];
    const processes = Array.isArray(snapshot.top_processes) ? snapshot.top_processes : [];
    const timeline = Array.isArray(snapshot.timeline) ? snapshot.timeline : [];
    const info = runtime && typeof runtime === 'object' && !Array.isArray(runtime) ? runtime : {};
    const generated = exportedAt instanceof Date && !Number.isNaN(exportedAt.getTime())
      ? exportedAt.toISOString() : new Date().toISOString();
    const lines = [
      'QnapControlCenter | AI向けディスク書き込み診断レポート',
      'report_schema: qcc-write-diagnostics-v1',
      '生成日時 (UTC): ' + generated,
      '生成方法: ブラウザがGET /api/write-logのRAMスナップショットから生成',
      '保存先: ダウンロード先端末（NAS側にレポートファイルは作成しない）',
      '稼働バージョン: ' + plain(info.running_version),
      'ビルドID: ' + plain(info.build_id),
      '',
      '=== 目的・AIへの解析依頼 ===',
      '目的: QNAP NASのHDD/SSDへの定常的なディスク書き込みを可能な限り減らしたい。',
      '次の順に診断してください。',
      '1. 直近の主要書き込みプロセスをプロセスwrite_bytes基準で順位付けし、寄与率と推定アプリを示す。',
      '2. 物理ディスク別の量と時系列から、継続書き込み・周期的バースト・監視自身の影響を評価する。',
      '3. 各候補ファイル/実行パスについて、原因の仮説と追加確認方法を整理する。',
      '4. 書き込み削減の対策を、期待効果・副作用・データ消失リスク・元に戻す方法・検証方法とともに優先度順に提案する。',
      '5. システムの安全性と機能を優先し、根拠なしのサービス停止・DB削除・ログ全停止・RAID/SSD設定変更は提案しない。',
      '6. 測定できなかった書き込みをゼロと判断しない。RAID/キャッシュ/ジャーナル/権限不足による不一致を説明する。',
      '事前条件: 自動修復や変更は許可しない。まず読み取り専用の確認方法を提案する。',
      '',
      '=== 計測範囲 ===',
      '保持期間上限: ' + number(snapshot.window_seconds) + ' 秒（ローリングRAM）',
      '正常サンプル数: ' + number(snapshot.sample_count),
      '最初のサンプル (UTC): ' + timestamp(snapshot.window_start),
      '最後のサンプル (UTC): ' + timestamp(snapshot.window_end),
      'サンプルが0件の場合は未計測、少数の場合は5分未満の部分的な観測。',
      '',
      '=== 5分間の書き込み集計（単位: bytes） ===',
      '物理デバイス書き込みの単純合算: ' + bytes(snapshot.disk_write_bytes),
      'プロセスwrite_bytes合計: ' + bytes(snapshot.process_write_bytes),
      'ランキング上位の記録外プロセス書き込み量: ' + bytes(snapshot.other_process_bytes),
      '監視プログラム自身のwrite_bytes: ' + bytes(snapshot.monitor_write_bytes),
      '採取処理の累計実行時間: ' + number(snapshot.collector_wall_ms).toFixed(2) + ' ms（ディスク書き込み時間ではない）',
      '注意: 物理デバイスとプロセスの合計は一致するとは限らず、両者を足して総書き込み量にしない。',
      '注意: RAID構成では物理デバイスの単純合算が同一論理書き込みを重複計上し得る。',
      '',
      '=== 物理ディスク別 ==='
    ];
    if (!disks.length) lines.push('データなし（未観測または権限・デバイス認識不足）');
    for (const disk of disks) {
      lines.push('- ' + plain(disk.device) + ': ' + bytes(disk.write_bytes));
    }
    lines.push('', '=== プロセス別ランキング（process write_bytes、最大24件） ===');
    if (!processes.length) lines.push('データなし（プロセス書き込みが未観測または読み取り権限不足）');
    for (let i = 0; i < processes.length; i++) {
      const p = processes[i] || {};
      lines.push(
        (i + 1) + '. ' + plain(p.name) +
        ' | PID=' + plain(p.pid) + ' | 開始識別子=' + plain(p.starttime) +
        ' | write_bytes=' + bytes(p.write_bytes) +
        ' | 全観測プロセス合計に対する割合=' +
        percent(p.write_bytes, snapshot.process_write_bytes)
      );
      lines.push('   推定QPKG: ' + plain(p.package_hint));
      lines.push('   実行ファイル: ' + plain(p.executable));
      lines.push('   作業ディレクトリ: ' + plain(p.cwd));
      lines.push('   ファイル候補の観測日時 (UTC): ' + timestamp(p.candidate_observed_at));
      const paths = Array.isArray(p.file_candidates) ? p.file_candidates : [];
      if (!paths.length) {
        lines.push('   書き込み可能なFDのファイル候補: 未取得');
      } else {
        for (const path of paths) lines.push('   書き込み可能なFD候補: ' + plain(path));
      }
    }
    lines.push('', '=== 各サンプルの推移（時刻UTC、各値はその採取区間の差分） ===');
    lines.push('timestamp_utc | physical_disk_bytes | process_bytes | monitor_bytes');
    if (!timeline.length) lines.push('データなし');
    for (const row of timeline) {
      lines.push(timestamp(row.timestamp) + ' | ' + number(row.disk_write_bytes) +
        ' | ' + number(row.process_write_bytes) + ' | ' +
        number(row.monitor_write_bytes));
    }
    lines.push(
      '', '=== 計測限界・注意 ===',
      plain(snapshot.limitations),
      'FDファイル候補は、観測時点で書き込み可能として開かれていたパスであり、そのファイルに実際に書き込んだ証拠ではない。',
      'ファイルごとの書き込み量は取得できない。短時間のFD、権限不足プロセス、kernel/writebackの書き込みは欠け得る。',
      '計測結果は過去最大300秒の一時的な状態のみ。時間当たりの長期推計には追加の観測が必要。',
      'このファイルにはユーザー名・フォルダ名などの機微なパス情報が含まれる可能性があります。AIに提供する前に確認してください。',
      '',
      '=== 原データJSON（同一時点の取得結果。再解析用） ===',
      'BEGIN_QCC_WRITE_SNAPSHOT_JSON',
      JSON.stringify({report_schema: 'qcc-write-diagnostics-v1', exported_at_utc: generated,
        runtime: info, write_log: snapshot}, null, 2),
      'END_QCC_WRITE_SNAPSHOT_JSON',
      ''
    );
    return lines.join('\n');
  }

  function fileName(now) {
    const date = now instanceof Date && !Number.isNaN(now.getTime()) ? now : new Date();
    return 'QnapControlCenter-write-diagnostics-' +
      date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z') + '.txt';
  }

  const api = {format, fileName};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.QCCWriteReport = api;
})(typeof window !== 'undefined' ? window : globalThis);
