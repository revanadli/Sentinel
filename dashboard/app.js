'use strict';

// ─────────────────────────────────────────
// CONFIG & STATE
// ─────────────────────────────────────────
const CFG = {
  MODE:           'auto',            // 'backend' | 'csv' | 'auto'
  BACKEND_URL:    '../backend/api',
  DATA_PATH:      '../',
  GEMINI_MODEL:   'gemini-3.5-flash',
  MIN_REVIEWED:   20,                // minimal kasus ditelaah sebelum precision terverifikasi dipakai
};

const S = {
  cases: [], filtered: [], results: null,
  page: 1, pageSize: 20,
  geminiKey: '', dataPath: CFG.DATA_PATH, backendUrl: CFG.BACKEND_URL,
  mode: CFG.MODE,
  chatHistory: [], activeCaseCtx: null, charts: {},
  role: 'verifikator',               // verifikator | apoteker | dokter
  maxSkor: 1,
};

// Label wilayah (kode BPS) & presentasi — bukan angka performa
const PROV = {'31':'DKI Jakarta','32':'Jawa Barat','33':'Jawa Tengah','35':'Jawa Timur','36':'Banten'};
const STATUS_LABEL = {pending:'Pending',in_review:'Ditinjau',verified_fraud:'Fraud ✓',cleared:'Bersih',escalated:'Eskalasi ⬆'};
const STATUS_ICON  = {pending:'🕐',in_review:'🔵',verified_fraud:'🔴',cleared:'✅',escalated:'⬆️'};
const POLA_LABEL   = {P1:'Drug shopping (obat sama, banyak faskes)', P2:'Kuantitas berlebih / tebus dini',
                      P3:'Layanan sama berulang', P4:'Identitas dipakai lintas wilayah', AN:'Anomali statistik (ML)'};
const PRIO = {Segera:{icon:'🔴',cls:'risk-critical'}, Tinggi:{icon:'🟠',cls:'risk-high'}, Sedang:{icon:'🟡',cls:'risk-medium'}};
const ROLE_BY_MODE = {apoteker:'Apoteker', dokter:'Dokter'};

// Metadata fitur → tampilan detail kasus (ambang dibaca dari results.json)
const FEATURE_META = [
  {key:'n_faskes_30d',      label:'Faskes berbeda (obat sama, 30 hari)', op:'>=', rule:true},
  {key:'qty_ratio',         label:'Kuantitas ÷ kebutuhan terapi',         op:'>=', rule:true, unit:'×'},
  {key:'gap_days',          label:'Interval tebus ÷ hari terapi',          op:'<=', rule:true},
  {key:'repeat_svc_60d',    label:'Kunjungan poli & diagnosis sama (60 hari)', op:'>=', rule:true},
  {key:'geo_time_conflict', label:'Pasangan kunjungan lintas provinsi ≤ 1 hari', op:'>=', rule:true},
  {key:'dx_norm_z',         label:'Z-score kunjungan vs kelompok sebaya', rule:false},
  {key:'use_vs_self',       label:'Lonjakan kuantitas vs riwayat sendiri', rule:false, unit:'×'},
];

const CHECKLIST = {
  P1: ['Cek riwayat penebusan obat yang sama di seluruh faskes (SIMRS/e-klaim).',
       'Konfirmasi ke apotek/faskes apakah resep benar-benar diterbitkan dokter.',
       'Tanyakan ke peserta alasan berobat di beberapa faskes (pindah domisili, rujukan sah).'],
  P2: ['Bandingkan kuantitas dengan dosis & durasi terapi di rekam medis.',
       'Cek apakah ada alasan klinis (misalnya dosis titrasi atau stok bepergian disetujui).',
       'Periksa interval antar penebusan terhadap hari terapi.'],
  P3: ['Bandingkan hasil pemeriksaan/diagnosis antar kunjungan: apakah ada perubahan klinis?',
       'Cek surat rujukan/indikasi medis untuk tiap kunjungan.',
       'Kemungkinan sah: kontrol terjadwal, kondisi gawat darurat, rujuk balik.'],
  P4: ['Verifikasi identitas peserta pada kunjungan di wilayah berbeda (KTP/biometrik).',
       'Cek jarak & waktu antar faskes: mungkinkah peserta hadir di keduanya?',
       'Hubungi peserta untuk memastikan kartu tidak dipinjam/disalahgunakan.'],
  AN: ['Telaah pola kunjungan peserta secara manual; belum ada rule tunggal yang terpicu.',
       'Bandingkan dengan peserta sebaya (diagnosis/usia) sebelum menyimpulkan.',
       'Jika wajar secara klinis, tandai "Flag Salah" agar ambang dapat dikalibrasi.'],
};

// ─────────────────────────────────────────
// SIDEBAR (mobile)
// ─────────────────────────────────────────
function toggleSidebar() { document.querySelector('.sidebar').classList.toggle('open'); }
document.addEventListener('click', (e) => {
  const sidebar = document.querySelector('.sidebar');
  const toggle  = document.getElementById('menu-toggle');
  if (window.innerWidth <= 960 && sidebar && !sidebar.contains(e.target) && !toggle?.contains(e.target)) {
    sidebar.classList.remove('open');
  }
});

// ─────────────────────────────────────────
// HELPER TAMPILAN
// ─────────────────────────────────────────
function humanizeAlasan(rawStr, c) {
  if (!rawStr) return [];
  const std = S.results?.hari_terapi_standar;
  return rawStr.split(';').filter(Boolean).map(a => {
    const m = a.match(/^(\w+)=(.+)$/);
    if (!m) return a;
    const [, key, val] = m;
    const num = parseFloat(val);
    switch (key) {
      case 'n_faskes_30d': return `Obat sama diambil di ${num} faskes berbeda dalam 30 hari`;
      case 'qty_ratio':    return std ? `Kuantitas ${Math.round(num*std)} unit = ${num}× kebutuhan terapi (${std} hari)` : `Kuantitas ${num}× kebutuhan terapi`;
      case 'gap_days':     return `Tebus ulang saat baru ${Math.round(num*100)}% masa terapi berjalan (terlalu cepat)`;
      case 'repeat_svc':   return `Layanan poli & diagnosis sama ${num}× dalam 60 hari`;
      case 'geo_conflict': {
        const provs = fmtProvs(c?.provinsi_terlibat);
        return `Kunjungan di wilayah berbeda (${provs}) dalam ≤ 1 hari — ${num} pasangan`;
      }
      case 'dev_dx_norm_z':    return `Jumlah kunjungan jauh di atas peserta sebaya (z=${num})`;
      case 'dev_use_vs_self':  return `Kuantitas mendadak melonjak dibanding riwayat sendiri (z=${num})`;
      case 'dev_n_faskes_30d': return `Jumlah faskes tidak lazim (z=${num})`;
      case 'dev_qty_ratio':    return `Kuantitas obat tidak lazim (z=${num})`;
      case 'dev_gap_days':     return `Interval penebusan tidak lazim (z=${num})`;
      case 'dev_repeat_svc_60d': return `Pengulangan layanan tidak lazim (z=${num})`;
      case 'dev_geo_time_conflict': return `Pola lintas wilayah tidak lazim (z=${num})`;
      default: return a;
    }
  });
}

