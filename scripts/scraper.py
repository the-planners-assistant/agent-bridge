import csv, time, mimetypes, requests
from urllib.parse import urlparse

BASE = "https://www.planning.data.gov.uk/entity.json"
FIELDS = ["reference","name","organisation-entity","document-url","documentation-url",
          "document-types","entry-date","local-plan"]

SPLIT_FIX = {
    "sustainability-apprasial": "sustainability-appraisal",
    "local-plan;site-allocations": "local-plan;site-allocations",  # keep both
}

UA = {"User-Agent": "TPA-harvester/1.0 (+planning use)"}

def fix_types(s: str) -> list[str]:
    if not s: return []
    parts = [p.strip() for p in s.split(";") if p.strip()]
    fixed = []
    for p in parts:
        fixed.append(SPLIT_FIX.get(p, p))
    return sorted(set(fixed))

def fetch_docs(limit=500):
    params = {"dataset":"local-plan-document","field":FIELDS,"limit":limit,"offset":0}
    while True:
        r = requests.get(BASE, params=params, headers=UA, timeout=60)
        r.raise_for_status()
        data = r.json()
        items = data.get("entities", [])
        if not items: break
        for it in items: yield it
        params["offset"] += params["limit"]; time.sleep(0.2)

org_cache = {}
def resolve_org(entity_id: str):
    if not entity_id: return {"lpa_curie":"", "lpa_name":""}
    if entity_id in org_cache: return org_cache[entity_id]
    r = requests.get(f"https://www.planning.data.gov.uk/entity/{entity_id}.json",
                     headers=UA, timeout=30)
    r.raise_for_status()
    j = r.json()
    curie = f"{j.get('prefix','')}:{j.get('reference','')}".strip(":")
    org_cache[entity_id] = {"lpa_curie":curie, "lpa_name":j.get("name","")}
    time.sleep(0.1)
    return org_cache[entity_id]

def classify_url(u: str):
    if not u: return ("", "", 0, "unknown")
    # Quick guard: treat obvious viewers/apps as landing
    host = urlparse(u).hostname or ""
    viewer_hosts = ("arcgis.com","maps.arcgis.com","sharepoint.com","google.com","drive.google.com")
    if any(host.endswith(h) for h in viewer_hosts):
        return (u, "", 0, "landing")
    ext = (urlparse(u).path or "").lower()
    guessed = mimetypes.guess_type(ext)[0] or ""
    try:
        h = requests.head(u, headers=UA, allow_redirects=True, timeout=25)
        status = h.status_code
        ctype = h.headers.get("Content-Type","").split(";")[0].strip().lower()
        final = h.url
        # Fallback tiny GET if HEAD blocked
        if status >= 400 or (not ctype):
            g = requests.get(u, headers=UA|{"Range":"bytes=0-0"}, allow_redirects=True, timeout=30)
            status = g.status_code
            ctype = g.headers.get("Content-Type","").split(";")[0].strip().lower()
            final = g.url
    except requests.RequestException:
        return (u, "", 0, "unknown")
    file_kind = ("pdf" if "pdf" in ctype or ext.endswith(".pdf")
                 else "image" if ctype.startswith("image/")
                 else "html" if "html" in ctype
                 else "doc" if ctype.startswith("application/")
                 else "unknown")
    return (final, ctype, status, file_kind)

seen = set()
rows = []
doc_count = 0
for d in fetch_docs():
    doc_count += 1
    if doc_count % 10 == 0:
        print(f"Processed {doc_count} documents, {len(rows)} unique rows...")
    
    org = resolve_org(str(d.get("organisation-entity","")).strip())
    doc_types = fix_types(d.get("document-types",""))
    key = (org["lpa_curie"], d.get("local-plan",""), d.get("document-url",""))
    if key in seen: continue
    seen.add(key)

    file_url = d.get("document-url","").strip()
    landing_url = d.get("documentation-url","").strip()

    if doc_count % 10 == 1:  # Print for first in batch
        print(f"  Classifying URL: {file_url[:60]}...")
    final_url, ctype, status, file_kind = classify_url(file_url)

    # If it's not an actual document, demote to landing_url
    if file_kind in ("landing","html","unknown") and landing_url:
        final_url = ""  # keeps it as landing-only row

    rows.append({
        "lpa_curie": org["lpa_curie"],
        "lpa_name": org["lpa_name"],
        "doc_reference": d.get("reference",""),
        "doc_name": d.get("name",""),
        "doc_types": ";".join(doc_types),
        "file_kind": file_kind,
        "final_url": final_url,
        "landing_url": landing_url,
        "status": status,
        "content_type": ctype,
        "entry_date": d.get("entry-date",""),
        "local_plan": d.get("local-plan",""),
    })

if rows:
    with open("local_plan_documents_clean.csv","w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)
    print(f"wrote {len(rows)} rows")
else:
    print("No rows to write")
