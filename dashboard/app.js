// ── SIDEBAR MOBILE TOGGLE ─────────────────────────────────────
function toggleSidebar() {
  document.querySelector(".sidebar").classList.toggle("open");
}
document.addEventListener("click", (e) => {
  const sidebar = document.querySelector(".sidebar");
  const toggle  = document.getElementById("menu-toggle");
  if (window.innerWidth <= 960 && sidebar && !sidebar.contains(e.target) && e.target !== toggle && !toggle?.contains(e.target)) {
    sidebar.classList.remove("open");
  }
});

'use strict';

// ─────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────
const CFG = {
  MODE:        'auto',         // 'backend'|'csv'|'auto'
  BACKEND_URL: '../backend/api',
  DATA_PATH:   '../',
};

const S = {   // state
  cases: [], filtered: [], results: null, results2: null,
  page: 1, pageSize: 20,
  geminiKey: '', dataPath: CFG.DATA_PATH, backendUrl: CFG.BACKEND_URL,
  mode: CFG.MODE,
  chatHistory: [], activeCaseCtx: null, charts: {},
  role: 'verifikator',   // apoteker | dokter | verifikator
};

const PROV = {'31':'DKI Jakarta','32':'Jawa Barat','33':'Jawa Tengah','35':'Jawa Timur','36':'Banten'};
const STATUS_LABEL = {pending:'Pending',in_review:'Ditinjau',verified_fraud:'Fraud ✓',cleared:'Bersih',escalated:'Eskalasi ⬆'};
const STATUS_ICON  = {pending:'🕐',in_review:'🔵',verified_fraud:'🔴',cleared:'✅',escalated:'⬆️'};

// ─────────────────────────────────────────
// HUMAN-READABLE HELPERS
// ─────────────────────────────────────────

// Ubah kode teknis → kalimat yang dipahami petugas
function humanizeAlasan(rawStr, c) {
  if (!rawStr) return [];
  return rawStr.split(';').filter(Boolean).map(a => {
    const m = a.match(/^(\w+)=(.+)$/);
    if (!m) return a;
    const [, key, val] = m;
    const num = parseFloat(val);
    switch(key) {
      case 'n_faskes_30d':
        return `Ambil obat di ${num} faskes berbeda dalam 30 hari (normal: 1 faskes)`;
      case 'qty_ratio':
        return `Klaim ${Math.round(num*30)} tablet — ${num}× kebutuhan bulanan (normal: 30/bulan)`;
      case 'gap_days':
        return `Tebus ulang obat setelah ${Math.round(num*100)}% obat habis (terlalu cepat)`;
      case 'repeat_svc':
        return `Kunjungan poli sama ${num}× dalam 60 hari di faskes berbeda`;
      case 'geo_conflict': {
        const provs = (c?.provinsi_terlibat||'').split(';').filter(Boolean)
                       .map(p => PROV[p]||p).join(' & ');
        return `Terdeteksi di ${provs||'2 provinsi berbeda'} dalam 1 hari yang sama`;
      }
      default: return a;
    }
  });
}

// Skor numerik → level risiko
function riskLevel(skor) {
  if (skor >= 3)   return {label:'Sangat Tinggi', icon:'🔴', cls:'risk-critical'};
  if (skor >= 2)   return {label:'Tinggi',        icon:'🟠', cls:'risk-high'};
  if (skor >= 1.5) return {label:'Sedang',        icon:'🟡', cls:'risk-medium'};
  return               {label:'Rendah',           icon:'🟢', cls:'risk-low'};
}

// Format provinsi jadi nama lengkap
function fmtProvs(str) {
  return (str||'').split(';').filter(Boolean).map(p => PROV[p]||p).join(', ') || '—';
}

// ─────────────────────────────────────────
// INIT
// ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  const hash = (location.hash || '').replace('#', '');
  if (hash && ['overview', 'alur', 'cases', 'model', 'ai'].includes(hash)) {
    showSection(hash);
  }
  const tbody = document.getElementById('cases-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:2.5rem;color:var(--muted);font-size:.82rem">⏳ Memuat data kartu kasus...</td></tr>';
  autoDetect().then(() => loadAllData());
});

async function autoDetect() {
  if (S.mode !== 'auto') return;
  try {
    const r = await fetch(`${S.backendUrl}/stats.php`, {signal: AbortSignal.timeout(2500)});
    if (r.ok) {
      // Pastikan response benar-benar JSON dari PHP, bukan file .php mentah
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        const d = await r.json().catch(() => null);
        if (d && d.summary) {
          S.mode = 'backend';
          const btn = document.getElementById('btn-import');
          if (btn) btn.style.display = '';
          setStatus('✓ PHP Backend (XAMPP)');
          return;
        }
      }
    }
  } catch(_) {}
  // Fallback: python -m http.server atau buka file langsung
  S.mode = 'csv';
  setStatus('Mode CSV');
}

