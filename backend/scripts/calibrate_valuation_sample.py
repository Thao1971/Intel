"""Offline Iberinform TAB pilot for the valuation calibrator (no Mongo required)."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.engines.financial.metrics import build_series  # noqa: E402
from services.engines.valuation.calibration import calibrate_companies  # noqa: E402


def parse_number(value):
    try: return float(str(value).strip().replace(',', '.'))
    except (TypeError, ValueError): return None


def load_companies(folder: Path):
    identities={}
    with (folder/'Datos_GENERALES.tab').open(encoding='latin-1',newline='') as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            cif=(row.get('REG_NUMBER') or '').strip().upper()
            if cif:
                identities[cif]={'cif_normalized':cif,
                                 'cnae_code':(row.get('ACTIVITY_CODE') or '').strip()}
    accounts=defaultdict(dict)
    with (folder/'Datos_BALANCES.tab').open(encoding='latin-1',newline='') as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            cif=(row.get('REG_NUMBER') or '').strip().upper()
            try: year=int(row.get('BALANCE_SHEET_YEAR') or '')
            except ValueError: continue
            code=(row.get('BALANCE_SHEET_ITEM') or '').strip()
            value=parse_number(row.get('BALANCE_SHEET_ITEM_VALUE'))
            if cif in identities and code and value is not None:
                accounts[(cif,year)][code]=value
    documents=defaultdict(list)
    for (cif,year),values in accounts.items():
        documents[cif].append({'year':year,'basis':'individual','accounts':values})
    return [{**identity,'series':build_series(documents.get(cif,[]))}
            for cif,identity in identities.items()]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path)
    parser.add_argument('--cutoff-date',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=calibrate_companies(load_companies(args.folder),args.cutoff_date)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={k:result[k] for k in ('pipeline_version','cutoff_date','population_initial',
                                    'population_eligible','exclusions','data_quality_adjustments')}
    summary['cohorts']=len(result['cohorts'])
    summary['reviewable_cohorts']=sum(c['quality']['eligible_for_review'] for c in result['cohorts'])
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
