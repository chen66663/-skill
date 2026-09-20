'''立创/JLC 元器件查询：核实库存、价格、封装、规格参数与数据手册链接

数据源是 JLC SMT 元器件库接口，与立创商城共用同一商品库，C 编号一致，
无需鉴权即可匿名调用。原理图评审时用它核实元器件参数与现货情况。

用法:
    python lcsc_lookup.py get C8734
    python lcsc_lookup.py search "STM32F103C8T6" --limit 5
    python lcsc_lookup.py search "0603 100nF 50V X7R" --in-stock
    python lcsc_lookup.py bom mpn_list.txt
'''

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

if not sys.stdout.isatty() and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_URL = (
    'https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/'
    'smtGood/selectSmtComponentList'
)
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
TIMEOUT_SECONDS = 30
MAX_LIMIT = 50


class LookupError(Exception):
    '''接口不可用或返回内容异常'''


def fetch(keyword, limit):
    payload = json.dumps(
        {'currentPage': 1, 'pageSize': limit, 'keyword': keyword}
    ).encode('utf-8')
    request = urllib.request.Request(API_URL, data=payload, method='POST')
    request.add_header('Content-Type', 'application/json')
    request.add_header('Accept', 'application/json')
    request.add_header('User-Agent', USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode('utf-8', errors='replace')
    except urllib.error.URLError as error:
        raise LookupError('无法访问元器件接口: %s' % error)
    except OSError as error:
        raise LookupError('网络请求失败: %s' % error)

    try:
        data = json.loads(body)
    except ValueError:
        raise LookupError('接口未返回 JSON，可能是网络被拦截或接口已变更')

    page = (data.get('data') or {}).get('componentPageInfo') or {}
    return page.get('list') or [], page.get('total') or 0


def first_price(item):
    for tier in item.get('componentPrices') or []:
        price = tier.get('productPrice')
        if price is not None:
            return price
    return None


def price_ladder(item):
    parts = []
    for tier in item.get('componentPrices') or []:
        price = tier.get('productPrice')
        if price is None:
            continue
        start = tier.get('startNumber')
        end = tier.get('endNumber')
        if end in (None, -1):
            parts.append('%s+: %s' % (start, price))
        else:
            parts.append('%s-%s: %s' % (start, end, price))
    return ' | '.join(parts)


def key_attributes(item):
    pairs = []
    for attribute in item.get('attributes') or []:
        name = attribute.get('attribute_name_en')
        value = attribute.get('attribute_value_name')
        if name and value and value not in ('-', ''):
            pairs.append('%s=%s' % (name, value))
    return pairs


def stock_text(item):
    stock = item.get('stockCount') or 0
    if stock > 0:
        return str(stock)
    return '0 <-- 无现货，必须给替代型号'


def component_code(item):
    return item.get('componentCode') or '?'


def model(item):
    return item.get('componentModelEn') or item.get('componentName') or '?'


def brand(item):
    return item.get('componentBrandEn') or '?'


def package(item):
    return item.get('componentSpecificationEn') or '?'


def format_item(item, verbose=True):
    lines = [
        '%s  %s %s  [%s]' % (
            component_code(item), brand(item), model(item), package(item)
        ),
        '  库存: %s' % stock_text(item),
    ]
    price = first_price(item)
    if price is not None:
        lines.append('  单价(1+): %s' % price)
    if verbose:
        ladder = price_ladder(item)
        if ladder:
            lines.append('  阶梯价: %s' % ladder)
        lines.append('  规格: %s' % (item.get('describe') or '-'))
        pairs = key_attributes(item)
        if pairs:
            lines.append('  参数: %s' % '; '.join(pairs))
    if item.get('dataManualUrl'):
        lines.append('  手册: %s' % item['dataManualUrl'])
    if item.get('lcscGoodsUrl'):
        lines.append('  商品页: %s' % item['lcscGoodsUrl'])
    return '\n'.join(lines)


def find_exact(items, target):
    wanted = target.upper()
    for item in items:
        if component_code(item).upper() == wanted:
            return item
    for item in items:
        if model(item).upper() == wanted:
            return item
    return None


def run_search(keyword, limit, in_stock_only, as_json, verbose):
    items, total = fetch(keyword, limit)
    if in_stock_only:
        items = [item for item in items if (item.get('stockCount') or 0) > 0]
    if as_json:
        print(json.dumps(
            {'keyword': keyword, 'total': total, 'items': items},
            ensure_ascii=False, indent=2,
        ))
        return 0
    print('关键词 "%s" 命中 %s 条，显示 %s 条' % (keyword, total, len(items)))
    if not items:
        print('没有匹配结果：换个型号，或用参数关键词（如 0603 100nF 50V X7R）重试')
        return 1
    for index, item in enumerate(items):
        if index:
            print('')
        print(format_item(item, verbose=verbose))
    return 0


def run_get(code, as_json, verbose):
    items, _ = fetch(code, MAX_LIMIT)
    match = find_exact(items, code)
    if match is None:
        if as_json:
            print(json.dumps(
                {'code': code, 'match': None}, ensure_ascii=False, indent=2
            ))
        else:
            print('未找到精确匹配的 %s，下面列出相近结果供人工确认' % code)
            for item in items[:5]:
                print(format_item(item, verbose=False))
        return 1
    if as_json:
        print(json.dumps(
            {'code': code, 'match': match}, ensure_ascii=False, indent=2
        ))
    else:
        print(format_item(match, verbose=verbose))
    return 0


def display_width(text):
    return sum(2 if ord(char) > 0x2E80 else 1 for char in str(text))


def pad(text, width):
    text = str(text)
    return text + ' ' * max(0, width - display_width(text))


def run_bom(path, as_json, limit):
    source = Path(path)
    if not source.is_file():
        print('找不到 BOM 文件: %s' % source)
        return 1

    targets = []
    for line in source.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            targets.append(line)
    if not targets:
        print('BOM 文件里没有可用型号（每行一个型号，# 开头为注释）')
        return 1

    rows = []
    failures = []
    for target in targets:
        try:
            items, _ = fetch(target, limit)
        except LookupError as error:
            failures.append('%s: %s' % (target, error))
            rows.append({'mpn': target, 'item': None, 'exact': False})
            continue
        match = find_exact(items, target)
        exact = match is not None
        if match is None and items:
            match = items[0]
        rows.append({'mpn': target, 'item': match, 'exact': exact})

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if not failures else 1

    header = ('型号', '立创编号', '品牌', '封装', '库存', '1+单价')
    table = [header]
    for row in rows:
        item = row['item']
        if item is None:
            table.append((row['mpn'], '未查到', '-', '-', '-', '-'))
            continue
        label = row['mpn'] if row['exact'] else '%s(近似)' % row['mpn']
        price = first_price(item)
        table.append((
            label,
            component_code(item),
            brand(item),
            package(item),
            str(item.get('stockCount') or 0),
            '-' if price is None else str(price),
        ))

    widths = [
        max(display_width(row[col]) for row in table)
        for col in range(len(header))
    ]
    for index, row in enumerate(table):
        print('  '.join(pad(row[col], widths[col]) for col in range(len(header))))
        if index == 0:
            print('  '.join('-' * width for width in widths))

    out_of_stock = [
        row['mpn'] for row in rows
        if not row['item'] or (row['item'].get('stockCount') or 0) == 0
    ]
    if out_of_stock:
        print('')
        print('无现货或未查到，需要替代型号: %s' % ', '.join(out_of_stock))
    if failures:
        print('')
        for failure in failures:
            print('查询失败: %s' % failure)
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(
        description='查询立创/JLC 元器件的库存、价格、封装与规格参数',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    get_parser = subparsers.add_parser('get', help='按立创 C 编号精确查询')
    get_parser.add_argument('code', help='立创编号，如 C8734')
    get_parser.add_argument('--json', action='store_true', dest='as_json')
    get_parser.add_argument('--brief', action='store_true', help='只显示库存与价格')

    search_parser = subparsers.add_parser('search', help='按型号或参数关键词搜索')
    search_parser.add_argument('keyword')
    search_parser.add_argument('--limit', type=int, default=5, help='显示条数，默认 5')
    search_parser.add_argument(
        '--in-stock', action='store_true', help='只保留有现货的'
    )
    search_parser.add_argument('--json', action='store_true', dest='as_json')
    search_parser.add_argument('--brief', action='store_true', help='只显示库存与价格')

    bom_parser = subparsers.add_parser('bom', help='批量核对 BOM，每行一个型号')
    bom_parser.add_argument('path')
    bom_parser.add_argument('--limit', type=int, default=20, help='每个型号的候选条数')
    bom_parser.add_argument('--json', action='store_true', dest='as_json')

    args = parser.parse_args()
    try:
        if args.command == 'get':
            return run_get(args.code, args.as_json, verbose=not args.brief)
        if args.command == 'search':
            return run_search(
                args.keyword, args.limit, args.in_stock, args.as_json,
                verbose=not args.brief,
            )
        return run_bom(args.path, args.as_json, args.limit)
    except LookupError as error:
        print('查询失败: %s' % error)
        return 1


if __name__ == '__main__':
    sys.exit(main())
