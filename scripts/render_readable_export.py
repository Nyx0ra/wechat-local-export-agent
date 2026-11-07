"""Render all source records faithfully, with explicit gaps and verified local media."""
import collections
import datetime as dt
import html
import json
import pathlib
import shutil
import sys
from urllib.parse import quote
from common import config, display_timezone

task = pathlib.Path(sys.argv[1]).resolve()
state = json.loads((task / 'work/target-view-state.json').read_text(encoding='utf-8'))
records = [json.loads(line) for line in (task / 'work/target-records.jsonl').read_text(encoding='utf-8').splitlines()]
root = task / 'exports/html'
media = json.loads((root / 'media-index.json').read_text(encoding='utf-8'))
verification = json.loads((task / 'work/media-verification.json').read_text(encoding='utf-8'))
by_id = collections.defaultdict(list)
for item in media:
    by_id[item['id']].append(item)
options = config(task)
timezone = display_timezone(options)
zone_label = 'UTC' + options.get('display_timezone', '+08:00')
me = state['account']['nickname'] or state['account']['username'] or '本方（身份名称未知）'
other = state['target'].get('remark') or state['target'].get('nickname') or state['target']['username']
labels = {1: '文本', 3: '图片', 34: '语音', 43: '视频', 47: '表情', 48: '位置',
          49: '分享/应用消息', 50: '通话记录', 10000: '系统消息', 10002: '系统/撤回通知'}


def timestamp(record):
    return dt.datetime.fromtimestamp(record['epoch'], timezone).strftime('%Y-%m-%d %H:%M:%S')


def sender(record):
    direction = {0: me, 1: other}.get(record['direction'], '未知方向（源值 ' + str(record['direction']) + '）')
    if record['type'] in (10000, 10002):
        return '系统/通知（源方向字段：' + direction + '）'
    return direction


def link(item):
    label = pathlib.PurePosixPath(item['source_relative']).name
    if item['valid'] is False:
        label += '（当前格式未通过解码校验，原文件已保留）'
    return '<a href="' + quote(item['href'], safe='/') + '" download>' + html.escape(label) + '</a>'


notice = (f'共 {len(records):,} 条源记录；可读正文 {len(records)-state["unparsed_count"]:,} 条，'
          f'压缩正文未解析 {state["unparsed_count"]:,} 条（其中普通文本 {sum(r['unparsed'] and r['type']==1 for r in records)} 条）。'
          '未解析记录保留其身份、时间、顺序、消息 ID，并显示明确说明；不代表其语音或视频一定缺失。'
          f'时区：{zone_label}。相同秒内按源本地消息 ID 排序，未推断更精细时间。'
          '范围仅为本次备份中的选定会话，不宣称覆盖手机所有历史记录。')
notice += ' 筛选窗口（UTC，起始包含、结束不包含）：' + json.dumps(state.get('time_range'), ensure_ascii=False)
notice += ' 媒体转换：' + state.get('conversion', 'disabled') + '；受限时间窗口内无法可靠归属的候选媒体不导出。'
text_path = task / 'exports/txt/chat.txt'
text_index = []
with text_path.open('wb') as output:
    output.write((other + ' — 微信聊天记录\n' + notice + '\n\n').encode('utf-8'))
    for record in records:
        header = f'[{record["seq"]:06d}] {timestamp(record)} | {sender(record)} | 类型 {record["type"]} | 本地ID {record["id"]}\n'
        output.write(header.encode('utf-8'))
        body = record['body'].encode('utf-8')
        offset = output.tell()
        output.write(body)
        text_index.append({'id': record['id'], 'offset': offset, 'length': len(body)})
        output.write(b'\n')
        attachments = by_id.get(record['id'], [])
        for item in attachments:
            relative = '../html/' + item['href']
            output.write(('附件：' + relative + ('（已通过解码校验）' if item['valid'] is True else '（原文件保留，兼容性详见 HTML）') + '\n').encode('utf-8'))
        if record['type'] in (3, 34, 43, 47, 49) and not attachments:
            output.write('附件：未找到可可靠关联的本地文件；未验证应有附件数量。\n'.encode('utf-8'))
        output.write(('─' * 48 + '\n').encode('utf-8'))
    output.write(f'\n记录结束：{len(records)} 条。\n'.encode('utf-8'))
(task / 'work/txt-byte-index.json').write_text(json.dumps(text_index), encoding='utf-8')

header = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src file: data:; media-src file:; style-src 'unsafe-inline'; script-src 'none'; object-src 'none'; base-uri 'none'">
<title>微信聊天记录</title><style>
body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f4f5f7;color:#18202b;margin:0;font-size:15px;line-height:1.65}
header,main{max-width:1000px;margin:auto;padding:20px}header{background:#fff;border-bottom:1px solid #ddd}
h1{font-size:24px;margin:0 0 12px}.notice{background:#fff5d6;padding:14px;border-left:4px solid #bf8500}
article{background:white;margin:14px 0;padding:16px 20px;border-radius:8px;border-left:4px solid #a4b2bf;content-visibility:auto;contain-intrinsic-size:auto 130px}
article.self{border-left-color:#4b9472}article.unparsed{background:#fffdf5}.meta{color:#596474;font-size:13px}.body{white-space:pre-wrap;overflow-wrap:anywhere;margin:12px 0}
img{max-width:min(100%,640px);max-height:600px;object-fit:contain}audio,video{display:block;max-width:100%;margin:10px 0}video{max-height:600px}
a{color:#155bb8;overflow-wrap:anywhere}details{font-size:13px;color:#596474;margin-top:8px}summary{cursor:pointer}.gap{color:#8c5300;font-size:13px}
</style></head><body>'''
with (root / 'index.html').open('w', encoding='utf-8', newline='\n') as output:
    range_navigation = '<p>选定时间范围内无记录。</p>'
    if records:
        range_navigation = ('<p>时间范围：' + timestamp(records[0]) + ' 至 ' + timestamp(records[-1]) +
                            '</p><p><a href="#m' + str(records[0]['id']) + '">最早</a> · <a href="#m' +
                            str(records[len(records)//2]['id']) + '">中间</a> · <a href="#m' + str(records[-1]['id']) + '">最近</a></p>')
    output.write(header + '<header><h1>' + html.escape(other) + ' — 微信聊天记录</h1><p>会话身份：' +
                 html.escape(me) + ' / ' + html.escape(other) + '（昵称 ' + html.escape(state['target']['nickname']) +
                 '，微信号 ' + html.escape(state['target']['alias']) + '）</p><p class="notice">' + html.escape(notice) +
                 '</p>' + range_navigation + '</header><main>\n')
    for record in records:
        classes = ('self ' if record['direction'] == 0 else '') + ('unparsed' if record['unparsed'] else '')
        output.write(f'<article id="m{record["id"]}" class="{classes}" data-id="{record["id"]}" data-epoch="{record["epoch"]}" data-direction="{record["direction"]}" data-type="{record["type"]}" data-unparsed="{int(record["unparsed"])}">')
        output.write('<div class="meta">' + html.escape(timestamp(record) + ' · ' + sender(record) + ' · ' +
                     labels.get(record['type'], '消息') + ' · #' + str(record['seq']) + ' · 本地ID ' + str(record['id'])) + '</div>')
        output.write('<div class="body">' + html.escape(record['body']) + '</div>')
        attachments = by_id.get(record['id'], [])
        usable = [e for e in attachments if e['valid'] is True]
        if record['type'] == 3:
            images = sorted((e for e in usable if e['kind'] == 'image'), key=lambda e: e['thumbnail'])
            if images:
                selected = images[0]
                if selected['thumbnail']:
                    output.write('<p class="gap">仅有通过解码校验的缩略图；原图格式兼容性见附件。</p>')
                output.write('<a href="' + quote(selected['href'], safe='/') + '"><img loading="lazy" alt="本地图片" src="' + quote(selected['href'], safe='/') + '"></a>')
        for item in usable:
            if item['kind'] == 'audio':
                output.write('<audio controls preload="none" src="' + quote(item['href'], safe='/') + '"></audio>')
            elif item['kind'] == 'video':
                output.write('<video controls preload="none" src="' + quote(item['href'], safe='/') + '"></video>')
        if attachments:
            output.write('<details><summary>本条本地附件（' + str(len(attachments)) + ' 个文件，含原文件/缩略图/转换件）</summary><ul>')
            for item in attachments:
                output.write('<li>' + link(item) + '</li>')
            output.write('</ul></details>')
        elif record['type'] in (3, 34, 43, 47, 49):
            output.write('<p class="gap">未找到可可靠关联的本地附件；未验证应有附件数量。</p>')
        output.write('</article>\n')
    unassociated = by_id.get(None, [])
    if unassociated:
        output.write('<details><summary>无法可靠关联到单条消息的资源（' + str(len(unassociated)) + ' 个）</summary><ul>')
        for item in unassociated:
            output.write('<li>' + link(item) + '</li>')
        output.write('</ul></details>')
    output.write('<p id="end">记录结束：' + str(len(records)) + ' 条。</p></main></body></html>\n')

native = root / 'tool-export'
native_destination = task / 'work/official-readable-html'
assert native.resolve().is_relative_to(task) and native_destination.resolve().is_relative_to(task)
if native.exists():
    assert not native_destination.exists()
    shutil.move(str(native), str(native_destination))
print(json.dumps({'html_bytes': (root/'index.html').stat().st_size, 'txt_bytes': text_path.stat().st_size,
                  'records': len(records), 'unparsed': state['unparsed_count'], 'raw_media_files': len(media)}))
