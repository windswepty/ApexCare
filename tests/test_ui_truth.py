"""화면은 사실만 말한다: 실제로 바뀌지 않은 것을 바뀐 것처럼 보여 주지 않는다."""

import os
import re

from tests.conftest import ROOT


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_mode_is_switched_only_where_it_is_really_applied():
    # 헤더의 표준·게이밍·에코 스위치는 화면의 선택만 바꿔, '게이밍' 으로 보이는데 PC 는 에코로 돌았다.
    # 모드 표시를 바꾸는 곳은 실제로 적용(setOptimizationMode)하거나 백엔드에서 읽는(getOptimizationMode) 곳뿐이어야 한다.
    comp_dir = os.path.join(ROOT, 'src', 'components')
    for f in os.listdir(comp_dir):
        if not f.endswith('.jsx'):
            continue
        src = _read(os.path.join('src', 'components', f))
        if re.search(r'\bsetCurrentMode\(', src):
            assert 'setOptimizationMode' in src and 'getOptimizationMode' in src, f
    header = _read('src/components/Header.jsx')
    assert 'setCurrentMode' not in header and "'gaming'" not in header
    assert 'setCurrentMode=' not in re.search(r'<Header[^>]*>', _read('src/App.jsx'), re.S).group(0)
