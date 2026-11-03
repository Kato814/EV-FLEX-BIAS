"""OpenDSS feeder evaluation and sensitivity-based balanced power planning."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import math
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from opendssdirect import dss as dss_default


IEEE13 = Path('data/feeders/ieee13/IEEE13Nodeckt.dss')

LV = Path('data/feeders/lv906_core/MasterStaticAudit.dss')

@dataclass(frozen=True)
class EV:
    ev_id:int; capacity:float; initial:float; target:float; reserve:float
    arrival:int; departure:int; pch:float; pdis:float; eta_c:float; eta_d:float
    v2g:bool; max_discharge:float; bus:str; phase:int; kv_ln:float

FEEDERS = {
 'ieee13': dict(master=IEEE13, balanced='posseq', buses=['634','670','671','675'], kv={'634':0.277,'670':2.4,'671':2.4,'675':2.4}, kva_limit=5000.0),
 'lv906': dict(master=LV, balanced='rebalance', buses=['178','349','502','676','899','906'], kv={b:0.240 for b in ['178','349','502','676','899','906']}, kva_limit=800.0),
}

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
