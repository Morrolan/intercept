"""Shared explanations stay deployed and every navigation mode is explained."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_shared_copies():
    shared = ROOT.parent / 'ami' / 'shared'
    if not shared.exists():
        pytest.skip('Sibling AMI checkout is absent')
    targets = json.loads((shared / 'targets.json').read_text())
    copies = [(source, target.split(':', 1)[1])
              for source, destinations in targets.items()
              for target in destinations if target.startswith('intercept:')]
    assert copies, 'Intercept must consume the shared explanation engine'
    for source, destination in copies:
        assert (ROOT / destination).read_bytes() == (shared / source).read_bytes(), destination


def test_every_navigation_mode_has_an_explanation():
    nav = (ROOT / 'templates/partials/nav.html').read_text()
    modes = set(re.findall(r"(?:mode_item|mobile_item)\('([a-z_]+)'", nav))
    data = ROOT / 'static/js/core/explanations.js'
    assert data.exists(), 'Missing app-owned explanation catalogue'
    guide = json.loads(data.read_text().split('/* catalogue */', 1)[1].split('; /* end catalogue */', 1)[0])
    assert len(modes) >= 30
    for mode in modes:
        item = guide.get('mode-' + mode)
        assert item, mode
        assert all(item.get(field) for field in ('term', 'meaning', 'matters', 'notMeaning')), mode


def test_shared_engine_loaded_with_theme():
    head = (ROOT / 'templates/partials/ami_head.html').read_text()
    assert 'css/explain.css' in head
    assert head.index('js/core/explain.js') < head.index('js/core/explanations.js')
    assert head.index('js/ami-bridge.js') < head.index('js/core/explanations.js')
    assert 'data-explain="mode-{{ mode }}"' in (ROOT / 'templates/partials/nav.html').read_text()


def test_literal_explanation_targets_have_catalogue_entries():
    source = (ROOT / 'static/js/core/explanations.js').read_text()
    guide = json.loads(source.split('/* catalogue */', 1)[1].split('; /* end catalogue */', 1)[0])
    import html

    count = 0
    for path in (ROOT / 'templates').rglob('*.html'):
        for text in re.findall(r'data-explain-text="([^"\n]+)"', path.read_text()):
            if any(marker in text for marker in ('${', '{{', "' +", '" +', '{%')):
                continue
            text = html.unescape(text)
            assert 'title-' + text in guide or 'term-' + text in guide, (path, text)
            count += 1
    assert count >= 150