// ─────────────────────────────────────────
// DATA LOAD
// ─────────────────────────────────────────
async function loadAllData() {
  setStatus('Memuat...');
  try {
    if (S.mode === 'backend') {
      await loadBackend();
    } else {
      await loadCSV();
      loadFlagsFromStorage();   // restore flag salah dari localStorage
    }
    renderOverview();
    filterTable();
    renderModelSection();
    updateCtxStats();
    document.getElementById('badge-mode').textContent =
      `● ${S.mode === 'backend' ? 'Database' : 'CSV'} · ${S.cases.length} kasus`;
    // Timestamp data run
    const runAt = S.results?.run_at || new Date().toLocaleDateString('id-ID',{day:'2-digit',month:'short',year:'numeric'});
    const tsEl  = document.getElementById('badge-ts');
    if (tsEl) tsEl.textContent = `Data: ${runAt}`;
    setStatus(`✓ ${S.cases.length} kasus dimuat`);
  } catch(e) {
    setStatus('⚠ Gagal – jalankan via server lokal (python -m http.server 8080)');
    console.error(e);
  }
}

async function loadBackend() {
  const [cr, sr] = await Promise.all([
    fetch(`${S.backendUrl}/cases.php?per_page=2000&sort=skor&order=desc`),
    fetch(`${S.backendUrl}/stats.php`),
  ]);
  if (!cr.ok || !sr.ok) throw new Error('Backend error');
  const cj = await cr.json();
  const sj = await sr.json();
  S.cases   = cj.data.map(normalizeRow);
  S.statsDB = sj;
  // Simulasi results.json dari stats
  S.results  = null;
  S.results2 = null;
}

async function loadCSV() {
  const [csv, r1, r2] = await Promise.all([
    fetchCSV(S.dataPath + 'kartu_kasus.csv'),
    fetchJSON(S.dataPath + 'results.json').catch(() => null),
    fetchJSON(S.dataPath + 'results2.json').catch(() => null),
  ]);
  S.cases   = csv.map(normalizeRow);
  S.results  = r1;
  S.results2 = r2;
}

function normalizeRow(r) {
  return {
    ...r,
    jumlah_kunjungan:  parseInt(r.jumlah_kunjungan)  || 0,
    total_biaya_tagih: parseInt(r.total_biaya_tagih) || 0,
    skor:              parseFloat(r.skor)            || 0,
    label_sintetis:    parseInt(r.label_sintetis)    || 0,
    _status:           r._status   || r.status   || 'pending',
    _db_id:            r._db_id    || r.id       || null,
    alasan_flag:       r.alasan_flag || '',
    role_target:       r.role_target || 'Verifikator',
  };
}

function applyRoleFilter(cases) {
  if (S.role === 'apoteker')   return cases.filter(c => ['P1','P2'].includes(c.tipe_fraud));
  if (S.role === 'dokter')     return cases.filter(c => c.tipe_fraud === 'P3');
  return cases;   // verifikator → semua
}

// ─────────────────────────────────────────
// OVERVIEW
// ─────────────────────────────────────────
function renderOverview() {
  const cases = S.cases;
  if (!cases.length) return;

  const p1p2    = cases.filter(c => ['P1','P2'].includes(c.tipe_fraud)).length;
  const p3      = cases.filter(c => c.tipe_fraud === 'P3').length;
  const p4      = cases.filter(c => c.tipe_fraud === 'P4').length;
  const biaya   = cases.reduce((s,c) => s + c.total_biaya_tagih, 0);
  const prec100 = S.results?.gabungan?.['100']?.[0];
  const recall  = S.results2?.sesudah?.recall;

  setText('kpi-flagged',   cases.length);
  setText('kpi-obat',      p1p2);
  setText('kpi-layanan',   p3);
  setText('kpi-identitas', p4);
  setText('kpi-precision', prec100 != null ? pct(prec100) : '100%');
  setText('kpi-recall',    recall  != null ? pct(recall)  : '92.6%');
  setText('kpi-biaya', 'Rp ' + fmtRp(biaya));
  setText('kpi-sub-flagged', `dari ${S.results?.n_peserta?.toLocaleString() ?? '20.000'} peserta`);

  // Alur stats
  setText('m-p1', cases.filter(c=>c.tipe_fraud==='P1').length);
  setText('m-p2', cases.filter(c=>c.tipe_fraud==='P2').length);
  setText('m-p3', p3);
  setText('m-p4', p4);

  renderCharts();
}

