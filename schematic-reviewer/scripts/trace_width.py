'''IPC-2221 走线载流量计算：由电流反推线宽，或由线宽反推载流

公式 I = k * dT^0.44 * A^0.725
    k   外层 0.048，内层 0.024
    dT  允许温升 ℃
    A   走线横截面积 mil^2 = 线宽(mil) * 铜厚(mil)

用法:
    python trace_width.py --current 3 --copper 1 --layer outer --dt 10
    python trace_width.py --width 50 --copper 1 --layer outer --dt 10
    python trace_width.py table
'''

import argparse
import sys

MIL_PER_MM = 1.0 / 0.0254
COPPER_THICKNESS_MIL = {
    '0.5': 0.685,
    '1': 1.37,
    '2': 2.74,
    '3': 4.11,
}
K_OUTER = 0.048
K_INNER = 0.024

if not sys.stdout.isatty() and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def layer_k(layer):
    return K_OUTER if layer == 'outer' else K_INNER


def current_for(width_mil, thickness_mil, dt, layer):
    section = width_mil * thickness_mil
    return layer_k(layer) * dt ** 0.44 * section ** 0.725


def width_for(current, thickness_mil, dt, layer):
    section = (current / (layer_k(layer) * dt ** 0.44)) ** (1.0 / 0.725)
    return section / thickness_mil


def to_mm(mil):
    return mil * 0.0254


def describe(copper, layer, dt):
    layer_text = '外层' if layer == 'outer' else '内层'
    return '%soz 铜厚, %s, ΔT<=%s℃' % (copper, layer_text, trim(dt))


def trim(value):
    text = '%.2f' % value
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def report_width(args):
    thickness = COPPER_THICKNESS_MIL[args.copper]
    minimum = width_for(args.current, thickness, args.dt, args.layer)
    print('电流 %s A, %s' % (trim(args.current), describe(args.copper, args.layer, args.dt)))
    print('  最小线宽: %.1f mil (%.2f mm)' % (minimum, to_mm(minimum)))
    for factor in (1.5, 2.0):
        width = minimum * factor
        print('  建议线宽(%sx): %.1f mil (%.2f mm)' % (trim(factor), width, to_mm(width)))
    print('  注: 电源主路径建议 2 倍裕量；过孔按单个 0.3mm 内径约 1~1.5A 并联计算')


def report_current(args):
    thickness = COPPER_THICKNESS_MIL[args.copper]
    current = current_for(args.width, thickness, args.dt, args.layer)
    print('线宽 %s mil (%.2f mm), %s' % (
        trim(args.width), to_mm(args.width), describe(args.copper, args.layer, args.dt)
    ))
    print('  载流能力: %.2f A' % current)
    half = args.width / 2
    print('  线宽减半(%s mil)时约 %.2f A' % (trim(half), current_for(half, thickness, args.dt, args.layer)))


def print_table():
    sections = (
        ('1oz 铜厚 · 外层走线', '1', 'outer', (10, 20, 30),
         (5, 8, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300)),
        ('1oz 铜厚 · 内层走线（约为外层的 50%~70%）', '1', 'inner', (10, 20),
         (10, 20, 30, 50, 75, 100, 150, 200)),
        ('2oz 铜厚 · 外层走线（大电流板常用）', '2', 'outer', (10, 20),
         (20, 30, 50, 75, 100, 150, 200)),
    )
    thickness_cache = {}
    for title, copper, layer, temps, widths in sections:
        thickness = thickness_cache.get(copper)
        if thickness is None:
            thickness = COPPER_THICKNESS_MIL[copper]
            thickness_cache[copper] = thickness
        print('')
        print('## %s' % title)
        print('')
        header = ['线宽(mil)', '线宽(mm)'] + ['ΔT=%s℃ 电流(A)' % t for t in temps]
        print('| ' + ' | '.join(header) + ' |')
        print('|' + '|'.join(['---:'] * len(header)) + '|')
        for width in widths:
            cells = ['%s' % width, '%.2f' % to_mm(width)]
            for t in temps:
                cells.append('%.2f' % current_for(width, thickness, t, layer))
            print('| ' + ' | '.join(cells) + ' |')


def main():
    parser = argparse.ArgumentParser(
        description='IPC-2221 走线载流量计算（默认 1oz 外层、ΔT<=10℃）',
    )
    subparsers = parser.add_subparsers(dest='command')

    width_parser = subparsers.add_parser('width', help='由电流反推最小线宽')
    common(width_parser)
    width_parser.add_argument('--current', type=float, required=True, help='电流 A')

    current_parser = subparsers.add_parser('current', help='由线宽反推载流能力')
    common(current_parser)
    current_parser.add_argument('--width', type=float, required=True, help='线宽 mil')

    subparsers.add_parser('table', help='输出 IPC-2221 速查表（Markdown）')

    args = parser.parse_args()
    if args.command == 'table':
        print_table()
        return 0
    if args.command == 'width':
        report_width(args)
        return 0
    if args.command == 'current':
        report_current(args)
        return 0

    parser.print_help()
    return 0


def common(parser):
    parser.add_argument('--copper', choices=sorted(COPPER_THICKNESS_MIL), default='1')
    parser.add_argument('--layer', choices=('outer', 'inner'), default='outer')
    parser.add_argument('--dt', type=float, default=10.0, help='允许温升 ℃，默认 10')


if __name__ == '__main__':
    sys.exit(main())
