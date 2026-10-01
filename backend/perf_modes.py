"""
APEX CARE — 성능 모드 (표준 / 게이밍 / 에코).

기존 구현의 문제와 이 모듈이 바꾼 것:

1. 이전 모드가 지워지지 않았다.
   게이밍이 켠 NetworkThrottlingIndex 와 HwSchMode 를 표준·에코가 되돌리지 않아
   사용자 PC 에 여러 모드의 설정이 뒤섞였다. 실측으로 확인된 문제다.
   → 이제 모드 전환은 반드시 '이전 모드 되돌리기 → 새 모드 적용' 순서로 간다.

2. 표준 모드가 짐작한 기본값을 덮어썼다.
   PROCTHROTTLEMIN=5 같은 값을 '윈도우 기본값'이라 가정하고 썼는데,
   사용자가 직접 조정한 플랜이었다면 그 설정이 영구히 파괴된다.
   → 표준 모드는 이제 아무 값도 쓰지 않는다. 기록해둔 원본으로 되돌릴 뿐이다.

3. 하위 명령이 실패해도 성공이라고 보고했다.
   powercfg 20개가 전부 실패해도 "적용 완료" 토스트가 떴다.
   → 이제 항목별 성패를 모아 그대로 돌려준다. 호출부가 숨기지 않는 한 사용자가 본다.

4. HwSchMode(하드웨어 가속 GPU 스케줄링)를 몰래 켰다.
   재부팅해야 적용되고, 일부 GPU·드라이버에서 불안정을 일으키며, 복구 수단이 없었다.
   → 모드에서 제외했다. 위험 대비 이득이 불확실한 변경을 고지 없이 넣지 않는다.

5. 코어 파킹과 USB 설정을 AC 에만 적용했다.
   노트북을 배터리로 쓰면 게이밍 모드가 절반만 걸렸다.
   → system_state.set_power_value 가 AC/DC 를 함께 적용한다.
"""

import ctypes
import logging

from backend import system_state as ss

log = logging.getLogger('PerfModes')

MODE_GROUP = 'perf_mode'      # 이 그룹의 변경만 모드 전환 시 되돌린다

# 숫자 값을 사람이 읽을 수 있게. 적용 결과에 '이전 → 지금' 으로 보여 준다.
BOOST_NAMES = {0: '끔(기본 클럭까지만)', 1: '켬', 2: '공격적', 3: '효율적', 4: '효율적 공격적',
               5: '공격적(보장 클럭)', 6: '효율적 공격적(보장 클럭)'}
ASPM_NAMES = {0: '끔', 1: '보통 절전', 2: '최대 절전'}
ONOFF_NAMES = {0: '끔', 1: '켬'}
PERCENT = '%'

