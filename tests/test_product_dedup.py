"""Regression checks for product candidate matching."""
import runpy
from pathlib import Path

import pandas as pd
import pytest

matcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / '01_product_dedup.py'))


def row(identifier, ref, name, uom='Units', active='True'):
    return dict(product_id=identifier, internal_ref=ref, name=name, uom=uom, category='Finished Tube', active=active)


def test_missing_reference_and_conflicts():
    rows = [row('1', 'RD-0750-049-240', 'Round Tube 0.750 OD x 0.049 W x 240'),
            row('2', None, 'Round Tube 3/4 x 18ga x 20ft', 'lb'),
            row('3', None, 'Round Tube 7/8 x 18ga x 20ft')]
    result = matcher['report'](pd.DataFrame(rows))
    assert len(result) == 1
    assert result.iloc[0]['duplicate_candidate'] == '2'
    assert result.iloc[0]['uom_conflict']
    assert result.iloc[0]['confidence'] == 'review'


def test_cut_and_unsafe_chain():
    rows = [row('1', 'RD-1000-065-240', 'Round Tube 1 OD x 0.065 W x 240'),
            row('2', 'RD-1000-065-240', 'Round Tube 1 OD x 0.065 W x 240'),
            row('3', 'RD-1000-065-240-CUT-36', 'Round Tube 1 OD x 0.065 W cut 36')]
    result = matcher['report'](pd.DataFrame(rows))
    assert list(result['group_id']) == ['1|2']
    assert result.iloc[0]['keep_candidate'] == '1'
    assert result.equals(matcher['report'](pd.DataFrame(rows[::-1])))


def test_coil_decimal_and_active_keeper():
    rows = [dict(product_id='1', internal_ref='COIL-1008-065-3.390', name='Coil 1008 0.065 x 3.390 slit', uom='lb', category='Raw Material', active='False'),
            dict(product_id='2', internal_ref='coil-1008-065-3.39', name='Coil 16ga 3.39in slit', uom='lb', category='Raw Material', active='True')]
    result = matcher['report'](pd.DataFrame(rows))
    assert len(result) == 1
    assert result.iloc[0]['keep_candidate'] == '2'
    assert result.iloc[0]['confidence'] == 'review'


def test_normalized_reference_equality():
    name = 'Round Tube 1 OD x 0.065 W x 240'
    products = [row('A', ' rd-1000-065-240 ', name), row('B', 'RD-1000-065-240', name)]
    match, = matcher['report'](pd.DataFrame(products)).to_dict('records')
    assert match['match_method'] == 'normalized_reference'
    assert match['confidence'] == 'high'


def test_blank_references_alone_are_insufficient():
    products = [row('A', None, 'Unspecified tube'), row('B', ' ', 'Unspecified tube')]
    assert matcher['report'](pd.DataFrame(products)).empty


def test_incompatible_outside_diameters():
    products = [row('A', 'RD-1000-065-240', 'Round Tube 1 OD x 0.065 W x 240'),
                row('B', 'RD-1001-065-240', 'Round Tube 1.001 OD x 0.065 W x 240')]
    assert matcher['report'](pd.DataFrame(products)).empty


def test_different_finished_cut_lengths():
    products = [row(size, f'RD-1000-065-240-CUT-{size}', f'Round Tube 1 OD x 0.065 W cut {size}')
                for size in ('36', '48')]
    assert matcher['report'](pd.DataFrame(products)).empty


def test_conflicting_uom_requires_review_even_for_exact_reference():
    name = 'Round Tube 1 OD x 0.065 W x 240'
    products = [row('A', 'RD-1000-065-240', name), row('B', 'RD-1000-065-240', name, 'lb')]
    match, = matcher['report'](pd.DataFrame(products)).to_dict('records')
    assert match['uom_conflict']
    assert match['confidence'] == 'review'


def test_empty_product_catalog():
    empty = pd.DataFrame(columns=row('A', '', '').keys())
    result = matcher['report'](empty)
    assert result.empty
    assert {'keep_candidate', 'duplicate_candidate', 'match_method'} <= set(result.columns)


def test_missing_product_column():
    frame = pd.DataFrame([row('A', '', '')]).drop(columns='internal_ref')
    with pytest.raises(ValueError, match='internal_ref'):
        matcher['report'](frame)


def test_supplied_catalog_pairs():
    products = pd.read_csv(Path(__file__).resolve().parents[1] / 'data/products.csv', dtype=str)
    # Manual catalog crosswalk: case/spacing, decimal coil width, same rectangular
    # tube sold by different UOM, and 3/4 inch x 20 ft for the missing reference.
    expected = [('P001', 'P013'), ('P002', 'P014'), ('P003', 'P019'), ('P004', 'P017'),
                ('P005', 'P015'), ('P006', 'P018'), ('P007', 'P016')]
    pairs = matcher['report'](products)[['keep_candidate', 'duplicate_candidate']]
    assert sorted(tuple(sorted(pair)) for pair in pairs.itertuples(index=False, name=None)) == expected
