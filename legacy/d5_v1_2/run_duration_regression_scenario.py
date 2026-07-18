#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import pandas as pd

import duration_aware_engine_v1_2 as eng


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--scenario-id',required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    core=eng.load_module(args.repo/'scripts/vendor/network_core_v1_2.py','duration_core_chunk')
    eng.configure_core(core,args.repo)
    scenarios=pd.read_csv(args.repo/'config/base_scenarios_v1_2.csv')
    pops=pd.read_csv(args.repo/'data/processed/formal_inputs_v1_2/formal_ev_populations_v1_2.csv')
    lp=pd.read_csv(args.repo/'config/controlled_native_load_profile_v1_2.csv')
    s=scenarios[scenarios.scenario_id==args.scenario_id].iloc[0]
    fleet=eng.build_fleet(pops[pops.scenario_id==args.scenario_id],core.EV)
    base=eng.uniform_baseline(fleet); scales=eng.scenario_load_scales(lp,s)
    rows=[]
    for direction in ['inc','dec']:
        for duration in [15,30,60]:
            t=time.time(); result=eng.compare_models(core,s.feeder,fleet,base,s.call_time,duration,direction,scales)
            row=eng.summarize_result(s,direction,duration,result,time.time()-t); row['n_ev']=len(fleet); rows.append(row)
            print(json.dumps(row,default=float),flush=True)
    pd.DataFrame(rows).to_csv(args.out/f'{args.scenario_id}.csv',index=False)

if __name__=='__main__': main()