MODES = {
    'standard': {
        'label': '표준',
        'summary': '이 앱의 성능 모드가 바꾼 설정을 모두 원래대로 되돌립니다. 새로 바꾸는 것은 없습니다.',
        # 전원 플랜도 바꾸지 않는다. 예전에는 '균형 조정' 으로 전환했는데, 사용자가
        # 원래 고성능 플랜을 쓰고 있었다면 '표준 = 원상복구' 라는 설명과 달리
        # 새 변경을 만드는 셈이었다. 복구가 곧 표준이다.
        'plan': None,
        'power': [],
        'registry': [],
    },
    'gaming': {
        'label': '게이밍',
        'summary': 'CPU 부스트를 가장 공격적으로 쓰고 클럭을 높게 유지합니다. 코어·PCIe·USB 절전을 꺼서 '
                   '깨어나는 지연을 없앱니다. 발열과 소비 전력은 늘어납니다.',
        'plan': ss.PLAN_HIGH_PERF,
        'power': [
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, 'CPU 최소 속도 100%', PERCENT),
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, 100, 'CPU 최대 속도 100%', PERCENT),
            (ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, 2, 'CPU 부스트 공격적으로', BOOST_NAMES),
            (ss.SUB_PROCESSOR, ss.PERFEPP, 0, 'CPU 성능 우선 (EPP 0)', PERCENT),
            (ss.SUB_PROCESSOR, ss.CPMINCORES, 100, '코어 파킹 해제', PERCENT),
            (ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, 0, 'PCIe 절전 끄기 (그래픽카드 지연 감소)', ASPM_NAMES),
            (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND, 0, 'USB 선택적 절전 끄기', ONOFF_NAMES),
        ],
        'registry': [
            # MMCSS 가 배경 작업에 예약하는 CPU 비율. 낮출수록 게임에 더 간다.
            # 0 으로 내리면 오디오 스레드까지 굶어 소리가 끊길 수 있어 10 을 쓴다.
            ('HKLM', r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile',
             'SystemResponsiveness', 10, 'MMCSS 배경 예약 축소'),
            ('HKLM', r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile',
             'NetworkThrottlingIndex', 0xFFFFFFFF, '네트워크 스로틀링 해제'),
        ],
    },
    'eco': {
        'label': '에코',
        'summary': 'CPU 부스트를 끄고 속도 상한을 낮춰 발열·소음·소비 전력을 확실히 줄입니다. '
                   '무거운 작업과 게임은 느려집니다.',
        'plan': ss.PLAN_POWER_SAVER,
        'power': [
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5, 'CPU 최소 속도 5%', PERCENT),
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, 70, 'CPU 최대 속도 70%', PERCENT),
            (ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, 0, 'CPU 부스트 끄기 (기본 클럭까지만)', BOOST_NAMES),
            (ss.SUB_PROCESSOR, ss.PERFEPP, 80, 'CPU 효율 우선 (EPP 80)', PERCENT),
            (ss.SUB_PROCESSOR, ss.CPMINCORES, 50, '코어 파킹 허용', PERCENT),
            (ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, 2, 'PCIe 최대 절전', ASPM_NAMES),
            (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND, 1, 'USB 선택적 절전 켜기', ONOFF_NAMES),
        ],
        'registry': [],
    },
}


def _fmt(v, names):
    if v is None:
        return '알 수 없음'
    if names == PERCENT:
        return f'{v}%'
    if isinstance(names, dict):
        return names.get(v, str(v))
    return str(v)


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def plan_name(guid, plans=None):
    """전원 플랜 이름. 이 PC 에 등록된 이름(사용자·제조사 플랜 포함)을 먼저 쓴다.

    예전에는 Windows 기본 플랜 4개만 이름을 알아서, 제조사 플랜이나 사용자가 만든 플랜을
    쓰면 '알 수 없음' 으로 보였다.
    """
    if not guid:
        return '알 수 없음'
    if plans is None:
        try:
            plans = ss.available_plans()
        except Exception:
            plans = {}
    name = plans.get(guid)
    if name and name != guid:
        return name
    return ss.KNOWN_PLANS.get(guid, name or '알 수 없음')


def _plan_fallback(wanted):
    """원하는 플랜이 없으면 대안을 고른다.

    Modern Standby 노트북에는 고성능·절전 플랜이 아예 없다. 그런 기기에서
    플랜 전환에 실패했다고 모드 적용 전체를 포기하면 안 된다. 세부 전원값만으로도
    상당 부분 효과가 있으므로 균형 플랜 위에 적용하고 그 사실을 알린다.
    """
    plans = ss.available_plans()
    if wanted in plans:
        return wanted, None
    if ss.PLAN_BALANCED in plans:
        return ss.PLAN_BALANCED, (
            f"이 PC 에는 '{ss.KNOWN_PLANS.get(wanted, wanted)}' 전원 플랜이 없어 "
            f"'균형 조정' 위에 세부 설정만 적용했습니다.")
    return (next(iter(plans)) if plans else None,
            '사용 가능한 전원 플랜을 찾지 못했습니다.')


