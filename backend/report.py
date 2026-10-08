"""
APEX CARE — PC 상태 보고서(HTML 한 장).

사양·드라이브·디스크 건강·부팅 시간·배터리와 이 앱이 바꿔 둔 설정을 한 파일로 저장한다. 수리를 맡기거나 다른 사람에게
상태를 보여 줄 때 쓴다. 측정한 값과 Windows 가 알려 준 값만 담고, 모르는 값은 '알 수 없음' 으로 둔다.
파일은 사용자가 저장 창에서 고른 곳에 새로 쓴다(외부 스크립트·글꼴 없이 한 파일로 열린다).
"""

import html
import logging
import os
from datetime import datetime

log = logging.getLogger('Report')

_CSS = """
body{font-family:'Malgun Gothic','Segoe UI',sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#111;background:#fff}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;border-bottom:2px solid #111;padding-bottom:4px}
.sub{color:#555;font-size:12px}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f3f3;width:32%}
.warn{color:#b45309;font-weight:bold}.bad{color:#b91c1c;font-weight:bold}.ok{color:#047857;font-weight:bold}
ul{margin:4px 0;padding-left:20px;font-size:13px}
"""


def _e(v, unknown='알 수 없음'):
    if v is None or v == '':
        return unknown
    return html.escape(str(v))


def _gb(v):
    return f'{v:,.1f} GB' if isinstance(v, (int, float)) else '알 수 없음'


def _bytes(b):
    if not isinstance(b, (int, float)):
        return '알 수 없음'
    return f'{b / 1e12:,.1f} TB' if b >= 1e12 else f'{b / 1e9:,.1f} GB'


def _rows(pairs):
    return '<table>' + ''.join(f'<tr><th>{_e(k)}</th><td>{v}</td></tr>' for k, v in pairs) + '</table>'


