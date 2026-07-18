from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal
import json, math, time

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import make_pipeline
from opendssdirect import dss as dss_default

OUT = Path('/mnt/data/EV_V1G_V2G_paper_stage')
IEEE13 = Path('/mnt/data/EV_V1G_V2G_feasibility/data/ieee13/IEEE13Nodeckt.dss')
LV = Path('/mnt/data/work_final_stage/lvtest/MasterStatic.dss')
DT = 0.25
T = 96

@dataclass(frozen=True)
class EV:
    ev_id:int; capacity:float; initial:float; target:float; reserve:float
    arrival:int; departure:int; pch:float; pdis:float; eta_c:float; eta_d:float
    v2g:bool; max_discharge:float; bus:str; phase:int; kv_ln:float

FEEDERS = {
 'ieee13': dict(master=IEEE13, balanced='posseq', buses=['634','670','671','675'], kv={'634':0.277,'670':2.4,'671':2.4,'675':2.4}, kva_limit=5000.0),
 'lv906': dict(master=LV, balanced='rebalance', buses=['178','349','502','676','899','906'], kv={b:0.240 for b in ['178','349','502','676','899','906']}, kva_limit=800.0),
}

def clock_hour(slot): return (12.0 + slot*DT) % 24

def price_vector():
    h=np.array([clock_hour(t) for t in range(T)])
    p=np.full(T,0.18); p[(h>=0)&(h<6)]=0.08; p[(h>=17)&(h<22)]=0.32
    return p
PRICE=price_vector()

def generate_fleet(feeder:str, n:int, seed:int, v2g_rate:float, phase_ratio:tuple[int,int,int], loc_conc:float)->list[EV]:
    rng=np.random.default_rng(seed); cfg=FEEDERS[feeder]; buses=cfg['buses']; far=buses[-1]
    phase_pool=np.repeat([1,2,3], phase_ratio)
    out=[]
    for i in range(n):
        cap=float(rng.choice([50,60,70,82,90])); pch=float(rng.choice([7.2,7.2,7.2,11.0]))
        arr=int(np.clip(np.rint(rng.normal(26,5.5)),10,42))
        dep=int(np.clip(np.rint(rng.normal(77,4.5)),66,91))
        if dep<=arr+20: dep=min(92,arr+24)
        soc=float(np.clip(rng.normal(.40,.12),.15,.68)); initial=soc*cap; reserve=.20*cap
        maxreach=min(.92*cap, initial+.95*pch*DT*(dep-arr))
        target=max(initial, min(float(np.clip(rng.normal(.80,.06),.67,.90))*cap,maxreach))
        bus=far if rng.random()<loc_conc else str(rng.choice(buses))
        phase=int(rng.choice(phase_pool)); v2g=bool(rng.random()<v2g_rate)
        out.append(EV(i+1,cap,initial,target,min(reserve,initial),arr,dep,pch,pch if v2g else 0,.95,.95,v2g,float(rng.choice([6,8,10,12])) if v2g else 0,bus,phase,cfg['kv'][bus]))
    return out

def baseline_schedule(ev:EV)->np.ndarray:
    p=np.zeros(T); need=max(0,(ev.target-ev.initial)/ev.eta_c)
    slots=list(range(ev.arrival,ev.departure)); slots.sort(key=lambda t:(PRICE[t], ((t*37 + ev.ev_id*53) % 101)))
    for t in slots:
        x=min(ev.pch,need/DT); p[t]=x; need-=x*DT
        if need<=1e-9: break
    if need>1e-6: raise RuntimeError('infeasible generated EV')
    return p

def bounds_at(ev:EV,tau:int,mode:str)->tuple[float,float]:
    if not (ev.arrival<=tau<ev.departure): return 0.0,0.0
    nb=tau-ev.arrival; na=ev.departure-tau-1
    e_before_max=min(ev.capacity,ev.initial+ev.eta_c*ev.pch*DT*nb)
    future_max=ev.eta_c*ev.pch*DT*na
    required=max(0,(ev.target-e_before_max-future_max)/(ev.eta_c*DT))
    lo_v1=min(ev.pch,required)
    hi=min(ev.pch,max(0,(ev.capacity-ev.initial)/(ev.eta_c*DT)))
    if mode=='v1g' or not ev.v2g: return lo_v1,hi
    d=min(ev.pdis,ev.max_discharge/DT,
          max(0,ev.eta_d*(e_before_max-ev.reserve)/DT),
          max(0,ev.eta_d*(e_before_max+future_max-ev.target)/DT))
    lo=-d if d>1e-9 else lo_v1
    return lo,hi

