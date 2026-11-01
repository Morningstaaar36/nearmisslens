"""SS4A action-plan grants, FY22-FY25, from USDOT's award spreadsheets (not stored here; download them from the award
list pages, e.g. https://www.transportation.gov/grants/ss4a/2025-full-award-list, which refuse scripts: use the
Wayback Machine). Usage: python validation/ss4a/action_plans.py DIR_WITH_XLSX > validation/ss4a/action_plans.json
Counts only grants for a new or updated action plan alone."""
import json, statistics as st, sys
import openpyxl

SPEC = {"FY22-SS4A-Full-Award-List-March2025.xlsx": ("Grant Type", lambda v: v == "Action Plan"),
        "FY23-SS4A-Award-List-March2025.xlsx": ("Application Type", lambda v: v == "Develop New Action Plan (only)"),
        "FY24-SS4A-Award-List-March2025.xlsx": ("Planning and Demonstration Activities",
                                                lambda v: v and (v.startswith("Develop a new") or v.startswith("Update/add"))),
        "FY25-SS4A-Award-List-FY2025.xlsx": ("Planning and Demonstration Activities",
                                             lambda v: v and (v.startswith("Develop a new") or v.startswith("Update/add")))}
out, allc = {}, []
for f, (col, pred) in SPEC.items():
    rows = list(openpyxl.load_workbook(f"{sys.argv[1]}/{f}", read_only=True).worksheets[0].iter_rows(values_only=True))
    h = rows[0]
    ci, fi, ti = h.index(col), h.index("Total Federal Funding "), h.index("Total Project Cost")
    sel = [r for r in rows[1:] if pred(r[ci]) and r[fi]]
    tot = [float(r[ti]) for r in sel if r[ti]]
    allc += tot
    out[f[:4]] = {"grants": len(sel), "median_total_cost_usd": round(st.median(tot)), "mean_total_cost_usd": round(st.mean(tot))}
out["all"] = {"grants": sum(v["grants"] for v in out.values()), "median_total_cost_usd": round(st.median(allc)),
              "quartiles_total_cost_usd": [round(x) for x in st.quantiles(allc, n=4)]}
print(json.dumps(out, indent=1))
