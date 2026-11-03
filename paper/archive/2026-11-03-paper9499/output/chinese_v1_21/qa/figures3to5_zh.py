from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

DATA=Path(__file__).resolve().parent/'figure_data'
HERE=Path(__file__).resolve().parents[1]/'figures'
HERE.mkdir(parents=True,exist_ok=True)
mpl.rcParams.update({
    'font.family':['Times New Roman','SimSun'],
    'font.size':8,
    'axes.labelsize':8,
    'axes.titlesize':8,
    'xtick.labelsize':8,
    'ytick.labelsize':8,
    'legend.fontsize':8,
    'mathtext.fontset':'custom',
    'mathtext.rm':'Times New Roman',
    'mathtext.it':'Times New Roman:italic',
    'mathtext.bf':'Times New Roman:bold',
    'pdf.fonttype':42,
    'svg.fonttype':'none',
    'ps.fonttype':42,
    'axes.linewidth':0.8,
})
COLORS={'00:00':'#377eb8','02:00':'#ff7f00','06:00':'#4daf4a','19:00':'#984ea3'}
MARKERS={'00:00':'o','02:00':'s','06:00':'^','19:00':'D'}
ORDER=['00:00','02:00','06:00','19:00']

def save_zh(fig, stem):
    for extension in ('pdf','svg','png'):
        fig.savefig(HERE/f'{stem}.{extension}', dpi=600, bbox_inches='tight', pad_inches=0.005)

def fig3():
    df=pd.read_csv(DATA/'fig3_scheduled_offer_data.csv')
    df['f_feas_kw']=df['f_bal_kw']*df['alpha_fixed']
    limits={'IEEE13':((150,2050),(150,2050)),'LV906':((0,280),(0,280))}
    for feeder in ['IEEE13','LV906']:
        sub=df[df['feeder']==feeder]
        fig,ax=plt.subplots(figsize=(3.50,2.55))
        for _,r in sub.iterrows():
            ax.plot([r['f_bal_kw'],r['f_bal_kw']],[r['f_feas_kw'],r['f_bal_kw']],color='0.84',lw=0.7,zorder=1)
        for ct in ORDER:
            ss=sub[sub['call_time']==ct]
            ax.scatter(ss['f_bal_kw'],ss['f_feas_kw'],s=31,marker=MARKERS[ct],facecolor=COLORS[ct],edgecolor='black',linewidth=0.45,label=ct,zorder=3)
        (xmin,xmax),(ymin,ymax)=limits[feeder]
        lo,hi=min(xmin,ymin),max(xmax,ymax)
        ax.plot([lo,hi],[lo,hi],'--',color='black',lw=1.0,zorder=2)
        ax.set_xlim(xmin,xmax); ax.set_ylim(ymin,ymax)
        ax.set_xlabel('计划灵活性功率 (kW)'); ax.set_ylabel('可实施灵活性功率 (kW)')
        ax.grid(True,linestyle=':',color='0.80',linewidth=0.55); ax.set_axisbelow(True)
        leg=ax.legend(title='调用时刻',loc='upper left',frameon=True,borderpad=0.28,handletextpad=0.35,labelspacing=0.32)
        leg.get_title().set_fontsize(8)
        fig.tight_layout(pad=0.35)
        save_zh(fig,f'fig3_{feeder.lower()}_scheduled_vs_feasible_offer')
        plt.close(fig)