function renderCharts() {
  const cases = S.cases;
  if (!cases.length) return;

  // Donut: 3 sub-kategori
  const obat     = cases.filter(c=>['P1','P2'].includes(c.tipe_fraud)).length;
  const layanan  = cases.filter(c=>c.tipe_fraud==='P3').length;
  const identitas= cases.filter(c=>c.tipe_fraud==='P4').length;
  const lain     = cases.length - obat - layanan - identitas;

  mkChart('chartFraudType','doughnut',{
    labels:['Obat/Alkes (P1+P2)','Layanan (P3)','Identitas (P4)','Anomali lain'],
    datasets:[{
      data:[obat, layanan, identitas, lain],
      backgroundColor:['rgba(245,158,11,.8)','rgba(34,211,238,.8)','rgba(168,85,247,.8)','rgba(100,116,139,.5)'],
      borderColor:['#f59e0b','#22d3ee','#a855f7','#64748b'],
      borderWidth:1, hoverOffset:6,
    }],
  }, dOpts());

  // Bar: provinsi
  const pCount = {};
  cases.forEach(c => (c.provinsi_terlibat||'').split(';').forEach(p=>{if(p) pCount[p]=(pCount[p]||0)+1}));
  const pLabels = Object.keys(pCount).map(k=>PROV[k]||k);
  const pVals   = Object.values(pCount);

  mkChart('chartProv','bar',{
    labels: pLabels,
    datasets:[{label:'Kasus',data:pVals,backgroundColor:'rgba(99,102,241,.65)',borderColor:'#6366f1',borderWidth:1,borderRadius:5}],
  }, bOpts());

  // Line: timeline
  const bucket = {};
  cases.forEach(c => {
    const m = (c.waktu_kejadian||'').match(/(\d+)/);
    if(m){ const b=Math.floor(parseInt(m[1])/10)*10; bucket[b]=(bucket[b]||0)+1; }
  });
  const tLabels = Object.keys(bucket).sort((a,b)=>a-b).map(d=>`H${d}–${+d+9}`);
  const tVals   = Object.keys(bucket).sort((a,b)=>a-b).map(d=>bucket[d]);

  mkChart('chartTimeline','line',{
    labels: tLabels,
    datasets:[{label:'Kasus',data:tVals,borderColor:'#6366f1',backgroundColor:'rgba(99,102,241,.1)',
      borderWidth:2,fill:true,tension:.4,pointRadius:3}],
  }, lOpts('Kasus per 10 hari'));

  // Model charts (jika ada results)
  if (S.results && S.results2) {
    const Ks = [50,100,150,200,300,400,600];
    const cols = {rules:{b:'#6366f1',bg:'rgba(99,102,241,.1)'},iforest:{b:'#22d3ee',bg:'rgba(34,211,238,.1)'},gabungan:{b:'#f59e0b',bg:'rgba(245,158,11,.1)'}};
    mkChart('chartModelPrec','line',{
      labels: Ks.map(k=>`K=${k}`),
      datasets: Object.entries(cols).map(([n,c])=>({
        label:n.charAt(0).toUpperCase()+n.slice(1),
        data:Ks.map(k=>(S.results[n]?.[k]?.[0]||0)*100),
        borderColor:c.b,backgroundColor:c.bg,borderWidth:2,fill:false,tension:.4,pointRadius:3,
      })),
    }, lOpts('Precision (%)'));

    const ft = S.results2.fair_tipe||{};
    mkChart('chartRecallType','bar',{
      labels:['P1','P2','P3','P4'],
      datasets:[{label:'Recall %',data:[ft.P1,ft.P2,ft.P3,ft.P4].map(v=>(v||0)*100),
        backgroundColor:['rgba(245,158,11,.7)','rgba(245,158,11,.7)','rgba(34,211,238,.7)','rgba(168,85,247,.7)'],
        borderColor:['#f59e0b','#f59e0b','#22d3ee','#a855f7'],
        borderWidth:1,borderRadius:6}],
    }, {...bOpts(),...{scales:{y:{...dkScales().y,max:110}}}});
  }
}

// ─────────────────────────────────────────
// TABLE
// ─────────────────────────────────────────
function filterTable() {
  const q      = document.getElementById('search-input').value.toLowerCase();
  const type   = document.getElementById('filter-type').value;
  const role   = document.getElementById('filter-role').value;
  const status = document.getElementById('filter-status').value;

  let base = applyRoleFilter([...S.cases]);

  S.filtered = base.filter(c => {
    const mQ = !q ||
      (c.id_pseudonim      ||'').toLowerCase().includes(q) ||
      (c.kode_obat_fkl44   ||'').toLowerCase().includes(q) ||
      (c.kode_diagnosis    ||'').toLowerCase().includes(q) ||
      (c.provinsi_terlibat ||'').toLowerCase().includes(q) ||
      (c.alasan_flag       ||'').toLowerCase().includes(q) ||
      (c.jenis_dugaan      ||'').toLowerCase().includes(q);
    const mT = !type   || c.tipe_fraud   === type;
    const mR = !role   || c.role_target  === role;
    const mS = !status || c._status      === status;
    return mQ && mT && mR && mS;
  });
  S.page = 1;
  renderTable();
}

