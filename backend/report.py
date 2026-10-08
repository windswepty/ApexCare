"""
APEX CARE — PC 상태 보고서(HTML 한 장).

사양·드라이브·디스크 건강·부팅 시간·배터리와 이 앱이 바꿔 둔 설정을 한 파일로 저장한다. 수리를 맡기거나 다른 사람에게
상태를 보여 줄 때 쓴다. 측정한 값과 Windows 가 알려 준 값만 담고, 모르는 값은 '알 수 없음' 으로 둔다.
파일은 사용자가 저장 창에서 고른 곳에 새로 쓴다(외부 스크립트·글꼴 없이 한 파일로 열린다).
화면이 영어면 보고서도 영어로 쓴다. 이 파일의 문구는 두 언어를 함께 적고, 백엔드가 준 문장(경고·안내·변경 이름)은
화면과 같은 사전(backend/ui_text)으로 바꾼다.
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


def build_html(data, now=None, lang='ko'):
    """data: {'stats', 'disks', 'boots', 'battery', 'changes'} (각각 백엔드가 돌려준 값, 없으면 None).
    lang: 'ko' | 'en'."""
    from backend.ui_text import translate
    en = lang == 'en'

    def t(ko, english):
        return english if en else ko

    unknown_text = t('알 수 없음', 'Unknown')

    def _e(v, unknown=None):
        if v is None or v == '':
            return html.escape(unknown if unknown is not None else unknown_text)
        return html.escape(translate(str(v), lang))

    def _gb(v):
        return f'{v:,.1f} GB' if isinstance(v, (int, float)) else unknown_text

    def _bytes(b):
        if not isinstance(b, (int, float)):
            return unknown_text
        return f'{b / 1e12:,.1f} TB' if b >= 1e12 else f'{b / 1e9:,.1f} GB'

    def _rows(pairs):
        return '<table>' + ''.join(f'<tr><th>{html.escape(k)}</th><td>{v}</td></tr>' for k, v in pairs) + '</table>'

    now = now or datetime.now()
    s = data.get('stats') or {}
    title = t('PC 상태 보고서', 'PC status report')
    parts = [f'<!doctype html><html lang="{"en" if en else "ko"}"><head><meta charset="utf-8"><title>{title}</title>'
             f'<style>{_CSS}</style></head><body>',
             f'<h1>{title}</h1>',
             '<div class="sub">' + t(f'APEX CARE 가 {now.strftime("%Y-%m-%d %H:%M")} 에 만든 보고서입니다. '
                                     '측정한 값과 Windows·디스크가 알려 준 값만 담았습니다.',
                                     f'Created by APEX CARE on {now.strftime("%Y-%m-%d %H:%M")}. '
                                     'It contains only measured values and values reported by Windows and the disks.')
             + '</div>']

    parts.append(f"<h2>{t('사양', 'Specifications')}</h2>")
    cores = ''
    if s.get('cpuCores'):
        cores = t(f" ({_e(s.get('cpuCores'))}코어 / {_e(s.get('cpuThreads'))}스레드)",
                  f" ({_e(s.get('cpuCores'))} cores / {_e(s.get('cpuThreads'))} threads)")
    installed = ''
    if s.get('ramInstalledGB'):
        installed = t(f"설치 {_gb(s.get('ramInstalledGB'))} · ", f"{_gb(s.get('ramInstalledGB'))} installed · ")
    parts.append(_rows([
        ('Windows', _e(s.get('osInfo'))),
        (t('프로세서', 'Processor'), _e(s.get('cpuModel')) + cores),
        (t('그래픽', 'Graphics'), _e(s.get('gpuModel'))),
        (t('메모리', 'Memory'), installed + t(f"Windows 가 쓸 수 있는 용량 {_gb(s.get('ramTotalGB'))}",
                                            f"{_gb(s.get('ramTotalGB'))} usable by Windows")),
    ]))

    drives = s.get('drives') or []
    if drives:
        parts.append(f"<h2>{t('드라이브', 'Drives')}</h2><table><tr><th>{t('드라이브', 'Drive')}</th>"
                     f"<td><b>{t('사용 / 전체 (남은 용량)', 'Used / total (free)')}</b></td></tr>")
        for d in drives:
            pct = d.get('percent')
            cls = ' class="bad"' if isinstance(pct, (int, float)) and pct >= 90 else ''
            free = t(f"({_gb(d.get('freeGB'))} 남음)", f"({_gb(d.get('freeGB'))} free)")
            parts.append(f"<tr><th>{_e(d.get('label'))}{' (Windows)' if d.get('system') else ''}</th>"
                         f"<td{cls}>{_gb(d.get('usedGB'))} / {_gb(d.get('totalGB'))} {free}</td></tr>")
        parts.append('</table>')

    dh = data.get('disks') or {}
    parts.append(f"<h2>{t('디스크 건강', 'Disk health')}</h2>")
    if not dh.get('ok'):
        parts.append(f"<p class=\"warn\">{_e(dh.get('error'), t('디스크 정보를 읽지 못했습니다.', 'Could not read disk information.'))}</p>")
    for d in dh.get('disks') or []:
        health = d.get('health')
        cls = {'정상': 'ok', '주의': 'warn', '위험': 'bad'}.get(health, '')
        extra = d.get('nvme') or d.get('ata') or {}
        err = d.get('mediaErrors')
        if err is None and (d.get('readErrors') is not None or d.get('writeErrors') is not None):
            err = (d.get('readErrors') or 0) + (d.get('writeErrors') or 0)
        hours = d.get('powerOnHours')
        rows = [
            (t('상태', 'Status'), f'<span class="{cls}">{_e(health)}</span>'),
            (t('종류', 'Type'), _e(' · '.join(x for x in (d.get('media'), d.get('bus')) if x))),
            (t('드라이브 문자', 'Drive letters'), _e(' '.join(d.get('letters') or []), t('없음', 'None'))),
            (t('수명 사용량', 'Life used'), f"{d['wearPct']}%" if isinstance(d.get('wearPct'), (int, float)) else unknown_text),
            (t('온도', 'Temperature'), f"{d['temperatureC']}°C" if isinstance(d.get('temperatureC'), (int, float)) else unknown_text),
            (t('사용 시간', 'Power-on time'),
             t(f"{int(hours):,}시간", f"{int(hours):,} hours") if isinstance(hours, (int, float)) else unknown_text),
            (t('복구하지 못한 오류', 'Unrecovered errors'),
             t(f'{int(err):,}건', f'{int(err):,}') if isinstance(err, (int, float)) else unknown_text),
            (t('지금까지 쓴 양', 'Total written'), _bytes(extra.get('dataWrittenBytes'))),
        ]
        for w in d.get('warnings') or []:
            rows.append((t('디스크 경고', 'Disk warning'), f'<span class="bad">{_e(w)}</span>'))
        parts.append(f"<h3>{_e(d.get('name'))}</h3>" + _rows(rows))

    bh = data.get('boots') or {}
    parts.append(f"<h2>{t('부팅 시간 (Windows 가 잰 값)', 'Boot time (measured by Windows)')}</h2>")
    boots = bh.get('boots') or []
    if boots:
        secs = [b['seconds'] for b in boots if isinstance(b.get('seconds'), (int, float))]
        sec = t('초', ' s')
        parts.append(_rows([
            (t('기록된 마지막 부팅', 'Last recorded boot'),
             f"{_e((boots[0].get('at') or '')[:16].replace('T', ' '))} · {boots[0]['seconds']}{sec}"),
            (t(f'평균 ({len(secs)}번)', f'Average ({len(secs)} boots)'),
             f'{sum(secs) / len(secs):.1f}{sec}' if secs else unknown_text),
        ]))
    else:
        parts.append(f"<p>{_e(bh.get('note') or bh.get('error'), t('기록된 부팅이 없습니다.', 'No boots recorded.'))}</p>")
    if bh.get('stale'):
        parts.append(f"<p class=\"warn\">{_e(bh['stale'])}</p>")

    bt = data.get('battery') or {}
    if bt.get('batteries'):
        parts.append(f"<h2>{t('배터리', 'Battery')}</h2>")
        for b in bt['batteries']:
            parts.append(_rows([
                (t('이름', 'Name'), _e(b.get('name'))),
                (t('건강 (완전 충전 / 설계 용량)', 'Health (full charge / design capacity)'),
                 f"{b['healthPct']}%" if isinstance(b.get('healthPct'), int) else unknown_text),
                (t('충전 횟수', 'Charge cycles'),
                 t(f"{b['cycles']:,}회", f"{b['cycles']:,}") if isinstance(b.get('cycles'), int) else unknown_text),
            ]))

    ch = data.get('changes')
    parts.append(f"<h2>{t('APEX CARE 가 바꿔 둔 설정', 'Settings changed by APEX CARE')}</h2>")
    if ch is None:
        parts.append(f"<p class=\"warn\">{t('변경 기록을 읽지 못했습니다.', 'Could not read the change history.')}</p>")
    elif not ch:
        parts.append('<p>' + t('되돌릴 설정 변경이 없습니다(이 앱이 기록한 시스템 설정은 모두 원래 값입니다).',
                               'No setting changes to undo (all system settings this app recorded are at their original values).')
                     + '</p>')
    else:
        items = sorted({str(e.get('why') or k) for k, e in ch.items() if isinstance(e, dict)})
        more = len(items) - 50
        parts.append('<p>' + t(f"{len(items)}개 — APEX CARE 의 '변경 내역 · 되돌리기' 에서 원래대로 되돌릴 수 있습니다.",
                               f"{len(items)} — they can be undone under 'Change history · Undo' in APEX CARE.")
                     + '</p><ul>'
                     + ''.join(f'<li>{_e(x)}</li>' for x in items[:50])
                     + (f"<li>{t(f'외 {more}개', f'and {more} more')}</li>" if more > 0 else '') + '</ul>')

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


def save(window, lang='ko'):
    """저장 창을 띄워 고른 곳에 보고서를 쓴다. {'success', 'path', 'cancelled', 'message'}
    lang: 보고서 언어('ko'|'en'). 결과 문장은 화면이 바꾼다."""
    lang = 'en' if lang == 'en' else 'ko'
    if window is None:
        return {'success': False, 'message': '창이 없어 저장 창을 띄울 수 없습니다.'}
    try:
        import webview
        stem = 'PC status report' if lang == 'en' else 'PC 상태 보고서'
        name = f"{stem} {datetime.now().strftime('%Y-%m-%d')}.html"
        chosen = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name,
                                           file_types=('HTML 파일 (*.html)' if lang == 'ko' else 'HTML file (*.html)',))
    except Exception as e:
        return {'success': False, 'message': f'저장 창을 띄우지 못했습니다: {e}'}
    if isinstance(chosen, (list, tuple)):
        chosen = chosen[0] if chosen else None
    if not chosen:
        return {'success': False, 'cancelled': True, 'message': '저장을 취소했습니다.'}
    path = str(chosen)
    if not path.lower().endswith(('.html', '.htm')):
        path += '.html'
    text = build_html(collect(), lang=lang)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError as e:
        return {'success': False, 'message': f'보고서를 저장하지 못했습니다: {e}'}
    return {'success': True, 'path': path, 'message': f'보고서를 저장했습니다: {os.path.basename(path)}'}