def fig4():
    # Use the call-time enriched data file to preserve the existing visual encoding.
    df=pd.read_csv(DATA/'fig3_scheduled_offer_data.csv')[['feeder','call_time','alpha_fixed']].copy()
    fig,ax=plt.subplots(figsize=(3.50,2.45))
    positions={'IEEE13':1.0,'LV906':2.0}
    groups=[df[df.feeder=='IEEE13'].alpha_fixed.to_numpy(),df[df.feeder=='LV906'].alpha_fixed.to_numpy()]
    ax.boxplot(groups,positions=[1,2],widths=0.36,showfliers=False,patch_artist=False,
               medianprops={'color':'#ff7f00','linewidth':1.1},boxprops={'linewidth':0.8},
               whiskerprops={'linewidth':0.8},capprops={'linewidth':0.8})
    rng=np.random.default_rng(20260817)
    for feeder in ['IEEE13','LV906']:
        sub=df[df.feeder==feeder].reset_index(drop=True)
        x0=positions[feeder]
        # bounded small jitter; all points retained
        jitter=rng.uniform(-0.095,0.095,len(sub))
        for ct in ORDER:
            idx=sub.index[sub.call_time==ct].to_numpy()
            ax.scatter(np.full(len(idx),x0)+jitter[idx],sub.loc[idx,'alpha_fixed'],
                       s=26,marker=MARKERS[ct],facecolor=COLORS[ct],edgecolor='black',linewidth=0.4,label=ct if feeder=='IEEE13' else None,zorder=3)
    ax.axhline(1.0,color='black',linestyle='--',linewidth=0.8)
    ax.axhline(0.95,color='0.55',linestyle=':',linewidth=0.8)
    ax.set_xlim(0.55,2.45); ax.set_ylim(0.10,1.04)
    ax.set_xticks([1,2],['IEEE13','LV906']); ax.set_ylabel(r'可行缩放因子 α')
    ax.grid(axis='y',linestyle=':',color='0.82',linewidth=0.55); ax.set_axisbelow(True)
    ax.legend(loc='lower center',bbox_to_anchor=(0.5,1.01),ncol=4,frameon=False,columnspacing=0.8,handletextpad=0.25)
    fig.tight_layout(pad=0.35)
    save_zh(fig,'fig4_feasible_scaling_distribution')
    plt.close(fig)

def fig5():
    df=pd.read_csv(DATA/'fig5_boundary_data.csv')
    cats=[('low_voltage','低电压','#8ecae6','///'),('high_voltage','高电压','#f4a261','---'),('vuf','电压不平衡度','#cdb4db','xx'),('transformer','变压器负载','#f6d365','..')]
    fig,ax=plt.subplots(figsize=(3.50,2.30))
    y=np.array([0.0,0.58]); left=np.zeros(2)
    for field,label,color,hatch in cats:
        vals=df[field].to_numpy(float)
        bars=ax.barh(y,vals,left=left,height=0.30,color=color,edgecolor='black',linewidth=0.75,hatch=hatch,label=label)
        for bar,val,lft in zip(bars,vals,left):
            if val<=0: continue
            ax.text(lft+val/2,bar.get_y()+bar.get_height()/2,f'{int(val)}',ha='center',va='center',fontsize=8,
                    bbox=dict(boxstyle='round,pad=0.12',facecolor='white',edgecolor='none',alpha=0.96))
        left += vals
    ax.set_yticks(y,df['feeder'].tolist()); ax.invert_yaxis(); ax.set_ylim(0.78,-0.20); ax.set_xlim(0,23.5)
    ax.set_xlabel('受限算例数')
    ax.grid(axis='x',linestyle=':',color='0.82',linewidth=0.55); ax.set_axisbelow(True)
    label_x={0.0:22.45,0.58:22.95}
    for yi,total in zip(y,left):
        ax.text(label_x[float(yi)],yi,f'n={int(total)}',ha='right',va='center',fontsize=8,
                bbox=dict(facecolor='white',edgecolor='none',pad=0.10,alpha=0.96),clip_on=True)
    ax.legend(loc='lower center',bbox_to_anchor=(0.5,1.03),ncol=2,frameon=True,borderpad=0.28,columnspacing=0.9,handlelength=1.6)
    fig.tight_layout(pad=0.30)
    save_zh(fig,'fig5_limiting_network_constraints')
    plt.close(fig)

if __name__=='__main__':
    fig3(); fig4(); fig5()
