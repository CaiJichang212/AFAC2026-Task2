from __future__ import annotations
import json, statistics
from pathlib import Path

ROOT = Path("/data/liyc/test/AFAC2026-Task2")
METRICS = ROOT / "outputs/table_train_run_v2/metrics/table_eval.json"
OUT_DIR = ROOT / "outputs/table_train_run_v2/metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)
report = json.loads(METRICS.read_text(encoding="utf-8"))
files = report["files"]

def short(name): return name.split(".")[0][:8]
def pct(values, q):
    s = sorted(values)
    if not s: return 0
    k = (len(s)-1)*q; f=int(k); c=min(f+1,len(s)-1)
    return s[f]+(s[c]-s[f])*(k-f)

teds=[f["table_teds"] for f in files if f["has_table"]]
te=[f["text_edit"] for f in files]
roe=[f["read_order_edit"] for f in files]
ov=[f["overall"] for f in files]

L=[]
L.append("# table_train_run_v2 逐条评分深度分析\n")
L.append(f"样本数: {len(files)}\n")
L.append("## 一、聚合指标\n")
L.append("| 指标 | min | p25 | 中位 | p75 | max | mean |")
L.append("|---|---|---|---|---|---|---|")
for label,arr in [("text_edit",te),("table_teds",teds),("read_order_edit",roe),("overall",ov)]:
    m=sum(arr)/len(arr)
    L.append(f"| {label} | {min(arr):.4f} | {pct(arr,0.25):.4f} | {pct(arr,0.5):.4f} | {pct(arr,0.75):.4f} | {max(arr):.4f} | {m:.4f} |")
L.append("")
L.append("## 二、TEDS 分桶\n")
buckets=[0,1,10,30,50,70,85,95,101]
counts=[0]*(len(buckets)-1)
for v in teds:
    for i in range(len(buckets)-1):
        if buckets[i]<=v<buckets[i+1]: counts[i]+=1; break
for i in range(len(buckets)-1):
    L.append(f"- TEDS [{buckets[i]},{buckets[i+1]}): {counts[i]}/{len(teds)}")
L.append("")

sorted_by_ov=sorted(files,key=lambda x:x["overall"])
bottom20=sorted_by_ov[:20]
top20=sorted_by_ov[-20:][::-1]
L.append("## 三、Overall 最差 20 条\n")
L.append("| rank | overall | teds | text_edit | roe | file_name |")
L.append("|---|---|---|---|---|---|")
for i,f in enumerate(bottom20,1):
    L.append(f"| {i} | {f['overall']:.2f} | {f['table_teds']:.2f} | {f['text_edit']:.4f} | {f['read_order_edit']:.4f} | {short(f['file_name'])} |")
L.append("")
L.append("## 四、Overall 最优 20 条\n")
L.append("| rank | overall | teds | text_edit | roe | file_name |")
L.append("|---|---|---|---|---|---|")
for i,f in enumerate(top20,1):
    L.append(f"| {i} | {f['overall']:.2f} | {f['table_teds']:.2f} | {f['text_edit']:.4f} | {f['read_order_edit']:.4f} | {short(f['file_name'])} |")
L.append("")

sorted_by_teds=sorted(files,key=lambda x:(x["table_teds"] if x["has_table"] else 0))
L.append("## 五、TEDS 最差 20 条\n")
L.append("| rank | teds | text_edit | roe | overall | file_name |")
L.append("|---|---|---|---|---|---|")
for i,f in enumerate(sorted_by_teds[:20],1):
    L.append(f"| {i} | {f['table_teds']:.2f} | {f['text_edit']:.4f} | {f['read_order_edit']:.4f} | {f['overall']:.2f} | {short(f['file_name'])} |")
L.append("")
L.append("## 六、TEDS 最优 20 条\n")
L.append("| rank | teds | text_edit | roe | overall | file_name |")
L.append("|---|---|---|---|---|---|")
for i,f in enumerate(sorted_by_teds[-20:][::-1],1):
    L.append(f"| {i} | {f['table_teds']:.2f} | {f['text_edit']:.4f} | {f['read_order_edit']:.4f} | {f['overall']:.2f} | {short(f['file_name'])} |")
L.append("")

(OUT_DIR/"analysis.md").write_text("\n".join(L),encoding="utf-8")
print("mean_overall:",round(report["mean_overall"],2))
print("mean_table_teds:",round(report["mean_table_teds"],2))
print("mean_text_edit:",round(report["mean_text_edit"],4))
print("mean_read_order_edit:",round(report["mean_read_order_edit"],4))
print("TEDS<10:",sum(1 for v in teds if v<10))
print("TEDS>=80:",sum(1 for v in teds if v>=80))
print("TE<0.1:",sum(1 for v in te if v<0.1))
print("TE>1:",sum(1 for v in te if v>1))
print("ROE>1:",sum(1 for v in roe if v>1))
print("BOTTOM20:",",".join(short(f['file_name']) for f in bottom20))
print("TOP20:",",".join(short(f['file_name']) for f in top20))
