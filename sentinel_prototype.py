"""JKN Sentinel - prototype pada DATA SINTETIS (tanpa data JKN riil). Jalankan: python sentinel_prototype.py"""
import json, numpy as np, pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
rng=np.random.default_rng(2026)
N=20000; HORIZON=180
NF=[24,16,12,6,4]                                   # jumlah faskes per wilayah (3,4 = wilayah minim faskes)
base=np.cumsum([0]+NF)
wil=rng.choice(5,N,p=[.35,.25,.2,.12,.08]); kron=rng.random(N)<.18; age=rng.integers(0,4,N)
def fk(w): return base[w]+rng.integers(0,NF[w])
fraud=np.zeros(N,int); ftype=np.array(['']*N,dtype=object); decoy=np.zeros(N,int)
idx=rng.permutation(N); p=0
def take(frac,mask=None):
    global p
    k=int(N*frac); ids=idx[p:p+k]; p+=k; return ids
P1,P2,P3,P4=take(.010),take(.005),take(.008),take(.004)
for ids,t in ((P1,'P1'),(P2,'P2'),(P3,'P3'),(P4,'P4')): fraud[ids]=1; ftype[ids]=t
cand=[i for i in idx[p:] if kron[i]]; DEC=rng.choice(cand,int(N*.03),replace=False); decoy[DEC]=1
res=[];svc=[]
def addres(i,f,w,t,drug,qty,terapi): res.append((i,f,w,t,drug,qty,terapi))
def addsvc(i,f,w,t,j): svc.append((i,f,w,t,j))
for i in range(N):
    w=wil[i]; home=fk(w)
    cross=lambda: (lambda w2:(fk(w2),w2))(2 if (w>=3 and rng.random()<.15) else w)
    if kron[i]:
        d=rng.integers(0,20); t=rng.integers(0,30); sw=rng.random()<.06
        while t<HORIZON:
            f,ww=(fk(w),w) if (sw and t>90) else (home,w)
            addres(i,f,ww,t,d,30,30); t+=30+rng.integers(-3,4)
    else:
        for _ in range(rng.poisson(1.2)): addres(i,home,w,rng.integers(0,HORIZON),rng.integers(20,60),7,7)
    for _ in range(rng.poisson(5.0 if kron[i] else 1.8)):
        f,ww=cross(); addsvc(i,f,ww,rng.integers(0,HORIZON),rng.integers(0,6))
for i in P1:
    d=rng.integers(0,20); t0=rng.integers(40,140)
    for k in range(rng.integers(3,6)): w=rng.integers(0,5); addres(i,fk(w),w,t0+rng.integers(0,25),d,30,30)
for i in P2:
    d=rng.integers(0,20); w=wil[i]; f=fk(w); t0=rng.integers(40,140)
    for k in range(2): addres(i,f,w,t0+k*12,d,int(rng.choice([90,120])),30)
for i in P3:
    j=rng.integers(0,6); t0=rng.integers(40,120)
    for k in range(rng.integers(6,10)): w=rng.integers(0,5); addsvc(i,fk(w),w,t0+rng.integers(0,55),j)
for i in P4:
    t0=rng.integers(20,160)
    for w in (0,int(rng.choice([3,4]))): addsvc(i,fk(w),w,t0,rng.integers(0,6))
for i in DEC:                                         # sah: rujukan bolak-balik + layanan banyak
    d=rng.integers(0,20); t0=rng.integers(40,140); w=wil[i]
    addres(i,fk(w),w,t0,d,30,30); addres(i,fk(w),w,t0+10,d,30,30) if False else None
    addres(i,fk(w),w,t0+12,d,0+1,30)
    for _ in range(rng.integers(6,10)): addsvc(i,fk(w),w,rng.integers(0,HORIZON),rng.integers(0,6))
R=pd.DataFrame(res,columns='id faskes wil t drug qty terapi'.split()); S=pd.DataFrame(svc,columns='id faskes wil t jenis'.split())
feat=pd.DataFrame(index=range(N)); 
def f_drug(g):
    g=g.sort_values('t'); T=g.t.values; F=g.faskes.values; Q=g.qty.values
    nf=max(len(set(F[(T>=T[k]-29)&(T<=T[k])])) for k in range(len(T)))
    qr=max(Q[(T>=T[k]-29)&(T<=T[k])].sum()/30 for k in range(len(T)))
    return pd.Series({'nf':nf,'qr':qr})
d=R[R.groupby(['id','drug']).id.transform('size')>1].groupby(['id','drug']).apply(f_drug,include_groups=False).groupby('id').max()
single=R.groupby('id').qty.max()/30
feat['n_faskes_30d']=d.nf.reindex(range(N)).fillna(1)
feat['qty_ratio']=np.maximum(d.qr.reindex(range(N)).fillna(1),single.reindex(range(N)).fillna(1)*np.where(single.reindex(range(N)).fillna(1)>=3,1,0)+1e-9).clip(lower=1)
def rep60(g):
    return max((((g.jenis==j)&(g.t>=t-59)&(g.t<=t)).sum()) for j,t in zip(g.jenis,g.t))
feat['repeat_svc_60d']=S.groupby('id').apply(rep60,include_groups=False).reindex(range(N)).fillna(0)
cnt=S.groupby('id').size().reindex(range(N)).fillna(0)
grp=kron.astype(int)*4+age
feat['dx_norm_z']=((cnt-cnt.groupby(grp).transform('mean'))/cnt.groupby(grp).transform('std')).values
ev=pd.concat([R[['id','wil','t']],S[['id','wil','t']]])
def geo(g):
    g=g.sort_values('t'); T=g.t.values; W=g.wil.values; return sum(1 for a in range(len(T)) for b in range(a+1,len(T)) if T[b]-T[a]<=1 and abs(W[a]-W[b])>=3)
