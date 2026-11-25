"""Generate conservative product duplicate candidates for human review."""
from __future__ import annotations

import argparse
import itertools
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent
COLUMNS = ['group_id', 'keep_candidate', 'duplicate_candidate', 'original_ref', 'match_method', 'similarity_score', 'confidence', 'uom_conflict', 'reason', 'recommended_action']
NUMBER = r'(?:\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)'


def number(text: str) -> Decimal:
    if '-' in text:
        whole, fraction = text.split('-', 1)
        return Decimal(whole) + number(fraction)
    if '/' in text:
        numerator, denominator = text.split('/')
        return Decimal(numerator) / Decimal(denominator)
    return Decimal(text)


def reference(value: str) -> str:
    ref = value.strip().upper()
    match = re.fullmatch(r'(COIL-\d+-\d+-)(\d+\.\d+)', ref)
    if match:
        return match.group(1) + format(Decimal(match.group(2)).normalize(), 'f')
    return ref


def specs(row: dict) -> dict:
    ref = reference(row['internal_ref'])
    name = row['name'].upper()
    family_match = re.search(r'\b(ROUND|SQUARE|RECT(?:ANGLE|ANGULAR)?|COIL)\b', name)
    family = {'ROUND': 'RD', 'SQUARE': 'SQ', 'RECT': 'RC', 'RECTANGLE': 'RC', 'RECTANGULAR': 'RC', 'COIL': 'COIL'}.get(family_match.group(1), '') if family_match else ''
    result = {'family': family, 'cut': bool(re.search(r'\bCUT\b', name)), 'gauge': None, 'dims': (), 'wall': None, 'length': None, 'grade': None}
    gauge = re.search(r'\b(\d+)\s*GA\b', name)
    if gauge:
        result['gauge'] = int(gauge.group(1))
    # References encode dimensions in thousandths for tube products.
    parts = ref.split('-')
    if parts[0] in ('RD', 'SQ', 'RC') and len(parts) >= (5 if parts[0] == 'RC' else 4):
        try:
            count = 2 if parts[0] == 'RC' else 1
            result.update(family=parts[0], dims=tuple(Decimal(x) / 1000 for x in parts[1:1+count]), wall=Decimal(parts[1+count]) / 1000, length=Decimal(parts[2+count]), cut='CUT' in parts)
            suffix = parts[3 + count:]
            if len(suffix) == 2 and suffix[0] == 'CUT':
                result['length'] = Decimal(suffix[1])
        except (ValueError, ArithmeticError):
            pass
    elif parts[0] == 'COIL' and len(parts) == 4:
        try:
            result.update(family='COIL', grade=parts[1], wall=Decimal(parts[2]) / 1000, dims=(Decimal(parts[3]),))
        except ArithmeticError:
            pass
    # Parse description independently to detect conflicting source fields.
    cleaned = re.sub(r'\b\d+\s*GA\b', '', name)
    tokens = list(re.finditer('(' + NUMBER + r')\s*(FT|IN|"|OD|W)?', cleaned))
    values = [(number(m.group(1)), (m.group(2) or '').upper()) for m in tokens]
    if family in ('RD', 'SQ', 'RC') and values:
        dims_count = 2 if family in ('SQ', 'RC') else 1
        desc_dims = tuple(v for v, _ in values[:dims_count])
        if family == 'SQ' and len(desc_dims) == 2 and desc_dims[0] == desc_dims[1]:
            desc_dims = desc_dims[:1]
        if len(values) > dims_count:
            length = values[-1][0] * (12 if values[-1][1] == 'FT' else 1)
            desc_wall = values[-2][0] if len(values) > dims_count + 1 else None
        else:
            length, desc_wall = None, None
        result['description'] = {'dims': desc_dims, 'wall': desc_wall, 'length': length}
        if not result['dims']:
            result.update(dims=desc_dims, wall=desc_wall, length=length)
    return result


def contradictions(a: dict, b: dict) -> list:
    issues = []
    for key in ('family', 'dims', 'wall', 'length', 'grade'):
        if a.get(key) and b.get(key) and a[key] != b[key]:
            issues.append(key)
    if a['cut'] != b['cut']:
        issues.append('cut status')
    if a['gauge'] and b['gauge'] and a['gauge'] != b['gauge']:
        issues.append('gauge')
    return issues


def consistency(s: dict) -> int:
    desc = s.get('description', {})
    return -sum(bool(s.get(k) and desc.get(k) and s[k] != desc[k]) for k in ('dims', 'wall', 'length'))