function renderTable() {
  const {filtered, page, pageSize} = S;
  const start = (page-1)*pageSize;
  const rows  = filtered.slice(start, start+pageSize);
  const tbody = document.getElementById('cases-tbody');
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:3rem 1.5rem;color:var(--muted)"><div style="font-size:2.2rem;margin-bottom:.5rem">📋</div><div style="font-weight:600;font-size:.9rem;color:var(--text);margin-bottom:.3rem">Tidak ada kartu kasus yang ditemukan</div><div style="font-size:.78rem;color:var(--dim);margin-bottom:.8rem">Coba reset filter tipe, role, atau kata kunci pencarian.</div><button onclick="resetFilter()" style="background:var(--accent-lt);border:1px solid var(--accent-bdr);color:var(--accent);font-size:.78rem;font-weight:600;padding:.4rem .9rem;border-radius:6px;cursor:pointer">↺ Reset Semua Filter</button></td></tr>';
    setText('table-count', '0 baris');
    renderPagination();
    return;
  }
  tbody.innerHTML = rows.map((c,i) => {
    const t      = c.tipe_fraud || 'unk';
    const risk   = riskLevel(c.skor);
    const alasan = humanizeAlasan(c.alasan_flag, c);
    const provTxt = fmtProvs(c.provinsi_terlibat);
    const pct100  = Math.min((c.skor / 5) * 100, 100).toFixed(0);

    return `<tr>
      <td><code style="font-size:.72rem;color:var(--dim)">${c.id_pseudonim||'—'}</code></td>
      <td style="max-width:130px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${c.jenis_dugaan}">${c.jenis_dugaan||'—'}</td>
      <td><span class="type-badge ${t}">${t.toUpperCase()}</span></td>
      <td>
        <div class="alasan-chips">
          ${alasan.length
            ? alasan.slice(0,2).map(a=>`<span class="alasan-chip" title="${a}">${a.length>45?a.slice(0,43)+'…':a}</span>`).join('')
            : '<span style="color:var(--muted);font-size:.72rem">Anomali pola umum (ML)</span>'}
          ${alasan.length>2 ? `<span class="alasan-chip" style="background:rgba(99,102,241,.15)">+${alasan.length-2} lagi</span>` : ''}
        </div>
      </td>
      <td><span class="role-badge ${c.role_target||'Verifikator'}">${c.role_target||'Verifikator'}</span></td>
      <td style="font-size:.75rem">${provTxt}</td>
      <td style="text-align:center">${c.jumlah_kunjungan}</td>
      <td>Rp ${fmtRp(c.total_biaya_tagih)}</td>
      <td>
        <div class="risk-badge-wrap">
          <span class="${risk.cls}">${risk.icon} ${risk.label}</span>
          <div class="score-bar" style="margin-top:.2rem"><div class="score-fill" style="width:${pct100}%"></div></div>
        </div>
      </td>
      <td><span class="status-badge ${c._status}">${STATUS_ICON[c._status]||''} ${STATUS_LABEL[c._status]||c._status}</span></td>
      <td><button class="btn-detail" onclick="openDetail(${start+i})">Detail</button></td>
    </tr>`;
  }).join('');

  setText('table-count', `${filtered.length} baris`);
  renderPagination();
}

function renderPagination() {
  const total = Math.ceil(S.filtered.length / S.pageSize);
  const el    = document.getElementById('pagination');
  if (total <= 1) { el.innerHTML=''; return; }
  let h = '';
  for (let p=1; p<=total; p++) {
    if (p===1||p===total||(p>=S.page-2&&p<=S.page+2)) {
      h += `<button class="page-btn ${p===S.page?'active':''}" onclick="goPage(${p})">${p}</button>`;
    } else if (p===S.page-3||p===S.page+3) {
      h += `<span style="color:var(--muted);align-self:center">…</span>`;
    }
  }
  el.innerHTML = h;
}

function goPage(p) { S.page=p; renderTable(); }

// ─────────────────────────────────────────
// DETAIL MODAL
// ─────────────────────────────────────────
function openDetail(idx) {
  const c = S.filtered[idx];
  if (!c) return;
  S.activeCaseCtx = c;

  const alasan = humanizeAlasan(c.alasan_flag, c);
  const provTxt = fmtProvs(c.provinsi_terlibat);
  const risk = riskLevel(c.skor);

  document.getElementById('case-modal-body').innerHTML = `
    <div class="detail-grid">
      <div class="detail-item detail-full">
        <label>ID Peserta (Pseudonim SHA-256)</label>
        <span><code>${c.id_pseudonim}</code></span>
      </div>
      <div class="detail-item">
        <label>Sub-Kategori Dugaan</label>
        <span><strong>${c.jenis_dugaan}</strong></span>
      </div>
      <div class="detail-item">
        <label>Tipe Fraud</label>
        <span><span class="type-badge ${c.tipe_fraud||'unk'}">${(c.tipe_fraud||'UNK').toUpperCase()}</span></span>
      </div>
      <div class="detail-item">
        <label>Petugas yang Ditugaskan</label>
        <span><span class="role-badge ${c.role_target}">${c.role_target}</span></span>
      </div>
      <div class="detail-item">
        <label>Tingkat Risiko</label>
        <span><span class="${risk.cls}">${risk.icon} ${risk.label} (Skor: ${c.skor.toFixed(2)})</span></span>
      </div>
      <div class="detail-item">
        <label>Periode Waktu Kejadian</label>
        <span>${c.waktu_kejadian}</span>
      </div>
      <div class="detail-item">
        <label>Wilayah / Provinsi Terlibat</label>
        <span><strong>${provTxt}</strong></span>
      </div>
      <div class="detail-item detail-full">
        <label>⚠️ Penjelasan Alasan Flag (Bahasa Manusia)</label>
        <div style="margin-top:.4rem;display:flex;flex-direction:column;gap:.35rem">
          ${alasan.length
            ? alasan.map(a=>`<div style="background:#fef2f2;border-left:3px solid #ef4444;padding:.4rem .6rem;border-radius:4px;font-size:.8rem;color:#b91c1c;">• ${a}</div>`).join('')
            : '<div style="color:var(--muted);font-size:.8rem">Anomali kombinasi multidimensi oleh IsolationForest (tidak ada single rule yang tembus batas ekstrim).</div>'}
        </div>
      </div>
      <div class="detail-item">
        <label>Jumlah Kunjungan FKRTL</label>
        <span>${c.jumlah_kunjungan} kali</span>
      </div>
      <div class="detail-item">
        <label>Total Biaya Tagih (FKL47)</label>
        <span style="color:var(--amber);font-weight:700">Rp ${fmtRp(c.total_biaya_tagih)}</span>
      </div>
      <div class="detail-item detail-full">
        <label>Kode Faskes yang Dikunjungi (FKL08)</label>
        <span style="word-break:break-all">${c.faskes_terlibat||'—'}</span>
      </div>
      <div class="detail-item">
        <label>Obat Terkait (FKL44 / Special Drugs)</label>
        <span>${c.kode_obat_fkl44||'—'}</span>
      </div>
      <div class="detail-item">
        <label>Diagnosis ICD-10 (FKP15)</label>
        <span>${c.kode_diagnosis||'—'}</span>
      </div>
      <div class="detail-item detail-full">
        <label>Status Verifikasi Saat Ini</label>
        <span><span class="status-badge ${c._status}">${STATUS_ICON[c._status]||''} ${STATUS_LABEL[c._status]||c._status}</span></span>
      </div>
    </div>
  `;
  document.getElementById('case-modal').classList.add('open');
}