def apply_mode(mode, user_set=True, persist=True):
    """성능 모드를 적용한다.

    반환값에 항목별 성패가 그대로 들어간다. 호출부는 이것을 사용자에게 보여줘야 한다.
    persist=False 는 '저장된 모드' 를 바꾸지 않는다. 게임 부스트가 게임 동안만
    게이밍 모드를 쓰고 끝나면 사용자가 쓰던 모드로 돌아가기 위한 것이다.
    """
    if mode not in MODES:
        return {'success': False, 'error': 'UNKNOWN_MODE',
                'message': f'알 수 없는 모드입니다: {mode}'}

    if not is_admin():
        return {'success': False, 'error': 'UAC_REQUIRED',
                'message': '성능 모드를 바꾸려면 관리자 권한으로 실행해야 합니다.'}

    spec = MODES[mode]
    steps = []
    notes = []

    # ── 1단계: 이전 모드가 남긴 변경을 먼저 되돌린다 ──────────────
    # 이게 빠지면 모드가 겹쳐 쌓인다. 기존 구현의 핵심 결함이었다.
    reverted = ss.restore_group(MODE_GROUP)
    steps.append({
        'name': '이전 모드 설정 되돌리기',
        'ok': reverted['ok'],
        'detail': f"{reverted['restored']}개 항목 복구"
                  + (f", {len(reverted['failed'])}개 실패 — {reverted['failed'][0].get('reason', '')}"
                     if reverted['failed'] else ''),
        'failures': reverted['failed'],
    })
    if reverted['failed']:
        notes.append('일부 이전 설정을 되돌리지 못했습니다. 관리자 권한을 확인하세요.')

    # ── 2단계: 전원 플랜 ──────────────────────────────────────────
    target_plan = None
    if spec['plan']:
        target_plan, fallback_note = _plan_fallback(spec['plan'])
        if fallback_note:
            notes.append(fallback_note)

        if target_plan:
            r = ss.set_active_plan(target_plan, group=MODE_GROUP, why=f'{spec["label"]} 모드')
            steps.append({
                'name': f"전원 플랜 → {plan_name(target_plan)}",
                'ok': r['ok'], 'detail': '' if r['ok'] else r.get('reason', ''),
            })
        else:
            steps.append({'name': '전원 플랜 전환', 'ok': False,
                          'detail': '사용 가능한 플랜 없음'})

    # ── 3단계: 전원 세부값 (AC/DC 모두) ──────────────────────────
    for sub, setting, value, label, names in spec['power']:
        r = ss.set_power_value(sub, setting, value, group=MODE_GROUP,
                               plan=target_plan, label=label)
        if r.get('unsupported'):
            # 이 PC 에 없는 설정이다. 바꾼 것이 없으니 실패도 성공도 아니다. 사실대로 '건너뜀' 으로 알린다.
            steps.append({'name': label, 'ok': True, 'skipped': True,
                          'detail': '이 PC 에는 없는 설정이라 건너뛰었습니다'})
            continue
        steps.append({'name': label, 'ok': r['ok'],
                      'detail': (f"{_fmt(r.get('before'), names)} → {_fmt(value, names)}" if r['ok']
                                 else r.get('reason', ''))})

    # ── 4단계: 레지스트리 ────────────────────────────────────────
    for hive, path, name, value, label in spec['registry']:
        r = ss.set_registry(hive, path, name, value, group=MODE_GROUP, why=label)
        steps.append({'name': label, 'ok': r['ok'],
                      'detail': '' if r['ok'] else r.get('reason', '')})

    # ── 결과 집계 ────────────────────────────────────────────────
    applied = [s for s in steps if s['ok'] and not s.get('skipped')]
    skipped = [s for s in steps if s.get('skipped')]
    failed = [s for s in steps if not s['ok']]

    # 전원 플랜조차 못 바꿨으면 모드가 적용됐다고 말할 수 없다.
    # 표준 모드는 플랜을 바꾸지 않으므로 '되돌리기' 가 성공했는지가 기준이다.
    if spec['plan']:
        plan_step = next((s for s in steps if s['name'].startswith('전원 플랜')), None)
        plan_ok = bool(plan_step and plan_step['ok'])
    else:
        plan_ok = reverted['ok']
    success = plan_ok and not failed
    partial = plan_ok and bool(failed)
    if not spec['plan']:
        # 표준 = 되돌리기. 일부만 되돌렸어도 사용자는 표준을 골랐으므로 표준으로 기록하고,
        # 남은 설정은 get_mode() 가 'leftover' 로 알린다. 예전에는 하나만 실패해도 저장된 모드가
        # 게이밍으로 남아 '게이밍인데 전원 플랜이 다르다' 는 엉뚱한 안내가 떴다.
        partial = bool(reverted['failed']) and reverted['restored'] > 0

    if persist and (success or plan_ok or not spec['plan']):
        try:
            from backend import config_manager
            config_manager.set_optimization_mode(mode, user_set=user_set)
        except Exception as e:
            log.warning(f'모드 저장 실패: {e}')

    if not spec['plan']:
        n_ok, n_fail = reverted['restored'], len(reverted['failed'])
        if n_fail:
            msg = (f"성능 모드가 바꾼 설정 {n_fail}개를 되돌리지 못했습니다"
                   + (f" ({n_ok}개는 되돌렸습니다)." if n_ok else "."))
        elif n_ok:
            msg = f"표준 모드로 돌아왔습니다. 성능 모드가 바꾼 설정 {n_ok}개를 원래대로 되돌렸습니다."
        else:
            msg = "표준 모드입니다. 되돌릴 성능 모드 설정이 없었습니다."
    elif failed:
        msg = (f"{spec['label']} 모드를 적용했지만 {len(failed)}개 항목이 실패했습니다."
               if plan_ok else f"{spec['label']} 모드 적용에 실패했습니다.")
    else:
        msg = f"{spec['label']} 모드를 적용했습니다. ({len(applied)}개 항목"
        msg += f", 이 PC 에 없는 {len(skipped)}개 건너뜀)" if skipped else ")"

    log.info(f"[모드] {mode}: 성공 {len(applied)} 실패 {len(failed)}")

    return {
        'success': success,
        'partial': partial,
        'mode': mode,
        'label': spec['label'],
        'message': msg,
        'steps': steps,
        'appliedCount': len(applied),
        'skippedCount': len(skipped),
        'failedCount': len(failed),
        'notes': notes,
        'activePlan': ss.active_plan_guid(),
        'activePlanName': plan_name(ss.active_plan_guid()),
    }