// Ringkas daftar provinsi untuk sel tabel (lengkap ada di tooltip & detail)
function provShort(str) {
  const l = (str || '').split(';').filter(Boolean);
  if (l.length <= 2) return fmtProvs(str);
  return `${PROV[l[0]] || l[0]} +${l.length - 1} prov.`;
}

function fmtProvs(str) {
  return (str||'').split(';').filter(Boolean).map(p => PROV[p]||p).join(', ') || '—';
}

// ─────────────────────────────────────────
// INIT
// ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  const cost = document.getElementById('be-cost');
  if (cost) cost.value = localStorage.getItem('s_cost') || '';
  const hash = (location.hash || '').replace('#', '');
  if (hash && ['overview', 'alur', 'cases', 'model', 'ai'].includes(hash)) showSection(hash);
  const tbody = document.getElementById('cases-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="empty-row">⏳ Memuat data kartu kasus...</td></tr>';
  autoDetect().then(() => loadAllData());
});

async function autoDetect() {
  if (S.mode !== 'auto') return;
  try {
    const r = await fetch(`${S.backendUrl}/stats.php`, {signal: AbortSignal.timeout(2500)});
    if (r.ok && (r.headers.get('content-type') || '').includes('application/json')) {
      const d = await r.json().catch(() => null);
      if (d && d.summary) {
        S.mode = 'backend';
        const btn = document.getElementById('btn-import');
        if (btn) btn.style.display = '';
        return;
      }
    }
  } catch (_) {}
  S.mode = 'csv';
}

// ─────────────────────────────────────────
// DATA LOAD
// ─────────────────────────────────────────
async function loadAllData() {
  setStatus('Memuat...');
  try {
    if (S.mode === 'backend') await loadBackend();
    else { await loadCSV(); applyDecisionsFromStorage(); }
    S.maxSkor = Math.max(1, ...S.cases.map(c => c.skor));
    renderOverview();
    filterTable();
    renderModelSection();
    updateCtxStats();
    setText('badge-mode', `● ${S.mode === 'backend' ? 'Database' : 'CSV'} · ${S.cases.length} kasus`);
    setText('badge-ts', S.results?.run_at ? `Data: ${S.results.run_at}` : '');
    const synth = document.getElementById('synth-banner');
    if (synth) synth.style.display = S.results?.data_sintetis ? '' : 'none';
    setStatus(`✓ ${S.cases.length} kasus dimuat`);
  } catch (e) {
    setStatus('⚠ Gagal memuat – jalankan via server (python -m http.server 8080 dari folder Sentinel)');
    console.error(e);
  }
}

async function loadBackend() {
  const cr = await fetch(`${S.backendUrl}/cases.php?per_page=5000&sort=peringkat&order=asc`);
  if (!cr.ok) throw new Error('Backend error');
  S.cases   = (await cr.json()).data.map(normalizeRow);
  S.results = await fetchJSON('results.json');   // metrik model berasal dari file hasil Python
}

async function loadCSV() {
  const [csv, res] = await Promise.all([fetchCSV(), fetchJSON('results.json')]);
  S.cases   = csv.map(normalizeRow);
  S.results = res;
}

const NUM_FIELDS = ['peringkat','jumlah_kunjungan','total_biaya_tagih','potensi_kerugian','label_sintetis'];
const FLT_FIELDS = ['skor','n_faskes_30d','qty_ratio','gap_days','repeat_svc_60d','dx_norm_z','geo_time_conflict','use_vs_self'];
function normalizeRow(r) {
  const o = {...r};
  NUM_FIELDS.forEach(k => o[k] = parseInt(r[k]) || 0);
  FLT_FIELDS.forEach(k => o[k] = parseFloat(r[k]) || 0);
  o.pola        = r.pola_terdeteksi || '';
  o.prioritas   = r.prioritas || 'Sedang';
  o.role_target = r.role_target || 'Verifikator';
  o.alasan_flag = r.alasan_flag || '';
  o._status     = r.status || 'pending';
  o._catatan    = r.catatan_verif || '';
  o._by         = r.diverifikasi_oleh || '';
  o._at         = r.diverifikasi_at || '';
  o._db_id      = r.id || null;
  return o;
}

function applyRoleFilter(cases) {
  const role = ROLE_BY_MODE[S.role];
  return role ? cases.filter(c => c.role_target === role) : cases;
}

// ─────────────────────────────────────────
// KEPUTUSAN VERIFIKATOR (mode CSV: tersimpan di browser)
// ─────────────────────────────────────────
const DEC_KEY = 's_decisions';

function readDecisions() {
  try { return JSON.parse(localStorage.getItem(DEC_KEY) || '{}'); } catch (_) { return {}; }
}
function applyDecisionsFromStorage() {
  const d = readDecisions();
  S.cases.forEach(c => {
    const x = d[c.id_pseudonim];
    if (x) { c._status = x.status; c._catatan = x.catatan || ''; c._by = x.by || ''; c._at = x.at || ''; }
  });
}
function persistDecision(c) {
  const d = readDecisions();
  d[c.id_pseudonim] = {status: c._status, catatan: c._catatan, by: c._by, at: c._at};
  try { localStorage.setItem(DEC_KEY, JSON.stringify(d)); } catch (_) {}
}

function reviewStats() {
  const n = s => S.cases.filter(c => c._status === s).length;
  const fraud = n('verified_fraud'), cleared = n('cleared'), esc_ = n('escalated'), review = n('in_review');
  return {fraud, cleared, escalated: esc_, review,
          done: fraud + cleared + esc_, decided: fraud + cleared, total: S.cases.length};
}

