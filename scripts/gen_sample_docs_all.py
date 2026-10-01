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
CIF = "B28031458"
PUB = "https://preview-arroba-app.preview.emergentagent.com/muestras"

jobs = [
    ("one_pager", f"/compose/one-pager?cif={CIF}"),
    ("perfil_empresa", f"/compose/company-profile?cif={CIF}"),
    ("investment_memo", f"/compose/investment-memo?cif={CIF}"),
    ("analisis_estrategico", f"/compose/strategic-analysis?cif={CIF}"),
    ("analisis_comparativo", f"/compose/comparative?cif={CIF}"),
    ("sucesion", f"/compose/succession?cif={CIF}"),
    ("company_snapshot", f"/compose/company-snapshot?cif={CIF}"),
    ("benchmark_sectorial_4650", "/compose/benchmark?cnae_code=4650"),
    ("benchmark_avanzado_4650", "/compose/benchmark-advanced?cnae_code=4650"),
    ("fragmentacion_G", "/compose/fragmentation?cnae_section=G"),
    ("rollup_G", "/compose/rollup?cnae_section=G"),
    ("ranking_MADRID", "/compose/ranking?provincia=MADRID&limit=25"),
]

LOG = "/tmp/gen_docs2.log"
RES = "/tmp/gen_docs2.result.json"
results = []


def log(msg):
    with open(LOG, "a") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


open(LOG, "w").close()
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
            rec.update(document_id=did, title=d.get("title"), sections=d.get("sections"), status=d.get("status"))
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
    json.dump(results, open(RES, "w"), ensure_ascii=False, indent=2)

log("=== FIN ===")