def get_mode():
    """현재 모드를 돌려준다.

    전원 플랜 GUID 만 보고 판정하던 기존 방식은 틀린다. 게이밍이 '최고의 성능'
    플랜을 쓰면 그 GUID 를 몰라 '표준'으로 읽혔고, 사용자가 윈도우에서 직접 플랜을
    바꾸면 앱의 기록과 어긋났다.
    → 저장된 모드를 정답으로 삼되, 실제 시스템 상태와 어긋나면 그 사실을 함께 알린다.
    """
    active = ss.active_plan_guid()
    saved = None
    user_set = False
    try:
        from backend import config_manager
        saved = config_manager.get_optimization_mode()
        user_set = config_manager.get_optimization_mode_user_set()
    except Exception:
        pass

    if saved not in MODES:
        saved = 'standard'

    pending = ss.pending_changes()
    left_over = sum(1 for e in pending.values() if e.get('group') == MODE_GROUP)
    if MODES[saved]['plan']:
        expected_plan, _ = _plan_fallback(MODES[saved]['plan'])
        in_sync = (active == expected_plan) if (active and expected_plan) else False
        # 화면이 '무엇이 어긋났는지' 를 사실대로 말하게 한다
        out_of_sync = None if in_sync else 'plan'
    else:
        # 표준은 특정 플랜이 정답이 아니다. 성능 모드가 남긴 변경이 없으면 맞는 상태다.
        # 이때 어긋남은 전원 플랜이 아니라 되돌리지 못한 성능 모드 설정이다.
        expected_plan = None
        in_sync = left_over == 0
        out_of_sync = None if in_sync else 'leftover'

    return {
        'mode': saved,
        'label': MODES[saved]['label'],
        'userSet': user_set,
        'activePlan': active,
        'activePlanName': plan_name(active),
        'expectedPlan': expected_plan,
        'expectedPlanName': plan_name(expected_plan) if expected_plan else None,
        # 앱 밖에서 전원 플랜이 바뀌었을 때 UI 가 사용자에게 알릴 수 있게 한다
        'inSync': in_sync,
        'outOfSync': out_of_sync,              # None | 'plan' | 'leftover'
        'leftoverModeChanges': left_over,
        # 게임 부스트가 게임 동안만 게이밍 모드를 적용 중이면, 불일치 경고 대신 그 사실을 알린다
        'boostOverride': _boost_override(),
        'pendingChanges': len(pending),
    }