// ─────────────────────────────────────────
// OVERVIEW
// ─────────────────────────────────────────
function renderOverview() {
  const cases = S.cases;
  if (!cases.length) return;
  const res = S.results, ops = res?.operasi;

  const cnt = f => cases.filter(f).length;
  const p1p2 = cnt(c => c.pola === 'P1' || c.pola === 'P2');
  const p3   = cnt(c => c.pola === 'P3');
  const p4   = cnt(c => c.pola === 'P4');
  const potensi = cases.reduce((s, c) => s + c.potensi_kerugian, 0);
  const biaya   = cases.reduce((s, c) => s + c.total_biaya_tagih, 0);
  const rv = reviewStats();

  setText('kpi-flagged',   cases.length.toLocaleString('id-ID'));
  setText('kpi-obat',      p1p2);
  setText('kpi-layanan',   p3);
  setText('kpi-identitas', p4);
  const nPes = res?.n_peserta;
  const budget = res?.review_budget;
  setText('kpi-sub-flagged', nPes != null
    ? `dari ${nPes.toLocaleString('id-ID')} peserta${budget ? ` · kapasitas ${(budget.pct*100).toFixed(0)}%` : ''}` : '—');
  setText('n-peserta-label', nPes != null ? nPes.toLocaleString('id-ID') : '—');
  setText('horizon-label', res?.horizon_hari ?? maxDay(cases) ?? '—');

  setText('kpi-prec-label', ops ? `Precision@${ops.k}` : 'Precision@K');
  setText('kpi-precision', ops ? pct(ops.precision) : '—');
  setText('kpi-prec-sub',  ops ? `simulasi · ${ops.lift_vs_acak}× lebih baik dari acak` : 'tidak ada data evaluasi');
  setText('kpi-recall',    ops ? pct(ops.recall) : '—');
  setText('kpi-recall-sub', ops && res ? `${ops.fraud_di_antrean} dari ${res.n_fraud_tertanam} fraud tertanam` : '—');
  setText('kpi-biaya', 'Rp ' + fmtRp(potensi));
  setText('kpi-biaya-sub', `dari total tagihan Rp ${fmtRp(biaya)}`);
  setText('kpi-progress', rv.total ? `${Math.round(rv.done / rv.total * 100)}%` : '—');
  setText('kpi-progress-sub', `${rv.fraud} fraud · ${rv.cleared} bersih · ${rv.escalated} eskalasi`);

  const byPola = p => cnt(c => c.pola === p);
  setText('m-p1', byPola('P1')); setText('m-p2', byPola('P2'));
  setText('m-p3', p3);           setText('m-p4', p4);

  renderThresholds();
  renderFairnessBanner();
  renderBreakEven();
  renderCharts();
}

function maxDay(cases) {
  let mx = null;
  cases.forEach(c => {
    const m = (c.waktu_kejadian || '').match(/(\d+)\D+(\d+)/);
    if (m) mx = Math.max(mx ?? 0, +m[2]);
  });
  return mx;
}

function renderThresholds() {
  const th = S.results?.threshold_rules;
  if (!th) return;
  const fmt = {
    n_faskes_30d:      v => `n_faskes_30d ≥ ${v}`,
    qty_ratio:         v => `qty_ratio ≥ ${v}×`,
    gap_days:          v => `gap_days ≤ ${v}`,
    repeat_svc_60d:    v => `repeat_svc_60d ≥ ${v}`,
    geo_time_conflict: v => `geo_time_conflict ≥ ${v}`,
  };
  Object.entries(fmt).forEach(([k, f]) => { if (th[k] != null) setText('th-' + k, f(th[k])); });
}

function renderFairnessBanner() {
  const f = S.results?.fairness;
  setText('fair-kronis-before', f ? pct2(f.sebelum.kronis) : '—');
  setText('fair-kronis-after',  f ? pct2(f.sesudah.kronis) : '—');
}

// Break-even: precision × potensi/kasus ≥ biaya telaah/kasus (sesuai model bisnis di proposal)
function renderBreakEven() {
  const costEl = document.getElementById('be-cost');
  const cost = costEl && costEl.value !== '' ? parseFloat(costEl.value) : null;
  if (costEl) try { localStorage.setItem('s_cost', costEl.value); } catch (_) {}

  const n = S.cases.length;
  if (!n) return;
  const rv = reviewStats();
  const live = rv.decided >= CFG.MIN_REVIEWED;
  const precision = live ? rv.fraud / rv.decided : S.results?.operasi?.precision;
  const total = S.cases.reduce((s, c) => s + c.potensi_kerugian, 0);
  const avg = total / n;

  setText('be-prec', pct(precision));
  setText('be-prec-src', live ? `terverifikasi dari ${rv.decided} keputusan` :
    `simulasi (terverifikasi aktif setelah ${CFG.MIN_REVIEWED} keputusan)`);
  setText('be-avg', 'Rp ' + fmtRp(avg));
  setText('be-be', precision != null ? 'Rp ' + fmtRp(precision * avg) : '—');
  const net = document.getElementById('be-net');
  if (cost == null || precision == null) {
    setText('be-net', '—'); setText('be-net-sub', 'isi biaya telaah per kasus');
    if (net) net.classList.remove('neg', 'pos');
  } else {
    const val = precision * total - n * cost;
    setText('be-net', (val < 0 ? '−' : '') + 'Rp ' + fmtRp(Math.abs(val)));
    setText('be-net-sub', val >= 0 ? 'telaah menguntungkan pada asumsi ini' : 'biaya telaah melebihi nilai — naikkan ambang / turunkan K');
    if (net) { net.classList.toggle('neg', val < 0); net.classList.toggle('pos', val >= 0); }
  }
}

function renderCharts() {
  const cases = S.cases;
  if (!cases.length) return;
  const cnt = f => cases.filter(f).length;
  const obat = cnt(c => c.pola === 'P1' || c.pola === 'P2');
  const lay = cnt(c => c.pola === 'P3'), ident = cnt(c => c.pola === 'P4'), an = cnt(c => c.pola === 'AN');

  mkChart('chartFraudType', 'doughnut', {
    labels: ['Obat/Alkes (P1+P2)', 'Layanan (P3)', 'Identitas (P4)', 'Anomali ML'],
    datasets: [{
      data: [obat, lay, ident, an],
      backgroundColor: ['rgba(245,158,11,.8)', 'rgba(34,211,238,.8)', 'rgba(168,85,247,.8)', 'rgba(100,116,139,.5)'],
      borderColor: ['#f59e0b', '#22d3ee', '#a855f7', '#64748b'], borderWidth: 1, hoverOffset: 6,
    }],
  }, dOpts());

  const pCount = {};
  cases.forEach(c => (c.provinsi_terlibat || '').split(';').forEach(p => { if (p) pCount[p] = (pCount[p] || 0) + 1; }));
  mkChart('chartProv', 'bar', {
    labels: Object.keys(pCount).map(k => PROV[k] || k),
    datasets: [{label: 'Kasus', data: Object.values(pCount), backgroundColor: 'rgba(99,102,241,.65)',
                borderColor: '#6366f1', borderWidth: 1, borderRadius: 5}],
  }, bOpts());

  const bucket = {};
  cases.forEach(c => {
    const m = (c.waktu_kejadian || '').match(/(\d+)/);
    if (m) { const b = Math.floor(parseInt(m[1]) / 10) * 10; bucket[b] = (bucket[b] || 0) + 1; }
  });
  const keys = Object.keys(bucket).sort((a, b) => a - b);
  mkChart('chartTimeline', 'line', {
    labels: keys.map(d => `H${d}–${+d + 9}`),
    datasets: [{label: 'Kasus', data: keys.map(d => bucket[d]), borderColor: '#6366f1',
                backgroundColor: 'rgba(99,102,241,.1)', borderWidth: 2, fill: true, tension: .4, pointRadius: 3}],
  }, lOpts('Kasus per 10 hari'));

  renderModelCharts();
}