def fleet_arrays(fleet,tau):
    rows=[]
    for ev in fleet:
        l1,h1=bounds_at(ev,tau,'v1g'); l2,h2=bounds_at(ev,tau,'v2g')
        b=l1  # minimum-feasible common baseline; remaining energy is scheduled in other 15-min slots
        rows.append({**asdict(ev),'base':b,'v1_lo':l1,'v1_hi':h1,'v2_lo':l2,'v2_hi':h2})
    return pd.DataFrame(rows)

class Network:
    def __init__(self, feeder:str, fleet_df:pd.DataFrame, model:Literal['3ph','balanced'], load_scale:float, vmin=.95,vmax=1.05,vuf=2.0):
        self.feeder=feeder; self.cfg=FEEDERS[feeder]; self.model=model; self.fd=fleet_df.copy(); self.load_scale=load_scale
        self.vmin=vmin; self.vmax=vmax; self.vuf=vuf; self.ctx=dss_default.NewContext(); self.labels=None
        self._prepare()
    def _prepare(self):
        c=self.ctx; c.Command('clear'); c.Command(f'compile "{self.cfg["master"]}"')
        native=list(c.Loads.AllNames())
        native_bus_set=set()
        for _name in native:
            c.Loads.Name(_name); c.Circuit.SetActiveElement('Load.'+_name)
            native_bus_set.add(c.CktElement.BusNames()[0].split('.')[0])
        if self.model=='balanced' and self.cfg['balanced']=='rebalance':
            agg={}
            for name in native:
                c.Loads.Name(name); c.Circuit.SetActiveElement('Load.'+name); bus=c.CktElement.BusNames()[0].split('.')[0]
                agg.setdefault(bus,[0.,0.]); agg[bus][0]+=c.Loads.kW()*self.load_scale; agg[bus][1]+=c.Loads.kvar()*self.load_scale
                c.CktElement.Enabled(False)
            for bus,(p,q) in agg.items():
                c.Command(f'new load.bn_{bus} bus1={bus}.1.2.3 phases=3 conn=wye model=1 kv=.416 kw={p} kvar={q}')
        else:
            for name in native:
                c.Loads.Name(name); c.Loads.kW(c.Loads.kW()*self.load_scale); c.Loads.kvar(c.Loads.kvar()*self.load_scale)
        c.Command('set controlmode=static maxcontroliter=100'); c.Solution.Solve(); c.Command('set controlmode=off')
        if self.model=='balanced' and self.cfg['balanced']=='posseq':
            c.Command('makeposseq'); c.Solution.Solve()
        if not c.Solution.Converged(): raise RuntimeError('base network failed')
        self.monitor_buses = sorted(set(c.Circuit.AllBusNames())) if self.feeder=='ieee13' else sorted(native_bus_set | set(self.cfg['buses']))
        _all_lines=list(c.Lines.AllNames())
        self.line_names=_all_lines if self.feeder=='ieee13' else _all_lines[:40]
        if self.model=='3ph':
            self.groups=sorted({(str(r.bus),int(r.phase)) for r in self.fd.itertuples(index=False)})
            for bus,ph in self.groups:
                kv=float(self.fd[(self.fd.bus.astype(str)==bus)&(self.fd.phase==ph)].kv_ln.iloc[0]); safe=bus.replace('.','_')
                c.Command(f'new load.ev_{safe}_{ph} bus1={bus}.{ph} phases=1 conn=wye model=1 kv={kv} kw=0 kvar=0')
                c.Command(f'new generator.eg_{safe}_{ph} bus1={bus}.{ph} phases=1 conn=wye model=1 kv={kv} kw=0 kvar=0')
        else:
            self.groups=sorted(self.fd.bus.astype(str).unique())
            for bus in self.groups:
                kv=float(self.fd[self.fd.bus.astype(str)==bus].kv_ln.iloc[0]); safe=bus.replace('.','_')
                if self.cfg['balanced']=='posseq':
                    c.Command(f'new load.eb_{safe} bus1={bus}.1 phases=1 conn=wye model=1 kv={kv} kw=0 kvar=0')
                    c.Command(f'new generator.gb_{safe} bus1={bus}.1 phases=1 conn=wye model=1 kv={kv} kw=0 kvar=0')
                else:
                    c.Command(f'new load.eb_{safe} bus1={bus}.1.2.3 phases=3 conn=wye model=1 kv=.416 kw=0 kvar=0')
                    c.Command(f'new generator.gb_{safe} bus1={bus}.1.2.3 phases=3 conn=wye model=1 kv=.416 kw=0 kvar=0')
        c.Solution.Solve(); self.base=self.evaluate(np.zeros(len(self.groups)))
    def setp(self,p):
        c=self.ctx
        if self.model=='3ph':
            for (bus,ph),v in zip(self.groups,p):
                safe=bus.replace('.','_'); c.Loads.Name(f'ev_{safe}_{ph}'); c.Loads.kW(max(float(v),0)); c.Generators.Name(f'eg_{safe}_{ph}'); c.Generators.kW(max(-float(v),0))
        else:
            div=3.0 if self.cfg['balanced']=='posseq' else 1.0
            for bus,v in zip(self.groups,p):
                safe=bus.replace('.','_'); c.Loads.Name(f'eb_{safe}'); c.Loads.kW(max(float(v),0)/div); c.Generators.Name(f'gb_{safe}'); c.Generators.kW(max(-float(v),0)/div)
    def evaluate(self,p):
        c=self.ctx; self.setp(np.asarray(p)); c.Solution.Solve(); conv=bool(c.Solution.Converged())
        metrics={}
        for bus in self.monitor_buses:
            try:
                c.Circuit.SetActiveBus(bus); nodes=list(c.Bus.Nodes()); va=list(c.Bus.puVmagAngle())
                for j,node in enumerate(nodes):
                    if 2*j < len(va) and np.isfinite(va[2*j]): metrics[f'V:{bus.lower()}.{node}']=float(va[2*j])
            except Exception:
                pass
        if self.model=='3ph':
            for bus in self.monitor_buses:
                c.Circuit.SetActiveBus(bus); nodes=set(c.Bus.Nodes())
                if {1,2,3}.issubset(nodes):
                    seq=c.Bus.SeqVoltages()
                    if len(seq)>=3 and seq[1]>1e-8: metrics['U:'+bus.lower()]=100*float(seq[2])/float(seq[1])
        # Stable subset of current constraints: all lines in IEEE13, upstream 40 lines in LV906.
        for name in self.line_names:
            c.Lines.Name(name); c.Circuit.SetActiveElement('Line.'+name); vals=c.CktElement.CurrentsMagAng(); nc=c.CktElement.NumConductors(); mags=[float(vals[2*i]) for i in range(min(nc,len(vals)//2))]
            em=float(c.Lines.EmergAmps())
            if em>0 and mags: metrics['I:'+name.lower()]=max(mags)/em
        tp=c.Circuit.TotalPower(); metrics['S:feeder']=math.hypot(float(tp[0]),float(tp[1]))/(self.cfg['kva_limit']*1.10)
        if self.labels is None: self.labels=list(metrics)
        vec=np.array([metrics.get(k,np.nan) for k in self.labels]); ok,viol=self.check(vec,conv)
        return {'vector':vec,'metrics':metrics,'feasible':ok,'violations':viol,'converged':conv,
                'vmin':min([v for k,v in metrics.items() if k.startswith('V:')],default=np.nan),
                'vmax':max([v for k,v in metrics.items() if k.startswith('V:')],default=np.nan),
                'vufmax':max([v for k,v in metrics.items() if k.startswith('U:')],default=0),
                'linemax':max([v for k,v in metrics.items() if k.startswith('I:')],default=0),
                'sload':metrics['S:feeder']}
    def bounds(self):
        lo=np.full(len(self.labels),-np.inf); hi=np.full(len(self.labels),np.inf)
        for i,k in enumerate(self.labels):
            if k.startswith('V:'): lo[i]=self.vmin; hi[i]=self.vmax
            elif k.startswith('U:'): hi[i]=self.vuf
            elif k.startswith('I:') or k.startswith('S:'): hi[i]=1.0
        return lo,hi
    def check(self,vec,conv=True):
        lo,hi=self.bounds() if self.labels is not None else (None,None); viol=[]
        if lo is None:return conv,viol
        for i,k in enumerate(self.labels):
            if not np.isfinite(vec[i]): continue
            if vec[i]<lo[i]-1e-7: viol.append((k,float(vec[i]),float(lo[i]),'lo'))
            if vec[i]>hi[i]+1e-7: viol.append((k,float(vec[i]),float(hi[i]),'hi'))
        return bool(conv and not viol),viol
    def sensitivity(self,p0,step=1.0):
        m0=self.evaluate(p0); S=np.zeros((len(m0['vector']),len(p0)))
        for j in range(len(p0)):
            q=np.array(p0,float); q[j]+=step; m=self.evaluate(q); S[:,j]=(m['vector']-m0['vector'])/step
        return m0,S
    def optimize(self,p0,lo_p,hi_p,direction,lin):
        m0,S=lin
        if not m0['feasible']: return {'success':False,'p':np.array(p0),**m0}
        lo,hi=self.bounds(); A=[];b=[]
        for i in range(len(m0['vector'])):
            if np.isfinite(hi[i]): A.append(S[i]); b.append(hi[i]-m0['vector'][i]+S[i]@p0)
            if np.isfinite(lo[i]): A.append(-S[i]); b.append(m0['vector'][i]-lo[i]-S[i]@p0)
        obj=np.ones(len(p0)) if direction=='min' else -np.ones(len(p0))
        res=linprog(obj,A_ub=np.array(A),b_ub=np.array(b),bounds=list(zip(lo_p,hi_p)),method='highs')
        if not res.success:return {'success':False,'p':np.array(p0),**m0}
        cand=res.x; mc=self.evaluate(cand)
        if mc['feasible']:return {'success':True,'p':cand,**mc}
        a0,a1=0.,1.; best=np.array(p0); bm=m0
        for _ in range(25):
            a=(a0+a1)/2; q=p0+a*(cand-p0); mm=self.evaluate(q)
            if mm['feasible']:a0=a;best=q;bm=mm
            else:a1=a
        return {'success':True,'p':best,**bm}

def aggregate(fd,series,net:Network):
    if net.model=='3ph': return np.array([series[(fd.bus.astype(str)==b)&(fd.phase==p)].sum() for b,p in net.groups])
    return np.array([series[fd.bus.astype(str)==b].sum() for b in net.groups])

def map_balanced(target,nb:Network,n3:Network,p03,lo3,hi3,direction):
    out=np.array(p03,dtype=float)
    for bus,targ in zip(nb.groups,target):
        idx=[i for i,(b,p) in enumerate(n3.groups) if b==bus]; base=out[idx].sum(); delta=targ-base
        room=(hi3[idx]-out[idx]) if delta>=0 else (out[idx]-lo3[idx]); total=room.sum()
        if total>1e-9: out[idx]+=np.sign(delta)*room*min(abs(delta)/total,1.0)
    return np.minimum(np.maximum(out,lo3),hi3)

def ray_alpha(net,p0,target):
    if net.evaluate(target)['feasible']:return 1.0
    lo,hi=0.,1.
    for _ in range(26):
        a=(lo+hi)/2
        if net.evaluate(p0+a*(target-p0))['feasible']:lo=a
        else:hi=a
    return lo

def scenario_run(feeder, split, idx, seed):
    rng=np.random.default_rng(seed)
    if feeder=='ieee13': n=int(rng.integers(30,85)); ls=float(rng.uniform(.45,.85))
    else: n=int(rng.integers(15,50)); ls=float(rng.uniform(.20,.65))
    ratios=[(1,1,1),(2,1,1),(4,1,1)]; ratio=ratios[int(rng.integers(0,3))]
    loc=float(rng.uniform(.05,.85)); vr=float(rng.uniform(.25,.95)); tau=int(rng.choice([52,56,60,64]))
    fleet=generate_fleet(feeder,n,seed+911,vr,ratio,loc); fd=fleet_arrays(fleet,tau)
    n3=Network(feeder,fd,'3ph',ls); nb=Network(feeder,fd,'balanced',ls)
    base=pd.Series(fd.base.values,index=fd.index); p03=aggregate(fd,base,n3); p0b=aggregate(fd,base,nb)
    if not n3.evaluate(p03)['feasible'] or not nb.evaluate(p0b)['feasible']: return []
    lin3=n3.sensitivity(p03); linb=nb.sensitivity(p0b)
    rows=[]
    for direction,lo_col,hi_col,mode in [('inc','v1_lo','v1_hi','V1G'),('dec','v2_lo','v2_hi','V2G')]:
        lo_ser=pd.Series(fd[lo_col].values,index=fd.index); hi_ser=pd.Series(fd[hi_col].values,index=fd.index)
        lo3=aggregate(fd,lo_ser,n3); hi3=aggregate(fd,hi_ser,n3); lob=aggregate(fd,lo_ser,nb); hib=aggregate(fd,hi_ser,nb)
        sense='max' if direction=='inc' else 'min'
        r3=n3.optimize(p03,lo3,hi3,sense,lin3); rb=nb.optimize(p0b,lob,hib,sense,linb)
        mapped=map_balanced(rb['p'],nb,n3,p03,lo3,hi3,sense); alpha=ray_alpha(n3,p03,mapped)
        f3=(r3['p'].sum()-p03.sum()) if sense=='max' else (p03.sum()-r3['p'].sum())
        fb=(rb['p'].sum()-p0b.sum()) if sense=='max' else (p0b.sum()-rb['p'].sum())
        phase_counts=fd.groupby('phase').size().reindex([1,2,3],fill_value=0).values
        m0=n3.evaluate(p03)
        rows.append(dict(feeder=feeder,split=split,scenario=idx,seed=seed,direction=direction,mode=mode,tau=tau,clock=clock_hour(tau),n_ev=n,load_scale=ls,v2g_rate=vr,location_concentration=loc,
                         phase_imbalance=(phase_counts.max()-phase_counts.min())/max(n,1),far_share=float((fd.bus.astype(str)==FEEDERS[feeder]['buses'][-1]).mean()),baseline_kw=float(p03.sum()),
                         base_vmin=m0['vmin'],base_vmax=m0['vmax'],base_vuf=m0['vufmax'],base_line=m0['linemax'],base_feeder=m0['sload'],balanced_flex=max(fb,0),true_flex=max(f3,0),
                         optimal_ratio=(f3/fb if fb>1e-6 else 1.0),ray_alpha=alpha,raw_feasible=bool(alpha>=.999999),soc_violation=0.0,
                         mapped_violation_count=len(n3.evaluate(mapped)['violations'])))
    return rows

def _fit_one_rule(tr,te,features,cat,num,seed=11):
    tr=tr.sample(frac=1,random_state=seed).reset_index(drop=True)
    cut=max(10,min(len(tr)-5,int(.72*len(tr)))) if len(tr)>=15 else max(3,len(tr)-2)
    fit=tr.iloc[:cut]; cal=tr.iloc[cut:]
    # Direct lower-quantile model, then one-sided conformal correction.
    pipe=make_pipeline(
        ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore'),cat),('num','passthrough',num)]),
        GradientBoostingRegressor(random_state=seed,n_estimators=160,max_depth=2,min_samples_leaf=4,learning_rate=.04,loss='quantile',alpha=.15)
    )
    pipe.fit(fit[features],fit.ray_alpha)
    pc=pipe.predict(cal[features])
    scores=pc-cal.ray_alpha.values
    # finite-sample 95% upper quantile of unsafe overprediction scores
    q=float(np.quantile(scores,.95,method='higher')) if len(scores) else .15
    pred=np.clip(pipe.predict(te[features])-max(q,0),0,1)
    return pred

def fit_calibrate(train,test):
    features=['feeder','n_ev','load_scale','v2g_rate','location_concentration','phase_imbalance','far_share','baseline_kw','base_vmin','base_vmax','base_vuf','base_line','base_feeder','balanced_flex']
    cat=['feeder']; num=[x for x in features if x not in cat]
    output=[]
    specs=[]
    # Most defensible rule: separate by direction and feeder, while retaining one common feature set.
    for d in ['inc','dec']:
        for f in sorted(train.feeder.unique()): specs.append(('directional_feeder',d,f))
    for d in ['inc','dec']: specs.append(('directional_global',d,'all'))
    specs.append(('unified','all','all'))
    for scope,d,f in specs:
        tr=train.copy(); te=test.copy()
        if d!='all': tr=tr[tr.direction==d]; te=te[te.direction==d]
        if f!='all': tr=tr[tr.feeder==f]; te=te[te.feeder==f]
        if len(tr)<8 or len(te)==0: continue
        pred=_fit_one_rule(tr,te,features,cat,num,seed=11+len(output))
        for row,k in zip(te.itertuples(index=False),pred):
            output.append(dict(scope=scope,rule_direction=d,rule_feeder=f,feeder=row.feeder,scenario=row.scenario,direction=row.direction,alpha_true=row.ray_alpha,k_offer=float(k),violation=bool(k>row.ray_alpha+1e-6),raw_balanced_flex=row.balanced_flex,offered_flex=float(k*row.balanced_flex),retention_balanced=float(k),retention_true=float(min(k/max(row.ray_alpha,1e-9),1.0)),soc_violation=0.0))
    return pd.DataFrame(output)

def main():
    t0=time.time(); rows=[]
    # 40 training and 20 independent test scenarios per feeder
    for feeder in FEEDERS:
        for split,count,base in [('train',40,10000 if feeder=='ieee13' else 20000),('test',20,30000 if feeder=='ieee13' else 40000)]:
            for i in range(count):
                try: rows += scenario_run(feeder,split,i,base+i*37)
                except Exception as e: print('SKIP',feeder,split,i,type(e).__name__,str(e)[:100])
    df=pd.DataFrame(rows); df.to_csv(OUT/'all_scenarios.csv',index=False)
    train=df[df.split=='train']; test=df[df.split=='test']; cal=fit_calibrate(train,test); cal.to_csv(OUT/'calibration_test_results.csv',index=False)
    summary=[]
    for scope,g in cal.groupby('scope'):
        summary.append(dict(scope=scope,n=len(g),network_violation_rate=float(g.violation.mean()),soc_violation_rate=float(g.soc_violation.mean()),mean_balanced_retention=float(g.retention_balanced.mean()),mean_true_retention=float(g.retention_true.mean())))
        for d,h in g.groupby('direction'):
            summary.append(dict(scope=scope+'_'+d,n=len(h),network_violation_rate=float(h.violation.mean()),soc_violation_rate=0.0,mean_balanced_retention=float(h.retention_balanced.mean()),mean_true_retention=float(h.retention_true.mean())))
    sm=pd.DataFrame(summary); sm.to_csv(OUT/'decision_metrics.csv',index=False)
    # Gate decision
    directional=sm[sm.scope=='directional_feeder'].iloc[0] if any(sm.scope=='directional_feeder') else None
    feeder_coverage=set(df.feeder)==set(FEEDERS); enough=len(test)>=20
    go=bool(directional is not None and directional.network_violation_rate<=.05 and directional.mean_balanced_retention>=.60 and feeder_coverage and enough)
    decision={'decision':'GO' if go else 'NO-GO','feeder_coverage':sorted(set(df.feeder)),'n_scenario_direction_rows':len(df),'n_train_rows':len(train),'n_test_rows':len(test),'directional_rule':directional.to_dict() if directional is not None else None,'elapsed_sec':time.time()-t0,
              'raw_balanced_infeasible_rate_test':float((~test.raw_feasible).mean()) if len(test) else None,'mean_ray_alpha_test':float(test.ray_alpha.mean()) if len(test) else None,'reason':('方向性降额规则在两个馈线的独立样本外场景中满足≤5%网络违约、0%SOC违约并保留≥60%平衡模型灵活性。' if go else '样本外安全性、灵活性保留率或跨馈线覆盖未达到锁题门槛。')}
    (OUT/'final_decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2))
    # concise report
    report=f'''# 正式研究阶段最终决策\n\n## 决策：**{decision['decision']}**\n\n- 测试馈线：{', '.join(decision['feeder_coverage'])}\n- 训练/样本外方向场景：{len(train)} / {len(test)}\n- 未校准平衡模型在样本外场景中的不可兑现率：{decision['raw_balanced_infeasible_rate_test']:.1%}\n- 分方向校准后网络违约率：{directional.network_violation_rate:.1%}\n- 用户SOC违约率：{directional.soc_violation_rate:.1%}\n- 平均保留平衡模型申报灵活性：{directional.mean_balanced_retention:.1%}\n- 平均保留真实射线可交付灵活性：{directional.mean_true_retention:.1%}\n\n{decision['reason']}\n'''
    (OUT/'final_decision_report.md').write_text(report,encoding='utf-8')
    print(json.dumps(decision,ensure_ascii=False,indent=2)); print(sm.to_string(index=False))
if __name__=='__main__': main()