def _boost_override():
    try:
        from backend import game_booster
        return game_booster.power_mode_overridden()
    except Exception:
        return False


def revert_everything():
    """이 앱이 바꾼 모든 시스템 설정을 원래대로. 사용자가 언제든 누를 수 있어야 한다.

    system_state 저널을 전부 되돌리고, 구버전이 settings.json 에 따로 남긴 백업
    (네트워크 튜닝, 하드웨어 튜닝 서비스 설정)이 있으면 그것도 되돌린다.

    예전에는 구버전 복구 함수를 무조건 불렀고, 그 함수들은 백업이 없으면
    'Windows 기본값' 을 추측해 써넣었다. 그래서 그 기능을 한 번도 쓰지 않은 사용자가
    '전부 원래대로' 를 누르면 일부러 꺼 둔 Windows Search 가 다시 켜지고, 모든
    네트워크 어댑터의 Nagle 설정이 지워졌다. 복구 버튼이 새 변경을 만든 것이다.
    """
    if not is_admin():
        return {'success': False, 'error': 'UAC_REQUIRED',
                'message': '되돌리려면 관리자 권한이 필요합니다.'}

    parts = []
    # 저널이 먼저다. 구버전 백업은 저널보다 오래된 원본이므로 뒤에서 덮어쓰는 게 맞다.
    r = ss.restore_all()
    parts.append({'name': '시스템 설정 (성능 모드·튜닝·부스트)', 'ok': r['ok'],
                  'detail': f"{r['restored']}개 복구"
                            + (f", {len(r['failed'])}개 실패" if r['failed'] else ''),
                  'restored': r['restored'], 'failed': r['failed']})

    from backend import system_repair, optimizer
    if system_repair.has_legacy_network_backup():
        try:
            n = system_repair.restore_network_tweaks()
            parts.append({'name': '구버전 네트워크 튜닝', 'ok': bool(n.get('success')),
                          'detail': n.get('message', '')})
        except Exception as e:
            parts.append({'name': '구버전 네트워크 튜닝', 'ok': False, 'detail': str(e)})

    if optimizer.has_legacy_service_backup():
        try:
            s = optimizer.restore_legacy_service_backup()
            parts.append({'name': '구버전 서비스 시작 설정', 'ok': bool(s.get('success')),
                          'detail': s.get('message', '')})
        except Exception as e:
            parts.append({'name': '구버전 서비스 시작 설정', 'ok': False, 'detail': str(e)})

    # 성능 모드 기록을 '표준' 으로. 저널을 비웠으니 실제 상태도 모드가 없는 상태다.
    try:
        from backend import config_manager
        config_manager.set_optimization_mode('standard', user_set=False)
    except Exception:
        pass

    failed_parts = [p for p in parts if not p['ok']]
    ok = not failed_parts
    total = r['restored']
    return {
        'success': ok,
        'message': (f"{total}개 설정을 원래대로 되돌렸습니다." if ok else
                    f"{total}개 복구했지만 {len(failed_parts)}개 영역에서 실패가 있습니다. "
                    "실패한 항목은 기록에 남아 다시 시도할 수 있습니다."),
        'restored': total,
        'failed': r['failed'],
        'parts': parts,
    }


def list_modes():
    """UI 가 카드를 그리는 데 쓸 모드 목록. 무엇이 바뀌는지 미리 보여주기 위한 것."""
    plans = ss.available_plans()
    out = []
    for key, spec in MODES.items():
        changes = [p[3] for p in spec['power']]
        changes += [label for *_, label in spec['registry']]
        if spec['plan']:
            target, note = _plan_fallback(spec['plan'])
            pname = plan_name(target, plans) if target else '사용 가능한 플랜 없음'
            plan_available = spec['plan'] in plans
        else:
            note, pname, plan_available = None, '원래 플랜 유지', True
        out.append({
            'id': key,
            'label': spec['label'],
            'summary': spec['summary'],
            'planName': pname,
            'planAvailable': plan_available,
            'note': note,
            'changes': changes,
            'reversible': True,
        })
    return out
