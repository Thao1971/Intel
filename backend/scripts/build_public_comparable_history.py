"""Build auditable annual international multiple history for Arroba."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / 'data/valuation/market/damodaran/archive'
OUTPUT = REPOSITORY_ROOT / 'data/valuation/market/damodaran/public_comparable_history_international_2020_2025.json'

ARCHETYPES = {
    'real_estate': {
        'label': 'Inmobiliario',
        'industries': {
            'Real Estate (Development)', 'Real Estate (General/Diversified)',
            'Real Estate (Operations & Services)', 'R.E.I.T.', 'Retail (REITs)'
        },
    },
    'media_content': {
        'label': 'Medios y publicidad',
        'industries': {'Advertising', 'Broadcasting', 'Entertainment', 'Publishing & Newspapers', 'Social Media'},
    },
    'construction': {
        'label': 'Construcción e ingeniería',
        'industries': {'Engineering/Construction', 'Construction Supplies'},
    },
    'energy_utilities': {
        'label': 'Energía',
        'industries': {'Electric Utility (Central)', 'Electric Utility (East)', 'Electric Utility (West)', 'Natural Gas (Distribution)', 'Power', 'Utility (General)', 'Utility (Water)', 'Green & Renewable Energy', 'Coal & Related Energy'},
    },
}

def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

def number(value: object) -> float | None:
    try:
        candidate = float(value)
        return candidate if candidate == candidate and candidate > 0 else None
    except (TypeError, ValueError):
        return None

def load_file(path: Path) -> pd.DataFrame:
    workbook = pd.ExcelFile(path)
    sheet_name = 'Industry Averages' if 'Industry Averages' in workbook.sheet_names else workbook.sheet_names[0]
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    header_row = next(index for index, row in raw.iterrows() if str(row.iloc[0]).replace(' ', '').strip() == 'IndustryName')
    header = raw.iloc[header_row].tolist()
    data = raw.iloc[header_row + 1:].copy()
    data.columns = header
    columns = []
    ev_ebitda_seen = 0
    for index, column in enumerate(data.columns):
        name = str(column).strip()
        if index == 0:
            columns.append('Industry Name')
        elif name == 'EV/EBITDA':
            ev_ebitda_seen += 1
            columns.append('ev_ebitda_positive' if ev_ebitda_seen == 1 else f'ev_ebitda_all_{ev_ebitda_seen}')
        elif name == 'Number of firms':
            columns.append('company_count')
        else:
            columns.append(f'{name}_{index}')
    data.columns = columns
    return data

def build_region(region: str, file_prefix: str) -> list[dict]:
    points: list[dict] = []
    for suffix in range(19, 25):
        path = SOURCE_ROOT / f'{file_prefix}{suffix}.xls'
        frame = load_file(path)
        as_of = f'{suffix + 2001}-01-05'
        for archetype, definition in ARCHETYPES.items():
            subset = frame[frame['Industry Name'].astype(str).isin(definition['industries'])]
            observations = []
            for _, row in subset.iterrows():
                multiple = number(row['ev_ebitda_positive'])
                companies = number(row['company_count'])
                if multiple is not None and companies is not None:
                    observations.append({
                        'industry': str(row['Industry Name']),
                        'multiple': round(multiple, 6),
                        'company_count': int(companies),
                    })
            if not observations:
                continue
            values = [item['multiple'] for item in observations]
            points.append({
                'as_of': as_of,
                'region': region,
                'archetype': archetype,
                'category': definition['label'],
                'metric': 'ev_ebitda',
                'median': round(median(values), 4),
                'p25': round(quantile(values, .25), 4),
                'p75': round(quantile(values, .75), 4),
                'subindustry_count': len(observations),
                'company_count': sum(item['company_count'] for item in observations),
                'observations': observations,
                'source_file': path.name,
            })
    return points

payload = {
    'history_version': 'public-comparable-history-v1',
    'provider': 'damodaran',
    'source': {
        'title': 'Archived Enterprise Value/EBITDA multiples by industry sector',
        'url': 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html',
        'cadence': 'annual',
        'retrieved_at': '2026-09-22',
        'methodology': 'Each category point is the median of the published aggregate EV/EBITDA multiples of its mapped subindustries. P25 and P75 measure dispersion across subindustries, not across individual companies.',
    },
    'coverage': {'regions': ['europe', 'united_states'], 'years': [2020, 2021, 2022, 2023, 2024, 2025]},
    'points': build_region('united_states', 'vebitda') + build_region('europe', 'vebitdaEurope'),
}
OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Wrote {len(payload["points"])} points to {OUTPUT}')
