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


def test_no_invented_progress_or_remaining_time():
    # SFC·DISM·잔여물 정리는 진행률을 알려 주지 않는다. 예전에는 타이머로 %를 올리고 '예상 남은 시간' 을 셌다.
    comp_dir = os.path.join(ROOT, 'src', 'components')
    for f in os.listdir(comp_dir):
        if f.endswith('.jsx'):
            src = _read(os.path.join('src', 'components', f))
            assert not re.search(r'set\w*Progress\(\s*\w+\s*=>\s*\(\s*\w+\s*<\s*99', src), f
            assert '예상 남은 시간' not in src, f


def test_result_toasts_follow_the_result():
    storage = _read('src/components/StorageCenter.jsx')
    assert "st?.status === 'success'" in storage              # TRIM: 실패·진행 중을 '마쳤습니다' 로 보이지 않는다
    uninst = _read('src/components/Uninstaller.jsx')
    assert '완벽 삭제 및 잔여 파일 정리가 완료' not in uninst and 'failedCount > 0' in uninst


def test_descriptions_do_not_promise_what_the_code_does_not_do():
    # 잔여물 정리는 설치 폴더에 남은 폴더만 휴지통으로 보낸다(레지스트리는 건드리지 않는다).
    # SFC·DISM 은 시스템 파일 손상만 고친다. 블루스크린을 '원천 방지' 하지 않는다.
    assert '레지스트리 및 찌꺼기 파일까지 완벽하게' not in _read('src/components/Uninstaller.jsx')
    assert '원천 방지' not in _read('src/components/DriverUpdater.jsx')