def report(products: pd.DataFrame, ref_threshold: float = 90, name_threshold: float = 85) -> pd.DataFrame:
    required = ['product_id', 'internal_ref', 'name', 'uom', 'category', 'active']
    if missing := set(required) - set(products.columns):
        raise ValueError(f'Missing columns: {sorted(missing)}')
    records = products.fillna('').astype(str).to_dict('records')
    ids = [r['product_id'].strip() for r in records]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Product IDs must be present and unique')
    for r in records:
        r['_spec'] = specs(r)
        r['_ref'] = reference(r['internal_ref'])
    records.sort(key=lambda r: r['product_id'])
    rows = []
    for a, b in itertools.combinations(records, 2):
        sa, sb = a['_spec'], b['_spec']
        equal_ref = bool(a['_ref'] and a['_ref'] == b['_ref'])
        same_category = bool(a['category'].strip() and a['category'].strip().casefold() == b['category'].strip().casefold())
        same_family = bool(sa['family'] and sa['family'] == sb['family'])
        conflicts = contradictions(sa, sb)
        evidence = same_family and bool(sa['dims'] and sa['dims'] == sb['dims']) and bool(sa['length'] and sa['length'] == sb['length'] or sa['grade'] and sa['grade'] == sb['grade'])
        ref_score = fuzz.ratio(a['_ref'], b['_ref']) if a['_ref'] and b['_ref'] else 0
        name_score = fuzz.ratio(a['name'].upper(), b['name'].upper()) if a['name'] and b['name'] else 0
        fuzzy = same_category and same_family and evidence and (ref_score >= ref_threshold or name_score >= name_threshold)
        if not equal_ref and (conflicts or not same_category or not evidence):
            continue
        if not equal_ref and not (evidence or fuzzy):
            continue
        uom_conflict = bool(a['uom'].strip() and b['uom'].strip() and a['uom'].strip().casefold() != b['uom'].strip().casefold())
        internal = [r['product_id'] for r in (a, b) if consistency(r['_spec']) < 0]
        uncertain = bool(conflicts or internal or uom_conflict or not same_category or not evidence or (sa['gauge'] or sb['gauge']) and sa['gauge'] != sb['gauge'])
        def rank(r: dict) -> tuple:
            return (r['active'].strip().casefold() != 'true', -sum(bool(r[k].strip()) for k in ('internal_ref', 'name', 'uom', 'category')), -consistency(r['_spec']), r['product_id'])
        keep, duplicate = sorted((a, b), key=rank)
        reasons = []
        if equal_ref:
            reasons.append('matching normalized reference')
        if evidence:
            reasons.append('matching family and dimensions')
        if conflicts:
            reasons.append('conflicting ' + ', '.join(conflicts))
        if internal:
            reasons.append('reference and description differ for ' + ', '.join(internal))
        if (sa['gauge'] or sb['gauge']) and sa['gauge'] != sb['gauge']:
            reasons.append('gauge to thickness equivalence requires verification')
        if uom_conflict:
            reasons.append('conflicting UOM')
        if not same_category:
            reasons.append('category missing or conflicting')
        if not evidence:
            reasons.append('specifications incomplete or unverified')
        method = 'normalized_reference' if equal_ref else ('fuzzy_and_specifications' if fuzzy else 'specifications')
        rows.append(dict(group_id='|'.join((a['product_id'], b['product_id'])), keep_candidate=keep['product_id'], duplicate_candidate=duplicate['product_id'], original_ref=duplicate['internal_ref'], match_method=method, similarity_score=round(max(ref_score, name_score), 2) if method == 'fuzzy_and_specifications' else '', confidence='review' if uncertain else 'high', uom_conflict=uom_conflict, reason='; '.join(reasons), recommended_action='Verify specifications and UOM before any consolidation' if uncertain else 'Verify records before consolidation'))
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-threshold', type=float, default=90)
    parser.add_argument('--name-threshold', type=float, default=85)
    args = parser.parse_args()
    if not all(0 <= x <= 100 for x in (args.reference_threshold, args.name_threshold)):
        parser.error('thresholds must be between 0 and 100')
    products = pd.read_csv(ROOT / 'data/products.csv', dtype=str, keep_default_na=False)
    output = report(products, args.reference_threshold, args.name_threshold)
    path = ROOT / 'reports/product_duplicates.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False)
    print(f'{len(output)} candidate pairs written to {path}')
    print(output.to_string(index=False))


if __name__ == '__main__':
    main()
