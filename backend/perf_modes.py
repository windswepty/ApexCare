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
        'summary': 'CPU 를 항상 최대 속도로 유지하고, 코어 절전과 USB 지연을 끕니다.',
        'plan': ss.PLAN_HIGH_PERF,
        'power': [
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, 'CPU 최소 속도 100%'),
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, 100, 'CPU 최대 속도 100%'),
            (ss.SUB_PROCESSOR, ss.CPMINCORES, 100, '코어 파킹 해제'),
            (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND, 0, 'USB 선택적 절전 끄기'),
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
        'summary': 'CPU 속도 상한을 낮추고 코어 절전을 켜서 발열과 소비 전력을 줄입니다.',
        'plan': ss.PLAN_POWER_SAVER,
        'power': [
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5, 'CPU 최소 속도 5%'),
            (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, 70, 'CPU 최대 속도 70%'),
            (ss.SUB_PROCESSOR, ss.CPMINCORES, 50, '코어 파킹 허용'),
        ],
        'registry': [],
    },
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


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
                  + (f", {len(reverted['failed'])}개 실패" if reverted['failed'] else ''),
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
                'name': f"전원 플랜 → {ss.KNOWN_PLANS.get(target_plan, target_plan)}",
                'ok': r['ok'], 'detail': '' if r['ok'] else r.get('reason', ''),
            })
        else:
            steps.append({'name': '전원 플랜 전환', 'ok': False,
                          'detail': '사용 가능한 플랜 없음'})

    # ── 3단계: 전원 세부값 (AC/DC 모두) ──────────────────────────
    for sub, setting, value, label in spec['power']:
        r = ss.set_power_value(sub, setting, value, group=MODE_GROUP,
                               plan=target_plan, label=label)
        steps.append({'name': label, 'ok': r['ok'],
                      'detail': '' if r['ok'] else r.get('reason', '')})

    # ── 4단계: 레지스트리 ────────────────────────────────────────
    for hive, path, name, value, label in spec['registry']:
        r = ss.set_registry(hive, path, name, value, group=MODE_GROUP, why=label)
        steps.append({'name': label, 'ok': r['ok'],
                      'detail': '' if r['ok'] else r.get('reason', '')})

    # ── 결과 집계 ────────────────────────────────────────────────
    applied = [s for s in steps if s['ok']]
    failed = [s for s in steps if not s['ok']]

    # 전원 플랜조차 못 바꿨으면 모드가 적용됐다고 말할 수 없다.
    # 표준 모드는 플랜을 바꾸지 않으므로 '되돌리기' 가 성공했는지가 기준이다.
    if spec['plan']:
        plan_step = next((s for s in steps if s['name'].startswith('전원 플랜')), None)
        plan_ok = bool(plan_step and plan_step['ok'])
    else:
        plan_ok = reverted['ok']
    success = plan_ok and not failed

    if persist and (success or plan_ok):
        try:
            from backend import config_manager
            config_manager.set_optimization_mode(mode, user_set=user_set)
        except Exception as e:
            log.warning(f'모드 저장 실패: {e}')

    if failed:
        msg = (f"{spec['label']} 모드를 적용했지만 {len(failed)}개 항목이 실패했습니다."
               if plan_ok else f"{spec['label']} 모드 적용에 실패했습니다.")
    else:
        msg = f"{spec['label']} 모드를 적용했습니다. ({len(applied)}개 항목)"

    log.info(f"[모드] {mode}: 성공 {len(applied)} 실패 {len(failed)}")

    return {
        'success': success,
        'partial': plan_ok and bool(failed),
        'mode': mode,
        'label': spec['label'],
        'message': msg,
        'steps': steps,
        'appliedCount': len(applied),
        'failedCount': len(failed),
        'notes': notes,
        'activePlan': ss.active_plan_guid(),
        'activePlanName': ss.KNOWN_PLANS.get(ss.active_plan_guid() or '', '알 수 없음'),
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

    if MODES[saved]['plan']:
        expected_plan, _ = _plan_fallback(MODES[saved]['plan'])
        in_sync = (active == expected_plan) if (active and expected_plan) else False
    else:
        # 표준은 특정 플랜이 정답이 아니다. 성능 모드가 남긴 변경이 없으면 맞는 상태다.
        expected_plan = None
        in_sync = not any(e.get('group') == MODE_GROUP for e in ss.pending_changes().values())

    return {
        'mode': saved,
        'label': MODES[saved]['label'],
        'userSet': user_set,
        'activePlan': active,
        'activePlanName': ss.KNOWN_PLANS.get(active or '', '알 수 없음'),
        'expectedPlan': expected_plan,
        # 앱 밖에서 전원 플랜이 바뀌었을 때 UI 가 사용자에게 알릴 수 있게 한다
        'inSync': in_sync,
        # 게임 부스트가 게임 동안만 게이밍 모드를 적용 중이면, 불일치 경고 대신 그 사실을 알린다
        'boostOverride': _boost_override(),
        'pendingChanges': len(ss.pending_changes()),
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
        changes = [label for *_, label in spec['power']]
        changes += [label for *_, label in spec['registry']]
        if spec['plan']:
            target, note = _plan_fallback(spec['plan'])
            plan_name = plans.get(target, ss.KNOWN_PLANS.get(spec['plan'], '?'))
            plan_available = spec['plan'] in plans
        else:
            note, plan_name, plan_available = None, '원래 플랜 유지', True
        out.append({
            'id': key,
            'label': spec['label'],
            'summary': spec['summary'],
            'planName': plan_name,
            'planAvailable': plan_available,
            'note': note,
            'changes': changes,
            'reversible': True,
        })
    return out
