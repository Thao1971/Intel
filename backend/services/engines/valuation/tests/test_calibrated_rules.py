import asyncio
from copy import deepcopy

from services.engines.valuation.calibrated_rules import resolve_calibrated_sector_rule
from services.engines.valuation.calibration_promotion import activate_run, review_run


def nested(row, key):
    value=row
    for part in key.split('.'):
        value=value.get(part) if isinstance(value,dict) else None
    return value


def matches(row, query):
    for key, expected in query.items():
        actual=nested(row,key)
        if isinstance(expected,dict) and '$in' in expected:
            if actual not in expected['$in']: return False
        elif actual != expected: return False
    return True


class Cursor:
    def __init__(self,rows): self.rows=rows
    async def to_list(self,limit): return deepcopy(self.rows if limit is None else self.rows[:limit])


class Collection:
    def __init__(self,rows=None): self.rows=list(rows or [])
    async def find_one(self,q,projection=None):
        row=next((r for r in self.rows if matches(r,q)),None)
        return deepcopy(row) if row else None
    def find(self,q,projection=None): return Cursor([r for r in self.rows if matches(r,q)])
    async def update_one(self,q,u):
        row=next(r for r in self.rows if matches(r,q)); row.update(deepcopy(u.get('$set',{})))
    async def update_many(self,q,u):
        for row in self.rows:
            if matches(row,q): row.update(deepcopy(u.get('$set',{})))
    async def insert_one(self,row): self.rows.append(deepcopy(row))
    async def insert_many(self,rows,ordered=False): self.rows.extend(deepcopy(rows))


class DB:
    def __init__(self):
        self.valuation_sector_rules=Collection()
        self.valuation_sector_calibration_runs=Collection()
        self.valuation_sector_rule_candidates=Collection()
        self.valuation_sector_rule_versions=Collection()


def stats(a,b,c,n=100):
    return {'p25':a,'median':b,'p75':c,'sample_size':n}


def test_resolver_prefers_division_size_and_falls_back_by_parameter():
    db=DB()
    db.valuation_sector_rules.rows=[{
        'active':True,'cohort_key':'division:59|size:small',
        'ruleset_version':'sector-rules-2026-09-21-v1','effective_from':'2026-09-21',
        'parameters':{'revenue_growth':stats(.01,.04,.08),
                      'ebit_margin':stats(.05,.12,.20)},
    }]
    rule=asyncio.run(resolve_calibrated_sector_rule(db,'5915',5_000_000))
    assert rule['parameters']['revenue_growth']['median']==.04
    assert rule['parameters']['revenue_growth']['source']=='calibrated_iberinform'
    assert rule['parameters']['capex_pct_revenue']['median']==.04  # media seed fallback
    assert rule['calibration_status']=='calibrated_iberinform_partial'


def test_review_then_activate_is_explicit_and_versioned():
    db=DB()
    db.valuation_sector_calibration_runs.rows=[{
        'run_id':'run1','status':'candidate','cutoff_date':'2026-09-21',
        'pipeline_version':'sector-calibration-v1'}]
    db.valuation_sector_rule_candidates.rows=[{
        'run_id':'run1','cohort_key':'archetype:media_content|size:small',
        'scope':{'level':'archetype_size'},
        'quality':{'eligible_for_review':True},
        'parameters':{'revenue_growth':stats(.01,.04,.08)},
    }]
    asyncio.run(review_run(db,'run1',approver='Finance',notes='checked'))
    activated=asyncio.run(activate_run(
        db,'run1',approver='Finance',ruleset_version='sector-rules-2026-09-21-v1'))
    assert activated['status']=='active'
    assert db.valuation_sector_rules.rows[0]['active'] is True
    assert db.valuation_sector_rules.rows[0]['calibration_status']=='calibrated_iberinform'
    assert db.valuation_sector_calibration_runs.rows[0]['status']=='calibrated'


def test_activation_rejects_unreviewed_run():
    db=DB(); db.valuation_sector_calibration_runs.rows=[{'run_id':'run1','status':'candidate'}]
    try: asyncio.run(activate_run(db,'run1',approver='Finance'))
    except ValueError as exc: assert 'reviewed' in str(exc)
    else: raise AssertionError('unreviewed run activated')