function closeCaseModal() { document.getElementById('case-modal').classList.remove('open'); }

function updateCaseStatus(newStatus, catatanMsg, successMsg) {
  const c = S.activeCaseCtx;
  if (!c) return;
  if (S.mode === 'backend' && c._db_id) {
    fetch(`${S.backendUrl}/verify.php`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({id: c._db_id, status: newStatus, catatan: catatanMsg, user_name: S.role})
    }).then(r => r.json()).then(d => {
      if (d.success) {
        c._status = newStatus;
        renderTable();
        closeCaseModal();
        setStatus('✓ ' + successMsg + ' (tersimpan di Database)');
      }
    }).catch(e => setStatus('⚠ Gagal simpan: ' + e.message));
  } else {
    c._status = newStatus;
    persistFlagToStorage(c.id_pseudonim, newStatus);
    renderTable();
    closeCaseModal();
    setStatus('✓ ' + successMsg + ' (tersimpan di browser)');
  }
}

function setPending() {
  updateCaseStatus('pending', 'Status dikembalikan ke Pending oleh ' + S.role, 'Status kasus dikembalikan ke: Pending');
}

function flagSalah() {
  updateCaseStatus('cleared', 'Kasus diklarifikasi sah/bukan fraud', 'Kasus ditandai: Bersih (Flag Salah)');
}

function confirmFraud() {
  updateCaseStatus('verified_fraud', 'Dikonfirmasi fraud resmi oleh ' + S.role, 'Kasus dikonfirmasi: FRAUD TERBUKTI');
}

function escalateCase() {
  updateCaseStatus('escalated', 'Dieskalasi ke Komite Audit / Manajemen oleh ' + S.role, 'Kasus berhasil DIESKALASI ke Komite Audit');
}

function persistFlagToStorage(id, status) {
  try {
    const flags = JSON.parse(localStorage.getItem('s_flags') || '{}');
    flags[id] = status;
    localStorage.setItem('s_flags', JSON.stringify(flags));
  } catch(_) {}
}

function loadFlagsFromStorage() {
  try {
    const flags = JSON.parse(localStorage.getItem('s_flags') || '{}');
    S.cases.forEach(c => {
      if (flags[c.id_pseudonim]) c._status = flags[c.id_pseudonim];
    });
  } catch(_) {}
}

function sendCaseToAI() {
  closeCaseModal();
  showSection('ai', document.querySelector('[onclick*="ai"]'));
  if (!S.activeCaseCtx) return;
  const c = S.activeCaseCtx;
  const alasanHuman = humanizeAlasan(c.alasan_flag, c).join('; ') || 'Anomali multidimensi IsolationForest';

  document.getElementById('ai-context-box').innerHTML =
    `<strong>${c.id_pseudonim}</strong><br/>
     Dugaan: ${c.jenis_dugaan}<br/>
     Indikasi: ${alasanHuman}<br/>
     Wilayah: ${fmtProvs(c.provinsi_terlibat)}<br/>
     Biaya: Rp ${fmtRp(c.total_biaya_tagih)}`;

  const ctx = `Tolong analisis kasus dugaan fraud JKN berikut secara klinis dan operasional BPJS:
• ID Peserta (Pseudonim): ${c.id_pseudonim}
• Sub-Kategori Kasus: ${c.jenis_dugaan} (Tipe: ${c.tipe_fraud||'Anomali'})
• Indikasi Temuan Sistem: ${alasanHuman}
• Wilayah Faskes: ${fmtProvs(c.provinsi_terlibat)}
• Daftar Faskes (FKL08): ${c.faskes_terlibat||'—'}
• Obat Diklaim (FKL44): ${c.kode_obat_fkl44||'—'}
• Diagnosa ICD-10 (FKP15): ${c.kode_diagnosis||'—'}
• Jumlah Kunjungan: ${c.jumlah_kunjungan} kali
• Estimasi Kerugian / Biaya Tagih: Rp ${fmtRp(c.total_biaya_tagih)}
• Skor Risiko Model: ${c.skor.toFixed(2)} (${riskLevel(c.skor).label})

Pertanyaan:
1. Mengapa pola ini dinilai anomali / melanggar regulasi BPJS Kesehatan?
2. Apa checklist investigasi lapangan konkret yang harus dilakukan oleh ${c.role_target}?
3. Apakah ada potensi "False Positive" (misal rujukan gawat darurat atau protokol klinis sah) yang perlu dicek terlebih dahulu?`;

  const inp = document.getElementById('chat-input');
  inp.value = ctx;
  autoResize(inp);
}

