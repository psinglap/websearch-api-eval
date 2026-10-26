"""Final latency. Headline = search-only run 1 (first time each query is sent, one call at a time).
Run 2 (~12-25 min later) = repeat-query / cache probe. Content mode (config B) = first repeat."""
import glob, json, re, statistics as st, csv, sys
PROV = ["You.com", "Tavily", "Exa", "Parallel"]
def load(path):
    rows = []
    for r in json.load(open(path))["results"]["results"]:
        m = (r.get("response") or {}).get("metadata") or {}
        if m.get("error_type") not in (None, "", "empty_results") and not m.get("results"):
            continue  # failed call
        rows.append(dict(p=r["provider"]["label"], qid=m.get("qid") or r["vars"].get("qid"),
                         client=m.get("search_latency_ms"), server=m.get("provider_reported_latency_ms"),
                         rep=m.get("repeat_index", 0)))
    return rows
med = lambda v: round(st.median(v)) if v else None
out_sum, out_q = [], []
for uc in ["gtm", "insurance", "finance"]:
    runs = {}
    for f in sorted(glob.glob(f"out/searchonly/{uc}_run*_*.json")):
        n = int(re.search(r"_run(\d)_", f).group(1)); runs[n] = load(f)  # newest file per run number wins
    content = [r for r in load(sorted(glob.glob(f"out/{uc}_results_*.json"))[-1]) if r["rep"] in (0, None)]
    for p in PROV:
        s_p50 = [med([r["server"] for r in runs[n] if r["p"] == p and r["server"] is not None]) for n in sorted(runs)]
        c_p50 = [med([r["client"] for r in runs[n] if r["p"] == p and r["client"] is not None]) for n in sorted(runs)]
        allc = [r["client"] for r in runs.get(1, []) if r["p"] == p and r["client"] is not None]
        avg = lambda v: round(sum(x for x in v if x is not None) / len([x for x in v if x is not None])) if any(x is not None for x in v) else None
        cc = [r["client"] for r in content if r["p"] == p and r["client"] is not None]
        cs = [r["server"] for r in content if r["p"] == p and r["server"] is not None]
        out_sum.append(dict(usecase=uc, provider=p, runs=len(runs),
            server_p50_run1=s_p50[0], client_p50_run1=c_p50[0],
            server_p50_run2_repeat=s_p50[1] if len(s_p50) > 1 else None,
            client_p50_run2_repeat=c_p50[1] if len(c_p50) > 1 else None,
            slowest_client_ms=round(max(allc)) if allc else None,
            within_1s=f"{sum(1 for x in allc if x <= 1000)}/{len(allc)}",
            content_client_p50=med(cc), content_server_p50=med(cs)))
        for q in sorted({r["qid"] for n in runs for r in runs[n]}, key=lambda q: int(q[1:])):
            vals = [r for r in runs.get(1, []) if r["p"] == p and r["qid"] == q]
            out_q.append(dict(usecase=uc, qid=q, provider=p,
                server_p50=med([r["server"] for r in vals if r["server"] is not None]),
                client_p50=med([r["client"] for r in vals if r["client"] is not None])))
for name, rows in [("latency_summary.csv", out_sum), ("latency_per_query.csv", out_q)]:
    with open(f"out/latency_final/{name}", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in out_sum: print(r)