feat['geo_time_conflict']=ev.groupby('id').apply(geo,include_groups=False).reindex(range(N)).fillna(0)
X=feat.values.astype(float)
# rules: skor 0..4 + bobot
rules=(feat.n_faskes_30d>=3)*1+(feat.qty_ratio>=2.0)*1+(feat.repeat_svc_60d>=6)*1+(feat.geo_time_conflict>=1)*1
iso=IsolationForest(n_estimators=300,random_state=7).fit(StandardScaler().fit_transform(X))
anom=-iso.score_samples(StandardScaler().fit_transform(X)); anom=(anom-anom.min())/(anom.max()-anom.min())
score=rules+anom
y=fraud; out={'n_peserta':N,'n_fraud_tertanam':int(y.sum()),'n_decoy':int(decoy.sum()),'n_resep':len(R),'n_layanan':len(S)}
out['tipe']={t:int((ftype==t).sum()) for t in ('P1','P2','P3','P4')}
def at_k(sc,K):
    top=np.argsort(-sc)[:K]; tp=y[top].sum(); return tp/K, tp/y.sum(), decoy[top].sum()/decoy.sum()
Ks=[50,100,150,200,300,400,600]
for name,sc in (('rules',rules+1e-6*rng.random(N)),('iforest',anom),('gabungan',score)):
    out[name]={str(K):[round(float(v),3) for v in at_k(sc,K)] for K in Ks}
K0=int(y.sum()); top=np.argsort(-score)[:K0]; flag=np.zeros(N,bool); flag[top]=True
out['K_eval']=K0
out['flag_rate']={'kronis':round(float(flag[kron&(fraud==0)].mean()*100),2),'non_kronis':round(float(flag[(~kron)&(fraud==0)].mean()*100),2)}
out['flag_rate_wilayah']={str(w):round(float(flag[(wil==w)&(fraud==0)].mean()*100),2) for w in range(5)}
out['recall_per_tipe']={t:round(float(flag[ftype==t].mean()),3) for t in ('P1','P2','P3','P4')}
out['decoy_flagged_pct']=round(float(flag[decoy==1].mean()*100),2)
json.dump(out,open('results.json','w'),indent=1,ensure_ascii=False); print(json.dumps(out,indent=1,ensure_ascii=False))

# ===== Analisis lanjutan: mitigasi bias, hard-stop, sensitivitas prevalensi =====
rk=rules.values; ex={}
anom_g=pd.Series(anom).groupby(pd.Series(grp)).rank(pct=True).values      # normalisasi skor anomali per kelompok kronis x usia
score_m=rk+anom_g
def flags(sc,K): f=np.zeros(N,bool); f[np.argsort(-sc)[:K]]=True; return f
def summ(f): 
    return {'recall':round(float(f[y==1].mean()),4),'kronis':round(float(f[kron&(y==0)].mean()*100),2),'non_kronis':round(float(f[(~kron)&(y==0)].mean()*100),2),'decoy_pct':round(float(f[decoy==1].mean()*100),2),
            'wilayah':{str(w):round(float(f[(wil==w)&(y==0)].mean()*100),2) for w in range(5)}}
ex['sebelum']=summ(flag); ex['sesudah']=summ(flags(score_m,K0))
hs=(feat.n_faskes_30d>=2).values
ex['hardstop']={'diblokir':int(hs.sum()),'precision':round(float(y[hs].mean()),4),'recall':round(float(hs[y==1].mean()),4),'decoy_diblokir_pct':round(float(decoy[hs].sum()/decoy.sum()*100),2),'peserta_sah_diblokir':int(((y==0)&hs).sum())}
sv=[]
for p_ in (0.027,0.01,0.005):
    nfr=540 if p_>=0.027 else int(p_*(N-540)/(1-p_))
    keep=rng.choice(np.where(y==1)[0],nfr,replace=False); ids=np.concatenate([np.where(y==0)[0],keep])
    Xs=StandardScaler().fit_transform(X[ids]); a2=-IsolationForest(n_estimators=300,random_state=7).fit(Xs).score_samples(Xs); a2=(a2-a2.min())/(a2.max()-a2.min())
    sc2=rk[ids]+pd.Series(a2).groupby(pd.Series(grp[ids])).rank(pct=True).values
    top=np.argsort(-sc2)[:nfr]; sv.append({'prevalensi_pct':round(p_*100,1),'n_fraud':nfr,'precision_at_n':round(float(y[ids][top].mean()),4),'decoy_pct':round(float(decoy[ids][top].sum()/decoy.sum()*100),2)})
ex['prevalensi']=sv
ex['fair']={str(K):[round(float(v),3) for v in (lambda top:(y[top].sum()/K,y[top].sum()/y.sum(),decoy[top].sum()/decoy.sum()))(np.argsort(-score_m)[:K])] for K in Ks}
ff=flags(score_m,K0); ex['fair_tipe']={t:round(float(ff[ftype==t].mean()),3) for t in ('P1','P2','P3','P4')}
json.dump(ex,open('results2.json','w'),indent=1,ensure_ascii=False); print(json.dumps(ex,ensure_ascii=False))