def build_html(data, now=None):
    """data: {'stats', 'disks', 'boots', 'battery', 'changes'} (각각 백엔드가 돌려준 값, 없으면 None)."""
    now = now or datetime.now()
    s = data.get('stats') or {}
    parts = [f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>PC 상태 보고서</title>'
             f'<style>{_CSS}</style></head><body>',
             '<h1>PC 상태 보고서</h1>',
             f'<div class="sub">APEX CARE 가 {now.strftime("%Y-%m-%d %H:%M")} 에 만든 보고서입니다. '
             '측정한 값과 Windows·디스크가 알려 준 값만 담았습니다.</div>']

    parts.append('<h2>사양</h2>')
    parts.append(_rows([
        ('Windows', _e(s.get('osInfo'))),
        ('프로세서', _e(s.get('cpuModel')) + (f" ({_e(s.get('cpuCores'))}코어 / {_e(s.get('cpuThreads'))}스레드)"
                                             if s.get('cpuCores') else '')),
        ('그래픽', _e(s.get('gpuModel'))),
        ('메모리', (f"설치 {_gb(s.get('ramInstalledGB'))} · " if s.get('ramInstalledGB') else '')
         + f"Windows 가 쓸 수 있는 용량 {_gb(s.get('ramTotalGB'))}"),
    ]))

    drives = s.get('drives') or []
    if drives:
        parts.append('<h2>드라이브</h2><table><tr><th>드라이브</th><td><b>사용 / 전체 (남은 용량)</b></td></tr>')
        for d in drives:
            pct = d.get('percent')
            cls = ' class="bad"' if isinstance(pct, (int, float)) and pct >= 90 else ''
            parts.append(f"<tr><th>{_e(d.get('label'))}{' (Windows)' if d.get('system') else ''}</th>"
                         f"<td{cls}>{_gb(d.get('usedGB'))} / {_gb(d.get('totalGB'))} "
                         f"({_gb(d.get('freeGB'))} 남음)</td></tr>")
        parts.append('</table>')

    dh = data.get('disks') or {}
    parts.append('<h2>디스크 건강</h2>')
    if not dh.get('ok'):
        parts.append(f"<p class=\"warn\">{_e(dh.get('error'), '디스크 정보를 읽지 못했습니다.')}</p>")
    for d in dh.get('disks') or []:
        health = d.get('health')
        cls = {'정상': 'ok', '주의': 'warn', '위험': 'bad'}.get(health, '')
        extra = d.get('nvme') or d.get('ata') or {}
        err = d.get('mediaErrors')
        if err is None and (d.get('readErrors') is not None or d.get('writeErrors') is not None):
            err = (d.get('readErrors') or 0) + (d.get('writeErrors') or 0)
        rows = [
            ('상태', f'<span class="{cls}">{_e(health)}</span>'),
            ('종류', _e(' · '.join(x for x in (d.get('media'), d.get('bus')) if x))),
            ('드라이브 문자', _e(' '.join(d.get('letters') or []), '없음')),
            ('수명 사용량', f"{d['wearPct']}%" if isinstance(d.get('wearPct'), (int, float)) else '알 수 없음'),
            ('온도', f"{d['temperatureC']}°C" if isinstance(d.get('temperatureC'), (int, float)) else '알 수 없음'),
            ('사용 시간', f"{int(d['powerOnHours']):,}시간" if isinstance(d.get('powerOnHours'), (int, float)) else '알 수 없음'),
            ('복구하지 못한 오류', f'{int(err):,}건' if isinstance(err, (int, float)) else '알 수 없음'),
            ('지금까지 쓴 양', _bytes(extra.get('dataWrittenBytes'))),
        ]
        for w in d.get('warnings') or []:
            rows.append(('디스크 경고', f'<span class="bad">{_e(w)}</span>'))
        parts.append(f"<h3>{_e(d.get('name'))}</h3>" + _rows(rows))

    bh = data.get('boots') or {}
    parts.append('<h2>부팅 시간 (Windows 가 잰 값)</h2>')
    boots = bh.get('boots') or []
    if boots:
        secs = [b['seconds'] for b in boots if isinstance(b.get('seconds'), (int, float))]
        parts.append(_rows([
            ('기록된 마지막 부팅', f"{_e((boots[0].get('at') or '')[:16].replace('T', ' '))} · {boots[0]['seconds']}초"),
            (f'평균 ({len(secs)}번)', f'{sum(secs) / len(secs):.1f}초' if secs else '알 수 없음'),
        ]))
    else:
        parts.append(f"<p>{_e(bh.get('note') or bh.get('error'), '기록된 부팅이 없습니다.')}</p>")
    if bh.get('stale'):
        parts.append(f"<p class=\"warn\">{_e(bh['stale'])}</p>")

    bt = data.get('battery') or {}
    if bt.get('batteries'):
        parts.append('<h2>배터리</h2>')
        for b in bt['batteries']:
            parts.append(_rows([
                ('이름', _e(b.get('name'))),
                ('건강 (완전 충전 / 설계 용량)', f"{b['healthPct']}%" if isinstance(b.get('healthPct'), int) else '알 수 없음'),
                ('충전 횟수', f"{b['cycles']:,}회" if isinstance(b.get('cycles'), int) else '알 수 없음'),
            ]))

    ch = data.get('changes')
    parts.append('<h2>APEX CARE 가 바꿔 둔 설정</h2>')
    if ch is None:
        parts.append('<p class="warn">변경 기록을 읽지 못했습니다.</p>')
    elif not ch:
        parts.append('<p>되돌릴 설정 변경이 없습니다(이 앱이 기록한 시스템 설정은 모두 원래 값입니다).</p>')
    else:
        items = sorted({str(e.get('why') or k) for k, e in ch.items() if isinstance(e, dict)})
        parts.append(f'<p>{len(items)}개 — APEX CARE 의 \'변경 내역 · 되돌리기\' 에서 원래대로 되돌릴 수 있습니다.</p><ul>'
                     + ''.join(f'<li>{_e(x)}</li>' for x in items[:50])
                     + (f'<li>외 {len(items) - 50}개</li>' if len(items) > 50 else '') + '</ul>')

    parts.append('</body></html>')
    return '\n'.join(parts)


def collect():
    from backend import health, system_monitor, system_state
    data = {}
    for key, fn in (('stats', system_monitor.get_system_stats), ('disks', health.disk_health),
                    ('boots', health.boot_history), ('battery', health.battery),
                    ('changes', system_state.pending_changes_or_none)):
        try:
            data[key] = fn()
        except Exception as e:
            log.warning(f'보고서 항목 {key} 을(를) 읽지 못했습니다: {e}')
            data[key] = None
    return data


def save(window):
    """저장 창을 띄워 고른 곳에 보고서를 쓴다. {'success', 'path', 'cancelled', 'message'}"""
    if window is None:
        return {'success': False, 'message': '창이 없어 저장 창을 띄울 수 없습니다.'}
    try:
        import webview
        name = f"PC 상태 보고서 {datetime.now().strftime('%Y-%m-%d')}.html"
        chosen = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name,
                                           file_types=('HTML 파일 (*.html)',))
    except Exception as e:
        return {'success': False, 'message': f'저장 창을 띄우지 못했습니다: {e}'}
    if isinstance(chosen, (list, tuple)):
        chosen = chosen[0] if chosen else None
    if not chosen:
        return {'success': False, 'cancelled': True, 'message': '저장을 취소했습니다.'}
    path = str(chosen)
    if not path.lower().endswith(('.html', '.htm')):
        path += '.html'
    text = build_html(collect())
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError as e:
        return {'success': False, 'message': f'보고서를 저장하지 못했습니다: {e}'}
    return {'success': True, 'path': path, 'message': f'보고서를 저장했습니다: {os.path.basename(path)}'}