function renderModelCharts() {
  const res = S.results;
  if (!res?.kurva) return;
  const Ks = Object.keys(res.kurva.fair).map(Number).sort((a, b) => a - b);
  const cols = {
    rules:   {label: 'Rules',          b: '#6366f1', bg: 'rgba(99,102,241,.1)'},
    iforest: {label: 'IsolationForest', b: '#22d3ee', bg: 'rgba(34,211,238,.1)'},
    fair:    {label: 'Skor Final',      b: '#f59e0b', bg: 'rgba(245,158,11,.1)'},
  };
  mkChart('chartModelPrec', 'line', {
    labels: Ks.map(k => `K=${k}`),
    datasets: Object.entries(cols).map(([n, c]) => ({
      label: c.label, data: Ks.map(k => (res.kurva[n]?.[k]?.[0] || 0) * 100),
      borderColor: c.b, backgroundColor: c.bg, borderWidth: 2, fill: false, tension: .3, pointRadius: 3,
    })),
  }, lOpts('Precision (%)'));

  const rt = res.recall_tipe || {};
  const tipe = Object.keys(rt);
  mkChart('chartRecallType', 'bar', {
    labels: tipe,
    datasets: [{label: 'Recall %', data: tipe.map(t => rt[t] * 100),
      backgroundColor: ['rgba(245,158,11,.7)', 'rgba(245,158,11,.7)', 'rgba(34,211,238,.7)', 'rgba(168,85,247,.7)'],
      borderColor: ['#f59e0b', '#f59e0b', '#22d3ee', '#a855f7'], borderWidth: 1, borderRadius: 6}],
  }, {...bOpts(), scales: {x: dkScales().x, y: {...dkScales().y, max: 100}}});
}

// ─────────────────────────────────────────
// TABEL KASUS
// ─────────────────────────────────────────
function filterTable() {
  const q      = document.getElementById('search-input').value.toLowerCase();
  const type   = document.getElementById('filter-type').value;
  const prio   = document.getElementById('filter-prio').value;
  const role   = document.getElementById('filter-role').value;
  const status = document.getElementById('filter-status').value;

  S.filtered = applyRoleFilter(S.cases).filter(c => {
    const hay = [c.id_pseudonim, c.kode_obat_fkl44, c.kode_diagnosis, c.provinsi_terlibat,
                 c.alasan_flag, c.jenis_dugaan].join(' ').toLowerCase();
    return (!q || hay.includes(q)) && (!type || c.pola === type) && (!prio || c.prioritas === prio) &&
           (!role || c.role_target === role) && (!status || c._status === status);
  });
  S.page = 1;
  renderTable();
}

