import json, csv

r1 = json.load(open('results.json'))
r2 = json.load(open('results2.json'))
g  = r1['gabungan']
ft = r2['fair_tipe']

print('=== FINAL METRICS AUDIT ===')
print('Run at   :', r1.get('run_at','?'))
print('Peserta  :', f"{r1['n_peserta']:,}")
print('Fraud    :', r1['n_fraud_tertanam'], '(P1=%d P2=%d P3=%d P4=%d)' % (
    r1['tipe']['P1'], r1['tipe']['P2'], r1['tipe']['P3'], r1['tipe']['P4']))
print('Decoy    :', r1['n_decoy'])
print()
print('--- Precision@K (gabungan rules+iforest) ---')
for k in [50,100,150,200,300,400,600]:
    v = g[str(k)]
    print('  K=%3d: P=%.1f%%  R=%.1f%%  decoy=%.1f%%' % (k, v[0]*100, v[1]*100, v[2]*100))
print()
print('--- Recall per Tipe (setelah fairness normalization) ---')
for t, v in ft.items():
    print('  %s: %.1f%%' % (t, v*100))
print()
print('Overall recall  :', '%.1f%%' % (r2['sesudah']['recall']*100))
print('Kronis FPR      :', '%.1f%%' % r2['sesudah']['kronis'])
print('Decoy terdeteksi:', '%.1f%%' % r2['sesudah']['decoy_pct'])

rows = list(csv.DictReader(open('kartu_kasus.csv', encoding='utf-8-sig')))
n_fraud = sum(1 for r in rows if r['label_sintetis'] == '1')
n_fp    = sum(1 for r in rows if r['label_sintetis'] == '0')
print()
print('Kartu kasus     :', len(rows), 'baris')
print('  Benar fraud   :', n_fraud, '(TP)')
print('  False positive:', n_fp, '(non-fraud yang ikut terdeteksi)')
print()
print('Penjelasan untuk juri:')
print('  - P@50-200=100% karena pola fraud eksplisit (P1-P4) tertangkap rules threshold')
print('  - P@300 turun ke 96.7% saat IsolationForest juga berkontribusi (decoy masuk)')
print('  - P4 recall 88.7% (bukan 100%) karena 30% kasus P4 menggunakan hari berdekatan')
print('    bukan hari persis sama, sehingga geo_time_conflict=0 dan hanya IForest yg tangkap')
print('  - P2 recall 95% karena 40% kasus menggunakan qty borderline 75-89 (bukan 90-120)')