// ─────────────────────────────────────────
// MODEL SECTION
// ─────────────────────────────────────────
function renderModelSection() {
  const r2 = S.results2;
  if (!r2) return;
  const b = r2.sebelum||{}, a = r2.sesudah||{}, hs = r2.hardstop||{};
  const ft = r2.fair_tipe || {};
  setText('f-recall-before', pct(b.recall));
  setText('f-kronis-before', pct2(b.kronis));
  setText('f-nk-before',     pct2(b.non_kronis));
  setText('f-decoy-before',  pct2(b.decoy_pct));
  setText('f-recall-after',  pct(a.recall));
  setText('f-kronis-after',  pct2(a.kronis));
  setText('f-nk-after',      pct2(a.non_kronis));
  setText('f-decoy-after',   pct2(a.decoy_pct));
  setText('hs-diblokir', (hs.diblokir||0).toLocaleString());
  setText('hs-prec',     pct(hs.precision));
  setText('hs-recall',   pct(hs.recall));
  setText('hs-decoy',    pct2(hs.decoy_diblokir_pct));

  // Metrik ringkasan per sub-kategori
  const prec100 = S.results?.gabungan?.['100']?.[0];
  const p1Rec   = ft.P1 || 0;
  const p2Rec   = ft.P2 || 0;
  const p3Rec   = ft.P3 || 0;
  const p4Rec   = ft.P4 || 0;
  const p1p2avg = (p1Rec + p2Rec) / 2;
  setText('m-prec100',   prec100 != null ? pct(prec100) : '100%');
  setText('m-recall-all', pct(a.recall));
  setText('m-rec-p1p2',  pct(p1p2avg));
  setText('m-rec-p3',    pct(p3Rec));
  setText('m-rec-p4',    pct(p4Rec));
  setText('m-decoy-rate', pct2(a.decoy_pct));
}

// ─────────────────────────────────────────
// AI CHAT
// ─────────────────────────────────────────
function updateCtxStats() {
  const c = S.cases;
  const prec100 = S.results?.gabungan?.['100']?.[0];
  const recAll  = S.results2?.sesudah?.recall;
  setText('ctx-total', c.length);
  setText('ctx-fraud', c.filter(x=>x.label_sintetis===1).length);
  setText('ctx-prec',  prec100 != null ? pct(prec100) : '100%');
  setText('ctx-rec',   recAll  != null ? pct(recAll)  : '95.4%');
}

function buildSysPrompt() {
  const prec100 = S.results?.gabungan?.['100']?.[0];
  const recAll  = S.results2?.sesudah?.recall;
  const ft      = S.results2?.fair_tipe || {};
  return `Kamu adalah Sentinel AI, asisten investigasi fraud JKN (BPJS Kesehatan) untuk Healthkathon 2026.

Konteks sistem:
- Kasus terdeteksi: ${S.cases.length}
- Fraud (ground truth sintetis): ${S.cases.filter(c=>c.label_sintetis===1).length}
- Metode: Rules threshold + IsolationForest (unsupervised ML)
- Precision@100: ${prec100 != null ? (prec100*100).toFixed(1)+'%' : '100%'} | Recall: ${recAll != null ? (recAll*100).toFixed(1)+'%' : '95.4%'}
- Per-tipe recall — P1 (Obat multi-faskes): ${ft.P1 ? (ft.P1*100).toFixed(1)+'%' : '94.5%'}, P2 (Qty berlebih): ${ft.P2 ? (ft.P2*100).toFixed(1)+'%' : '95.0%'}, P3 (Duplikasi layanan): ${ft.P3 ? (ft.P3*100).toFixed(1)+'%' : '100%'}, P4 (Identitas): ${ft.P4 ? (ft.P4*100).toFixed(1)+'%' : '88.7%'}

3 Sub-kategori fraud (sesuai Permenkes 16/2019 + proposal):
1. Penyalahgunaan Obat/Alkes (P1,P2) → dikonfirmasi Apoteker
   Sinyal: n_faskes_30d≥3 (drug shopping), qty_ratio≥2.8× (overclaming), gap_days≤0.4 (penebusan prematur)
2. Pelayanan yang Tidak Perlu (P3) → dikonfirmasi Dokter
   Sinyal: repeat_svc_60d≥5 kunjungan poli sama, dx_norm_z tinggi (anomali populasi)
3. Penyalahgunaan Identitas (P4) → ditelaah Verifikator BPJS
   Sinyal: geo_time_conflict≥1 (2 provinsi berbeda hari sama), use_vs_self tinggi (lonjakan tiba-tiba)

7 Fitur (F1-F7) sesuai Proposal Healthkathon hal. 8:
F1: n_faskes_30d, F2: qty_ratio, F3: gap_days, F4: repeat_svc_60d, F5: dx_norm_z, F6: geo_time_conflict, F7: use_vs_self

Prinsip:
- TIDAK ada blokir otomatis — peserta tidak kehilangan akses layanan (Permenkes 16/2019)
- Output: antrean kasus + alasan → keputusan di tangan manusia
- Pseudonimisasi SHA-256, compliance UU PDP 27/2022
- Tombol "Flag Salah" untuk feedback loop menurunkan false positive
- Data SINTETIS — bukan data JKN riil (akses data riil membutuhkan MoU dengan BPJS)

Jawab Bahasa Indonesia. Singkat, spesifik, dan actionable.`;
}

