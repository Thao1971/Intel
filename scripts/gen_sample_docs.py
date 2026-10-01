import os, re, json, time, requests, traceback
env = open("/app/backend/.env").read()
os.environ["JWT_SECRET"] = re.search(r'^JWT_SECRET="([^"]+)"', env, re.M).group(1)
import sys
sys.path.insert(0, "/app/backend")
from auth_utils import create_token
from pymongo import MongoClient

db = MongoClient('mongodb://localhost:27017')['arroba_agency_tool']
admin = db.users.find_one({"role": "admin"}, {"_id": 0, "id": 1, "email": 1})
JWT = create_token(admin["id"], admin.get("email") or "a@x")
H = {"Authorization": f"Bearer {JWT}"}
B = "http://localhost:8001/api/v1/docstudio"
OUT = "/app/frontend/public/muestras"
os.makedirs(OUT, exist_ok=True)
CIF = "B28031458"  # NCR ESPAÑA
PUB = "https://preview-arroba-app.preview.emergentagent.com/muestras"

jobs = [
    ("teaser", f"/compose/teaser?cif={CIF}"),
    ("valoracion_aproximada", f"/compose/valuation-approx?cif={CIF}"),
    ("valoracion_avanzada", f"/compose/valuation-advanced?cif={CIF}"),
    ("information_memorandum", f"/compose/information-memorandum?cif={CIF}"),
    ("sector_report_4650", "/compose/sector-report?cnae_code=4650"),
    ("oportunidades_MADRID", "/compose/opportunities?provincia=MADRID&limit=25"),
]

results = []


def log(msg):
    with open("/tmp/gen_docs.log", "a") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


open("/tmp/gen_docs.log", "w").close()
for name, path in jobs:
    rec = {"name": name}
    try:
        t0 = time.time()
        r = requests.post(B + path, headers=H, timeout=300)
        rec["compose_http"] = r.status_code
        if r.status_code != 200:
            rec["error"] = f"compose {r.status_code}: {r.text[:200]}"
            log(f"[{name}] COMPOSE FALLO {r.status_code}: {r.text[:160]}")
        else:
            d = r.json()
            did = d.get("document_id")
            rec["document_id"] = did
            rec["title"] = d.get("title")
            rec["sections"] = d.get("sections")
            rec["status"] = d.get("status")
            rec["compose_ms"] = int((time.time() - t0) * 1000)
            log(f"[{name}] compuesto doc={did} '{d.get('title')}' secciones={d.get('sections')} en {rec['compose_ms']}ms")
            t1 = time.time()
            rp = requests.get(f"{B}/export/{did}/pdf", headers=H, timeout=300)
            rec["export_http"] = rp.status_code
            if rp.status_code == 200 and rp.content[:4] == b"%PDF":
                open(f"{OUT}/{name}.pdf", "wb").write(rp.content)
                rec["pdf_bytes"] = len(rp.content)
                rec["url"] = f"{PUB}/{name}.pdf"
                rec["export_ms"] = int((time.time() - t1) * 1000)
                log(f"[{name}] PDF OK {len(rp.content)} bytes -> {rec['url']} ({rec['export_ms']}ms)")
            else:
                rec["error"] = f"export {rp.status_code}: {rp.text[:200] if rp.status_code != 200 else 'no-PDF'}"
                log(f"[{name}] EXPORT FALLO {rp.status_code}: {rp.text[:160]}")
    except Exception as e:
        rec["error"] = f"EXC {type(e).__name__}: {e}"
        log(f"[{name}] EXCEPCION: {e}\n{traceback.format_exc()[:400]}")
    results.append(rec)
    json.dump(results, open("/tmp/gen_docs.result.json", "w"), ensure_ascii=False, indent=2)

log("=== FIN ===")