function renderTable() {
  const {filtered, page, pageSize} = S;
  const start = (page - 1) * pageSize;
  const tbody = document.getElementById('cases-tbody');
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty-row"><div class="empty-ico">📋</div>
      <div class="empty-title">Tidak ada kartu kasus yang ditemukan</div>
      <div class="empty-sub">Coba reset filter pola, prioritas, role, atau kata kunci.</div>
      <button class="btn-reset" onclick="resetFilter()">↺ Reset Semua Filter</button></td></tr>`;
    setText('table-count', '0 baris');
    renderPagination();
    return;
  }
  tbody.innerHTML = filtered.slice(start, start + pageSize).map((c, i) => {
    const pr = PRIO[c.prioritas] || PRIO.Sedang;
    const alasan = humanizeAlasan(c.alasan_flag, c);
    const w = Math.min(c.skor / S.maxSkor * 100, 100).toFixed(0);
    return `<tr>
      <td class="rank">${c.peringkat}</td>
      <td><code class="idcell">${esc(c.id_pseudonim)}</code></td>
      <td><div class="jenis" title="${esc(POLA_LABEL[c.pola] || c.jenis_dugaan)}">${esc(c.jenis_dugaan)}</div>
          <span class="type-badge ${esc(c.pola)}">${esc(c.pola || '—')}</span></td>
      <td><div class="alasan-chips">
        ${alasan.slice(0, 2).map(a => `<span class="alasan-chip" title="${esc(a)}">${esc(a.length > 52 ? a.slice(0, 50) + '…' : a)}</span>`).join('')}
        ${alasan.length > 2 ? `<span class="alasan-chip more">+${alasan.length - 2} lagi</span>` : ''}
      </div></td>
      <td><span class="role-badge ${esc(c.role_target)}">${esc(c.role_target)}</span></td>
      <td class="provcell" title="${esc(fmtProvs(c.provinsi_terlibat))}">${esc(provShort(c.provinsi_terlibat))}</td>
      <td class="num">${c.jumlah_kunjungan}</td>
      <td>Rp ${fmtRp(c.potensi_kerugian)}</td>
      <td><div class="risk-badge-wrap"><span class="${pr.cls}">${pr.icon} ${esc(c.prioritas)}</span>
          <div class="score-bar"><div class="score-fill" style="width:${w}%"></div></div></div></td>
      <td><span class="status-badge ${esc(c._status)}">${STATUS_ICON[c._status] || ''} ${esc(STATUS_LABEL[c._status] || c._status)}</span></td>
      <td><button class="btn-detail" onclick="openDetail(${start + i})">Detail</button></td>
    </tr>`;
  }).join('');
  setText('table-count', `${filtered.length} baris`);
  renderPagination();
}

function renderPagination() {
  const total = Math.ceil(S.filtered.length / S.pageSize);
  const el = document.getElementById('pagination');
  if (total <= 1) { el.innerHTML = ''; return; }
  let h = '';
  for (let p = 1; p <= total; p++) {
    if (p === 1 || p === total || (p >= S.page - 2 && p <= S.page + 2)) {
      h += `<button class="page-btn ${p === S.page ? 'active' : ''}" onclick="goPage(${p})">${p}</button>`;
    } else if (p === S.page - 3 || p === S.page + 3) {
      h += '<span class="page-gap">…</span>';
    }
  }
  el.innerHTML = h;
}
function goPage(p) { S.page = p; renderTable(); }

function resetFilter() {
  ['search-input', 'filter-type', 'filter-prio', 'filter-role', 'filter-status']
    .forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
  S.role = 'verifikator';
  document.querySelectorAll('.role-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
  setText('role-indicator', '🏢 Verifikator');
  filterTable();
}

// ─────────────────────────────────────────
// DETAIL KASUS
// ─────────────────────────────────────────
function ruleHit(meta, v) {
  const th = S.results?.threshold_rules?.[meta.key];
  if (!meta.rule || th == null) return null;
  return meta.op === '>=' ? v >= th : v <= th;
}

function openDetail(idx) {
  const c = S.filtered[idx];
  if (!c) return;
  S.activeCaseCtx = c;
  const pr = PRIO[c.prioritas] || PRIO.Sedang;
  const alasan = humanizeAlasan(c.alasan_flag, c);
  const th = S.results?.threshold_rules || {};

  const featRows = FEATURE_META.map(m => {
    const v = c[m.key];
    const hit = ruleHit(m, v);
    const ambang = m.rule && th[m.key] != null ? `${m.op === '>=' ? '≥' : '≤'} ${th[m.key]}${m.unit || ''}` : 'tanpa ambang (ML)';
    return `<tr class="${hit ? 'hit' : ''}"><td>${esc(m.label)}</td><td class="num">${Number(v).toFixed(2)}${m.unit || ''}</td>
            <td>${esc(ambang)}</td><td>${hit === null ? '—' : hit ? '⚠ terpicu' : 'normal'}</td></tr>`;
  }).join('');

  const demo = S.results?.data_sintetis
    ? `<div class="detail-item detail-full demo-gt"><label>Label sintetis (hanya demo — tidak ada pada data riil)</label>
         <span>${c.label_sintetis ? `Benar fraud tertanam${c.tipe_fraud ? ' · tipe ' + esc(c.tipe_fraud) : ''}` : 'Bukan fraud tertanam (peserta normal / decoy)'}</span></div>` : '';

  const list = (CHECKLIST[c.pola] || CHECKLIST.AN).map(t => `<li>${esc(t)}</li>`).join('');

  document.getElementById('case-modal-body').innerHTML = `
    <div class="detail-grid">
      <div class="detail-item detail-full"><label>ID Peserta (pseudonim SHA-256)</label><span><code>${esc(c.id_pseudonim)}</code></span></div>
      <div class="detail-item"><label>Sub-kategori dugaan</label><span><strong>${esc(c.jenis_dugaan)}</strong></span></div>
      <div class="detail-item"><label>Pola terdeteksi</label><span><span class="type-badge ${esc(c.pola)}">${esc(c.pola || '—')}</span> ${esc(POLA_LABEL[c.pola] || '')}</span></div>
      <div class="detail-item"><label>Petugas yang ditugaskan</label><span><span class="role-badge ${esc(c.role_target)}">${esc(c.role_target)}</span></span></div>
      <div class="detail-item"><label>Prioritas · peringkat</label><span><span class="${pr.cls}">${pr.icon} ${esc(c.prioritas)}</span> · #${c.peringkat} (skor ${c.skor.toFixed(2)})</span></div>
      <div class="detail-item"><label>Periode kejadian</label><span>${esc(c.waktu_kejadian)}</span></div>
      <div class="detail-item"><label>Wilayah terlibat</label><span><strong>${esc(fmtProvs(c.provinsi_terlibat))}</strong></span></div>
      <div class="detail-item detail-full"><label>⚠️ Mengapa kasus ini muncul</label>
        <div class="reason-list">${alasan.length ? alasan.map(a => `<div class="reason">• ${esc(a)}</div>`).join('') : '<div class="reason muted">Tidak ada alasan tercatat.</div>'}</div></div>
      <div class="detail-item detail-full"><label>Nilai fitur vs ambang</label>
        <div class="table-wrap"><table class="feat-table"><thead><tr><th>Fitur</th><th>Nilai</th><th>Ambang</th><th>Status</th></tr></thead><tbody>${featRows}</tbody></table></div></div>
      <div class="detail-item"><label>Jumlah kunjungan FKRTL</label><span>${c.jumlah_kunjungan} kali</span></div>
      <div class="detail-item"><label>Potensi kerugian (estimasi)</label><span class="amt">Rp ${fmtRp(c.potensi_kerugian)}</span>
        <small>dari total tagihan Rp ${fmtRp(c.total_biaya_tagih)}</small></div>
      <div class="detail-item detail-full"><label>Faskes dikunjungi (FKL08)</label><span class="wrap">${esc(c.faskes_terlibat || '—')}</span></div>
      <div class="detail-item"><label>Obat (FKL44)</label><span>${esc(c.kode_obat_fkl44 || '—')}</span></div>
      <div class="detail-item"><label>Diagnosis ICD-10 (FKP15)</label><span>${esc(c.kode_diagnosis || '—')}</span></div>
      <div class="detail-item detail-full"><label>Checklist verifikasi sebelum menyimpulkan</label><ul class="checklist">${list}</ul></div>
      ${demo}
      <div class="detail-item detail-full"><label>Status verifikasi</label>
        <span><span class="status-badge ${esc(c._status)}">${STATUS_ICON[c._status] || ''} ${esc(STATUS_LABEL[c._status] || c._status)}</span>
        ${c._at ? `<small>· ${esc(c._by || '')} ${esc(c._at)}</small>` : ''}</span></div>
    </div>`;
  const note = document.getElementById('case-note');
  if (note) note.value = c._catatan || '';
  document.getElementById('case-modal').classList.add('open');
}

function closeCaseModal() { document.getElementById('case-modal').classList.remove('open'); }

function updateCaseStatus(newStatus, successMsg) {
  const c = S.activeCaseCtx;
  if (!c) return;
  const catatan = (document.getElementById('case-note')?.value || '').trim();
  const now = new Date().toISOString().slice(0, 16).replace('T', ' ');

  const finish = (where) => {
    c._status = newStatus; c._catatan = catatan; c._by = S.role; c._at = now;
    renderTable(); renderOverview();
    closeCaseModal();
    setStatus(`✓ ${successMsg} (tersimpan di ${where})`);
  };

  if (S.mode === 'backend' && c._db_id) {
    fetch(`${S.backendUrl}/verify.php`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: c._db_id, status: newStatus, catatan, user_name: S.role}),
    }).then(r => r.json().then(d => ({ok: r.ok, d})))
      .then(({ok, d}) => { if (ok && d.success) finish('database'); else throw new Error(d.error || 'gagal menyimpan'); })
      .catch(e => setStatus('⚠ Gagal simpan: ' + e.message));
  } else {
    finish('browser');
    persistDecision(c);
  }
}

const setPending    = () => updateCaseStatus('pending', 'Status dikembalikan ke Pending');
const flagSalah     = () => updateCaseStatus('cleared', 'Ditandai bersih (flag salah)');
const confirmFraud  = () => updateCaseStatus('verified_fraud', 'Dikonfirmasi fraud');
const escalateCase  = () => updateCaseStatus('escalated', 'Dieskalasi ke audit');

// Ekspor antrean + keputusan untuk laporan audit
function exportDecisions() {
  const cols = ['peringkat', 'id_pseudonim', 'prioritas', 'pola', 'jenis_dugaan', 'role_target',
                'potensi_kerugian', 'skor', '_status', '_catatan', '_by', '_at'];
  const head = ['peringkat', 'id_pseudonim', 'prioritas', 'pola_terdeteksi', 'jenis_dugaan', 'role_target',
                'potensi_kerugian', 'skor', 'status', 'catatan', 'ditelaah_oleh', 'waktu_telaah'];
  const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [head.join(',')].concat(S.filtered.map(c => cols.map(k => q(c[k])).join(','))).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], {type: 'text/csv;charset=utf-8'}));
  a.download = `keputusan_telaah_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ─────────────────────────────────────────
// HALAMAN PERFORMA MODEL
// ─────────────────────────────────────────
function renderModelSection() {
  const res = S.results;
  if (!res) return;
  const fa = res.fairness || {}, b = fa.sebelum || {}, a = fa.sesudah || {}, hs = res.hardstop || {};
  setText('f-recall-before', pct(b.recall));  setText('f-kronis-before', pct2(b.kronis));
  setText('f-nk-before', pct2(b.non_kronis)); setText('f-decoy-before', pct2(b.decoy_pct));
  setText('f-recall-after', pct(a.recall));   setText('f-kronis-after', pct2(a.kronis));
  setText('f-nk-after', pct2(a.non_kronis));  setText('f-decoy-after', pct2(a.decoy_pct));
  setText('hs-diblokir', (hs.diblokir || 0).toLocaleString('id-ID'));
  setText('hs-prec', pct(hs.precision));
  setText('hs-recall', pct(hs.recall));
  setText('hs-decoy', pct2(hs.decoy_diblokir_pct));
  if (hs.diblokir != null) {
    const sah = Math.round(hs.diblokir * (1 - (hs.precision || 0)));
    setText('hs-note', `Pembanding sederhana (n_faskes ≥ 2): ±${sah.toLocaleString('id-ID')} peserta sah ikut terblokir dan ${pct(1 - (hs.recall || 0))} fraud tetap lolos. Karena itu hanya ada antrean telaah — keputusan ada di manusia (Permenkes 16/2019).`);
  }

  const o = res.operasi || {};
  setText('ops-k', o.k ?? '—');
  const rt = res.recall_tipe || {};
  const acc = Object.values(res.akurasi_kategori || {}).filter(v => v != null);
  const accAvg = acc.length ? acc.reduce((s, v) => s + v, 0) / acc.length : null;
  const tile = (val, label, sub, cls = '') =>
    `<div class="feat-item metric ${cls}"><div class="metric-val">${val}</div>
     <div class="metric-lbl">${label}</div><div class="metric-sub">${sub}</div></div>`;
  document.getElementById('metrics-grid').innerHTML = [
    tile(pct(o.precision), `Precision@${o.k}`, `${o.fraud_di_antrean} benar · ${o.bukan_fraud} bukan fraud`),
    tile(pct(o.recall), `Recall@${o.k}`, `dari ${res.n_fraud_tertanam} fraud tertanam`, 'layanan'),
    tile(`${o.lift_vs_acak}×`, 'Lift vs acak', `baseline = prevalensi ${pct(res.prevalensi)}`),
    tile(res.auc?.fair?.roc ?? '—', 'ROC-AUC', 'skor final'),
    tile(res.auc?.fair?.pr ?? '—', 'PR-AUC', `acak ≈ ${res.prevalensi}`, 'identitas'),
    tile(pct(accAvg), 'Akurasi kategori', 'role tujuan sesuai pola', 'obat'),
    tile(pct2(a.decoy_pct), 'Decoy ter-flag', 'pasien sah mirip fraud'),
  ].join('');

  const worst = Object.entries(rt).sort((x, y) => x[1] - y[1])[0];
  setText('metric-note',
    `Semua angka dihitung pada data sintetis dengan pola fraud yang ditanam tim, sehingga membuktikan mesin bekerja sesuai desain — bukan akurasi pada data JKN riil.` +
    (worst ? ` Recall terendah: ${worst[0]} (${pct(worst[1])}), karena sebagian kasus sengaja dibuat borderline.` : ''));

  document.getElementById('sens-body').innerHTML = (res.sensitivitas_prevalensi || [])
    .map(r => `<tr><td>${pct(r.prevalensi)}</td><td>${pct(r.precision)}</td></tr>`).join('');
}

// ─────────────────────────────────────────
// AI CHAT
// ─────────────────────────────────────────
function updateCtxStats() {
  const o = S.results?.operasi;
  setText('ctx-total', S.cases.length);
  setText('ctx-fraud', S.results?.data_sintetis ? S.cases.filter(x => x.label_sintetis === 1).length : '—');
  setText('ctx-prec-label', o ? `Precision@${o.k}` : 'Precision@K');
  setText('ctx-prec', o ? pct(o.precision) : '—');
  setText('ctx-rec', o ? pct(o.recall) : '—');
}

function buildSysPrompt() {
  const r = S.results || {}, o = r.operasi || {}, th = r.threshold_rules || {}, rt = r.recall_tipe || {};
  return `Kamu adalah Sentinel AI, asisten investigasi fraud JKN (BPJS Kesehatan) untuk Healthkathon 2026.

Konteks sistem:
- Antrean telaah: ${S.cases.length} kasus (kapasitas ${r.review_budget ? (r.review_budget.pct * 100).toFixed(0) + '% peserta' : '—'})
- Metode: ${Object.keys(th).length} rule threshold + IsolationForest (unsupervised), skor dinormalisasi per kelompok kronis×usia
- Evaluasi (DATA SINTETIS): Precision@${o.k ?? 'K'} ${pct(o.precision)}, Recall ${pct(o.recall)}; recall per pola ${Object.entries(rt).map(([k, v]) => `${k} ${pct(v)}`).join(', ') || '—'}

Pola yang dideteksi:
1. Penyalahgunaan Obat/Alkes (P1 drug shopping, P2 kuantitas/tebus dini) → Apoteker
   Sinyal: n_faskes_30d≥${th.n_faskes_30d ?? '?'}, qty_ratio≥${th.qty_ratio ?? '?'}×, gap_days≤${th.gap_days ?? '?'}
2. Pelayanan yang Tidak Perlu (P3) → Dokter
   Sinyal: repeat_svc_60d≥${th.repeat_svc_60d ?? '?'} (poli & diagnosis sama dalam 60 hari)
3. Penyalahgunaan Identitas (P4) → Verifikator
   Sinyal: geo_time_conflict≥${th.geo_time_conflict ?? '?'} (provinsi berbeda ≤ 1 hari)
AN = anomali statistik tanpa rule tunggal.

Prinsip:
- TIDAK ada blokir otomatis; semua keputusan di tangan manusia (Permenkes 16/2019)
- Temuan adalah "perlu verifikasi", bukan "terbukti curang"
- ID peserta dipseudonimkan (SHA-256), selaras UU PDP 27/2022
- Data bersifat SINTETIS, bukan data JKN riil

Jawab Bahasa Indonesia. Singkat, spesifik, dan actionable. Selalu sebut kemungkinan alasan sah (false positive).`;
}

function sendCaseToAI() {
  closeCaseModal();
  showSection('ai');
  const c = S.activeCaseCtx;
  if (!c) return;
  const alasan = humanizeAlasan(c.alasan_flag, c).join('; ') || '—';
  document.getElementById('ai-context-box').innerHTML =
    `<strong>${esc(c.id_pseudonim)}</strong><br/>Dugaan: ${esc(c.jenis_dugaan)}<br/>Indikasi: ${esc(alasan)}<br/>` +
    `Wilayah: ${esc(fmtProvs(c.provinsi_terlibat))}<br/>Potensi: Rp ${fmtRp(c.potensi_kerugian)}`;

  const inp = document.getElementById('chat-input');
  inp.value = `Tolong bantu telaah kasus dugaan fraud JKN berikut:
• ID (pseudonim): ${c.id_pseudonim}
• Sub-kategori: ${c.jenis_dugaan} (pola ${c.pola})
• Indikasi sistem: ${alasan}
• Wilayah: ${fmtProvs(c.provinsi_terlibat)}
• Faskes (FKL08): ${c.faskes_terlibat || '—'}
• Obat (FKL44): ${c.kode_obat_fkl44 || '—'}
• Diagnosis (ICD-10): ${c.kode_diagnosis || '—'}
• Kunjungan: ${c.jumlah_kunjungan} kali · Potensi kerugian (estimasi): Rp ${fmtRp(c.potensi_kerugian)}
• Prioritas: ${c.prioritas} (peringkat ${c.peringkat})

Pertanyaan:
1. Mengapa pola ini perlu diverifikasi?
2. Checklist telaah konkret untuk ${c.role_target}?
3. Alasan sah (false positive) apa yang harus dicek lebih dulu?`;
  autoResize(inp);
}

async function sendChat() {
  const inp = document.getElementById('chat-input');
  const msg = inp.value.trim();
  if (!msg) return;
  if (S.mode !== 'backend' && !S.geminiKey) {
    addMsg('system', '⚠️ Masukkan <strong>Gemini API Key</strong> di ⚙️ Pengaturan.');
    return;
  }
  addMsg('user', esc(msg));
  inp.value = ''; autoResize(inp);
  document.getElementById('btn-send').disabled = true;
  const tid = addTyping();
  document.getElementById('ai-dot').className = 'ai-status-dot online';
  try {
    let reply;
    if (S.mode === 'backend') {
      const r = await fetch(`${S.backendUrl}/chat.php`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: msg, history: S.chatHistory}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      reply = d.reply;
    } else {
      S.chatHistory.push({role: 'user', parts: [{text: msg}]});
      const r = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${CFG.GEMINI_MODEL}:generateContent`,
        {method: 'POST', headers: {'Content-Type': 'application/json', 'x-goog-api-key': S.geminiKey},
         body: JSON.stringify({system_instruction: {parts: [{text: buildSysPrompt()}]}, contents: S.chatHistory,
           generationConfig: {temperature: .5, topK: 40, topP: .95, maxOutputTokens: 8192}})});
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.error?.message || `HTTP ${r.status}`); }
      const d = await r.json();
      reply = d.candidates?.[0]?.content?.parts?.[0]?.text || '(Tidak ada respons)';
    }
    S.chatHistory.push({role: 'model', parts: [{text: reply}]});
    rmEl(tid);
    addMsg('ai', md2html(esc(reply)));
  } catch (e) {
    rmEl(tid);
    addMsg('system', `❌ ${esc(e.message)}`);
    console.error(e);
  } finally {
    document.getElementById('btn-send').disabled = false;
    document.getElementById('ai-dot').className = 'ai-status-dot';
  }
}

function handleChatKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }
function sendSug(btn) {
  const i = document.getElementById('chat-input');
  i.value = btn.textContent; autoResize(i); sendChat();
}
function addMsg(role, html) {
  const w = document.getElementById('chat-messages');
  const d = document.createElement('div');
  d.className = `chat-msg ${role}`;
  d.innerHTML = `<div class="msg-bubble">${html}</div>`;
  w.appendChild(d); w.scrollTop = w.scrollHeight;
}
function addTyping() {
  const w = document.getElementById('chat-messages');
  const d = document.createElement('div');
  const id = 'ty-' + Date.now();
  d.id = id; d.className = 'chat-msg ai';
  d.innerHTML = '<div class="msg-bubble"><div class="typing-ind"><span></span><span></span><span></span></div></div>';
  w.appendChild(d); w.scrollTop = w.scrollHeight;
  return id;
}
function rmEl(id) { document.getElementById(id)?.remove(); }

// ─────────────────────────────────────────
// ROLE, IMPORT, NAVIGASI, PENGATURAN
// ─────────────────────────────────────────
function setRole(role, btn) {
  S.role = role;
  document.querySelectorAll('.role-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  setText('role-indicator', {verifikator: '🏢 Verifikator', apoteker: '💊 Apoteker', dokter: '🩺 Dokter'}[role]);
  filterTable();
}

async function importToDB() {
  if (S.mode !== 'backend') {
    alert('Import ke database hanya bisa saat berjalan di server XAMPP (Apache + PHP + MySQL).');
    return;
  }
  setStatus('Mengimport CSV ke database...');
  try {
    const fd = new FormData(); fd.append('use_default', '1');
    const r = await fetch(`${S.backendUrl}/import.php`, {method: 'POST', body: fd});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    setStatus(`✓ Import: ${d.imported} baris, total DB: ${d.total_db}`);
    await loadAllData();
  } catch (e) { setStatus('⚠ Import gagal: ' + e.message); }
}

function showSection(name, el) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`section-${name}`)?.classList.add('active');
  const navEl = el || document.querySelector(`.sidebar-nav .nav-item[onclick*="'${name}'"]`);
  if (navEl) navEl.classList.add('active');
  const titles = {overview: 'Overview', alur: 'Alur Sistem', cases: 'Kartu Kasus', model: 'Performa Model', ai: 'AI Investigator'};
  setText('page-title', titles[name] || name);
  try { history.replaceState(null, '', '#' + name); } catch (_) {}
  document.querySelector('.sidebar')?.classList.remove('open');
  // chart yang dibuat saat section tersembunyi perlu diukur ulang
  Object.values(S.charts).forEach(c => c?.resize());
}

function toggleSettings() {
  const m = document.getElementById('settings-modal');
  m.classList.toggle('open');
  if (m.classList.contains('open')) {
    document.getElementById('gemini-api-key').value = S.geminiKey;
    document.getElementById('data-path').value      = S.dataPath;
    document.getElementById('backend-url').value    = S.backendUrl;
  }
}

function saveSettings() {
  S.geminiKey  = document.getElementById('gemini-api-key').value.trim();
  S.dataPath   = document.getElementById('data-path').value.trim() || CFG.DATA_PATH;
  S.backendUrl = document.getElementById('backend-url').value.trim() || CFG.BACKEND_URL;
  if (!S.dataPath.endsWith('/')) S.dataPath += '/';
  localStorage.setItem('s_key', S.geminiKey);
  localStorage.setItem('s_dp',  S.dataPath);
  localStorage.setItem('s_bu',  S.backendUrl);
  toggleSettings();
  S.mode = 'auto';
  autoDetect().then(() => loadAllData());
}

function loadSettings() {
  S.geminiKey  = localStorage.getItem('s_key') || '';
  S.dataPath   = localStorage.getItem('s_dp')  || CFG.DATA_PATH;
  S.backendUrl = localStorage.getItem('s_bu')  || CFG.BACKEND_URL;
}
function toggleKey() {
  const i = document.getElementById('gemini-api-key');
  i.type = i.type === 'password' ? 'text' : 'password';
}
function closeModalOut(e, id) { if (e.target === e.currentTarget) document.getElementById(id).classList.remove('open'); }

// ─────────────────────────────────────────
// CHART HELPERS (tema terang)
// ─────────────────────────────────────────
const AXIS = '#64748b', GRID = 'rgba(15,23,42,.07)';
function dkScales() {
  return {x: {ticks: {color: AXIS, font: {size: 10}}, grid: {color: GRID}},
          y: {ticks: {color: AXIS, font: {size: 10}}, grid: {color: GRID}}};
}
function dkLegend() { return {labels: {color: '#475569', font: {size: 10}, boxWidth: 10, padding: 14}}; }
function ttip() { return {backgroundColor: '#0f172a', titleColor: '#f1f5f9', bodyColor: '#cbd5e1'}; }
function lOpts(yLabel) {
  const sc = dkScales();
  return {responsive: true, maintainAspectRatio: false, plugins: {legend: dkLegend(), tooltip: ttip()},
          scales: {x: sc.x, y: {...sc.y, title: {display: !!yLabel, text: yLabel, color: AXIS, font: {size: 10}}}}};
}
function bOpts() { return lOpts(); }
function dOpts() {
  return {responsive: true, maintainAspectRatio: false, cutout: '60%',
          plugins: {legend: {position: 'right', labels: {color: '#475569', font: {size: 10}, boxWidth: 10, padding: 10}}, tooltip: ttip()}};
}
function mkChart(id, type, data, opts) {
  S.charts[id]?.destroy();
  const el = document.getElementById(id);
  if (!el) return;
  S.charts[id] = new Chart(el, {type, data, options: opts});
}

// ─────────────────────────────────────────
// FETCH
// ─────────────────────────────────────────
async function fetchJSON(name) {
  for (const base of [...new Set([S.dataPath, CFG.DATA_PATH])]) {
    try { const r = await fetch(base + name); if (r.ok) return await r.json(); } catch (_) {}
  }
  return null;
}
async function fetchCSV() {
  for (const base of [...new Set([S.dataPath, CFG.DATA_PATH])]) {
    try {
      const r = await fetch(base + 'kartu_kasus.csv');
      if (!r.ok) continue;
      const text = await r.text();
      if (!text.includes('id_pseudonim')) continue;
      return Papa.parse(text, {header: true, skipEmptyLines: true}).data;
    } catch (_) {}
  }
  throw new Error('kartu_kasus.csv tidak dapat diunduh dari server.');
}

// ─────────────────────────────────────────
// UTILS
// ─────────────────────────────────────────
function setText(id, v) { const e = document.getElementById(id); if (e) e.textContent = v; }
function setStatus(m) { setText('data-status', m); }
function pct(v)  { return v != null && !isNaN(v) ? (v * 100).toFixed(1) + '%' : '—'; }
function pct2(v) { return v != null && !isNaN(v) ? v.toFixed(2) + '%' : '—'; }
function fmtRp(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1) + ' M';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + ' jt';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + ' rb';
  return n.toLocaleString('id-ID');
}
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function autoResize(el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 110) + 'px'; }
function md2html(md) {
  if (!md) return '';
  let h = md
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
    .replace(/^###\s(.+)/gm, '<h4 class="md-h4">$1</h4>')
    .replace(/^##\s(.+)/gm, '<h3 class="md-h3">$1</h3>')
    .replace(/^[-*]\s(.+)/gm, '<li>$1</li>')
    .replace(/^\d+\.\s(.+)/gm, '<li>$1</li>');
  h = h.replace(/((?:<li>[\s\S]*?<\/li>\s*)+)/g, '<ul class="md-ul">$1</ul>');
  return h.replace(/\n\n/g, '<div class="md-gap"></div>').replace(/\n/g, '<br/>');
}
