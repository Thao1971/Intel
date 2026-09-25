import asyncio
from copy import deepcopy

from services.engines.valuation.company_inputs import normalize_patch, save_company_inputs


class Collection:
    def __init__(self, rows=None): self.rows=list(rows or [])
    async def find_one(self, query, projection=None):
        if "$or" in query:
            row=next((r for r in self.rows if any(r.get(k)==v for clause in query["$or"] for k,v in clause.items())),None)
        else:
            row=next((r for r in self.rows if all(r.get(k)==v for k,v in query.items())),None)
        return deepcopy(row) if row else None
    async def update_one(self, query, update, upsert=False):
        row=next((r for r in self.rows if all(r.get(k)==v for k,v in query.items())),None)
        if row is None:
            row=dict(query); self.rows.append(row)
            row.update(update.get("$setOnInsert",{}))
        row.update(deepcopy(update.get("$set",{})))
    async def insert_one(self, row): self.rows.append(deepcopy(row))


class DB:
    def __init__(self):
        self.master_companies=Collection([{"master_id":"m1","cif_normalized":"B1"}])
        self.valuation_company_inputs=Collection()
        self.valuation_input_audit=Collection()


def test_normalize_rejects_percentages_outside_contract():
    try: normalize_patch({"recurring_revenue_pct":80})
    except ValueError as exc: assert "between 0 and 1" in str(exc)
    else: raise AssertionError("invalid percentage accepted")


def test_save_projects_to_master_and_preserves_audit():
    db=DB()
    result=asyncio.run(save_company_inputs(
        db,"B1",{"recurring_revenue_pct":.8,"key_person_dependency":False},
        source_type="data_room",source_reference="QofE-2026.pdf",notes="Reviewed",
        actor="arroba"))
    assert result["values"]=={"recurring_revenue_pct":.8,"key_person_dependency":False}
    assert db.master_companies.rows[0]["valuation_inputs"]==result["values"]
    assert db.master_companies.rows[0]["valuation_inputs_evidence"]["recurring_revenue_pct"]["source_type"]=="data_room"
    assert db.valuation_input_audit.rows[0]["previous_values"]=={}
    assert db.valuation_input_audit.rows[0]["source_reference"]=="QofE-2026.pdf"


def test_null_explicitly_clears_previous_value():
    db=DB()
    asyncio.run(save_company_inputs(db,"m1",{"largest_customer_pct":.4},
        source_type="due_diligence",source_reference=None,notes=None,actor="arroba"))
    result=asyncio.run(save_company_inputs(db,"m1",{"largest_customer_pct":None},
        source_type="advisor_review",source_reference=None,notes="Withdrawn",actor="arroba"))
    assert "largest_customer_pct" not in result["values"]
    assert len(db.valuation_input_audit.rows)==2