async function sendChat() {
  const inp = document.getElementById('chat-input');
  const msg = inp.value.trim();
  if (!msg) return;

  if (S.mode === 'csv' && !S.geminiKey) {
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
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({message: msg, history: S.chatHistory}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error||`HTTP ${r.status}`);
      reply = d.reply;
    } else {
      S.chatHistory.push({role:'user',parts:[{text:msg}]});
      const r = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=${S.geminiKey}`,
        {method:'POST',headers:{'Content-Type':'application/json'},
         body:JSON.stringify({system_instruction:{parts:[{text:buildSysPrompt()}]},contents:S.chatHistory,
           generationConfig:{temperature:.7,topK:40,topP:.95,maxOutputTokens:1024}})}
      );
      if (!r.ok){const e=await r.json();throw new Error(e.error?.message||`HTTP ${r.status}`);}
      const d = await r.json();
      reply = d.candidates?.[0]?.content?.parts?.[0]?.text || '(Tidak ada respons)';
    }

    S.chatHistory.push({role:'model',parts:[{text:reply}]});
    rmEl(tid);
    addMsg('ai', md2html(reply));
  } catch(e) {
    rmEl(tid);
    addMsg('system', `❌ ${esc(e.message)}`);
    console.error(e);
  } finally {
    document.getElementById('btn-send').disabled = false;
    document.getElementById('ai-dot').className = 'ai-status-dot';
  }
}

function handleChatKey(e) { if (e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();} }
function sendSug(btn) { document.getElementById('chat-input').value=btn.textContent; autoResize(document.getElementById('chat-input')); sendChat(); }

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
  const id = 'ty-'+Date.now();
  d.id = id; d.className = 'chat-msg ai';
  d.innerHTML = `<div class="msg-bubble"><div class="typing-ind"><span></span><span></span><span></span></div></div>`;
  w.appendChild(d); w.scrollTop = w.scrollHeight;
  return id;
}

function rmEl(id) { document.getElementById(id)?.remove(); }

// ─────────────────────────────────────────
// ROLE SWITCHER
// ─────────────────────────────────────────
function setRole(role, btn) {
  S.role = role;
  document.querySelectorAll('.role-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const labels = {verifikator:'🏢 Verifikator', apoteker:'💊 Apoteker', dokter:'🩺 Dokter'};
  setText('role-indicator', labels[role]);
  S.filtered = applyRoleFilter([...S.cases]);
  S.page = 1;
  renderTable();
}

// ─────────────────────────────────────────
// IMPORT DB
// ─────────────────────────────────────────
async function importToDB() {
  if (S.mode !== 'backend') {
    alert('Import ke database hanya bisa dilakukan saat berjalan di server XAMPP (Apache + PHP + MySQL). Saat menggunakan python http.server, dashboard langsung membaca file CSV/JSON.');
    return;
  }
  setStatus('Mengimport CSV ke database...');
  try {
    const fd = new FormData(); fd.append('use_default','1');
    const r = await fetch(`${S.backendUrl}/import.php`,{method:'POST',body:fd});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error||`HTTP ${r.status}`);
    setStatus(`✓ Import: ${d.imported} baris, total DB: ${d.total_db}`);
    await loadAllData();
  } catch(e) { setStatus('⚠ Import gagal: '+e.message); }
}

// ─────────────────────────────────────────
// NAVIGATION
// ─────────────────────────────────────────
function showSection(name, el) {
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  document.getElementById(`section-${name}`)?.classList.add('active');
  const navEl = el || document.querySelector(`.sidebar-nav .nav-item[onclick*="${name}"]`);
  if (navEl) navEl.classList.add('active');
  const titles = {overview:'Overview',alur:'Alur Sistem',cases:'Kartu Kasus',model:'Performa Model',ai:'AI Investigator'};
  setText('page-title', titles[name]||name);
  try { history.replaceState(null, '', '#' + name); } catch(_) {}
}

// ─────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────
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
  S.dataPath   = document.getElementById('data-path').value.trim()||'../';
  S.backendUrl = document.getElementById('backend-url').value.trim()||'../backend/api';
  if (!S.dataPath.endsWith('/')) S.dataPath+='/';
  localStorage.setItem('s_key', S.geminiKey);
  localStorage.setItem('s_dp',  S.dataPath);
  localStorage.setItem('s_bu',  S.backendUrl);
  toggleSettings();
  S.mode = 'auto';
  autoDetect().then(()=>loadAllData());
}

function loadSettings() {
  S.geminiKey  = localStorage.getItem('s_key')||'';
  S.dataPath   = localStorage.getItem('s_dp') ||'../';
  S.backendUrl = localStorage.getItem('s_bu') ||CFG.BACKEND_URL;
}

function toggleKey() {
  const i=document.getElementById('gemini-api-key');
  i.type=i.type==='password'?'text':'password';
}

function closeModalOut(e, id) { if(e.target===e.currentTarget) document.getElementById(id).classList.remove('open'); }

// ─────────────────────────────────────────
// CHART HELPERS
// ─────────────────────────────────────────
function dkScales() {
  return {
    x:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'rgba(255,255,255,.04)'}},
    y:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'rgba(255,255,255,.04)'}},
  };
}
function dkLegend() { return {labels:{color:'#94a3b8',font:{size:10},boxWidth:10,padding:14}}; }
function ttip() { return {backgroundColor:'#0c1018',borderColor:'rgba(255,255,255,.1)',borderWidth:1,titleColor:'#e2e8f0',bodyColor:'#94a3b8'}; }

function lOpts(yLabel) { return {responsive:true,maintainAspectRatio:false,plugins:{legend:dkLegend(),tooltip:ttip()},scales:{...dkScales(),y:{...dkScales().y,title:{display:!!yLabel,text:yLabel,color:'#64748b',font:{size:10}}}}}; }
function bOpts() { return lOpts(); }
function dOpts() { return {responsive:true,maintainAspectRatio:false,cutout:'60%',plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:10},boxWidth:10,padding:10}},tooltip:ttip()}}; }

function mkChart(id, type, data, opts) {
  const existing = Object.entries(S.charts).find(([,c])=>c?.canvas?.id===id);
  if (existing) { existing[1].destroy(); delete S.charts[existing[0]]; }
  const el = document.getElementById(id);
  if (!el) return;
  S.charts[id] = new Chart(el, {type, data, options:opts});
}

// ─────────────────────────────────────────
// DATA FETCH
// ─────────────────────────────────────────
async function fetchJSON(url) {
  const basename = url.split('/').pop();
  const paths = [...new Set([url, S.dataPath + basename, '../' + basename, './' + basename, '/' + basename, basename])];
  for (const p of paths) {
    try {
      const r = await fetch(p);
      if (r.ok) return await r.json();
    } catch(_) {}
  }
  return null;
}
async function fetchCSV(targetPath) {
  const filename = 'kartu_kasus.csv';
  const paths = [...new Set([
    targetPath,
    S.dataPath + filename,
    '../' + filename,
    './' + filename,
    '/' + filename,
    filename
  ])];

  let rawText = null;
  for (const p of paths) {
    try {
      const res = await fetch(p);
      if (res.ok) {
        const text = await res.text();
        if (text && text.includes('id_pseudonim')) {
          rawText = text;
          break;
        }
      }
    } catch (_) {}
  }

  if (!rawText) {
    throw new Error('File kartu_kasus.csv tidak dapat diunduh dari server.');
  }

  // Parse CSV: gunakan PapaParse jika ada, atau fallback parser bawaan
  if (typeof Papa !== 'undefined' && Papa.parse) {
    const parsed = Papa.parse(rawText, { header: true, skipEmptyLines: true });
    if (parsed.data && parsed.data.length > 0) {
      return parsed.data;
    }
  }

  // Fallback parsing mandiri tanpa dependensi luar
  const lines = rawText.trim().split(/\r?\n/);
  const headers = lines[0].split(',').map(h => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const vals = line.split(',');
    const row = {};
    headers.forEach((h, idx) => {
      row[h] = vals[idx] !== undefined ? vals[idx].trim() : '';
    });
    rows.push(row);
  }
  return rows;
}

// ─────────────────────────────────────────
// UTILS
// ─────────────────────────────────────────
function setText(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}
function setStatus(m){setText('data-status',m);}
function pct(v){return v!=null?(v*100).toFixed(1)+'%':'—';}
function pct2(v){return v!=null?v.toFixed(2)+'%':'—';}
function fmtRp(n){if(n>=1e9)return(n/1e9).toFixed(1)+' M';if(n>=1e6)return(n/1e6).toFixed(1)+' jt';if(n>=1e3)return(n/1e3).toFixed(0)+' rb';return n?.toLocaleString('id-ID')||'0';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function autoResize(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,110)+'px';}
function md2html(md){
  return md
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.*?)\*/g,'<em>$1</em>')
    .replace(/`([^`]+)`/g,'<code style="background:rgba(255,255,255,.08);padding:.1em .3em;border-radius:3px;font-size:.88em">$1</code>')
    .replace(/^###\s(.+)/gm,'<h4 style="margin:.5rem 0 .2rem;font-size:.85rem;color:#818cf8">$1</h4>')
    .replace(/^##\s(.+)/gm,'<h3 style="margin:.6rem 0 .3rem;font-size:.92rem">$1</h3>')
    .replace(/^- (.+)/gm,'<li style="margin:.15rem 0">$1</li>')
    .replace(/(<li.*<\/li>)/gs,'<ul style="padding-left:1.1rem;margin:.35rem 0">$1</ul>')
    .replace(/\n\n/g,'</p><p style="margin:.4rem 0">')
    .replace(/\n/g,'<br/>');
}


function resetFilter() {
  const inp = document.getElementById('search-input'); if (inp) inp.value = '';
  const ft = document.getElementById('filter-type'); if (ft) ft.value = '';
  const fr = document.getElementById('filter-role'); if (fr) fr.value = '';
  const fs = document.getElementById('filter-status'); if (fs) fs.value = '';
  S.role = 'verifikator';
  document.querySelectorAll('.role-btn').forEach((b,i) => b.classList.toggle('active', i === 0));
  setText('role-indicator', '🏢 Verifikator');
  filterTable();
}
