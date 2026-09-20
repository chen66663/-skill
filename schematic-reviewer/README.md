# schematic-reviewer（原理图检查专家）

Codex skill：原理图检查与审核。读数据手册做引脚级分析、查外围电路、算载流线宽、核验立创元器件参数与库存。

## 功能

- 读数据手册做逐引脚分析，提取设计约束（电源、上下拉、电平、驱动能力）
- 对照外部权威 checklist 检查外围电路：去耦、复位与配置、时钟、接口电平、模拟前端、功率路径、ESD
- 识别大电流路径，按 IPC-2221 计算走线宽度并给出加宽建议
- 通过立创/JLC 接口核实元器件规格与现货库存，缺货给替代型号
- 直接输出问题清单，不生成报告/HTML/图片

## 目录结构

```
schematic-reviewer/
|-- SKILL.md                        主流程与约束
|-- agents/openai.yaml              UI 元数据（中文显示名）
|-- scripts/
|   |-- lcsc_lookup.py              立创/JLC 元器件查询
|   `-- trace_width.py              IPC-2221 载流计算
`-- references/
    |-- external-resources.md       权威 checklist 索引与手册获取
    |-- lcsc-guide.md               接口用法、字段、避坑
    |-- peripheral-rules.md         外围电路核心规则速查
    `-- trace-current-table.md      载流速查表（由脚本生成）
```

## 脚本

```bash
# 元器件核实
python scripts/lcsc_lookup.py get C8734
python scripts/lcsc_lookup.py search "0603 100nF 50V X7R" --in-stock
python scripts/lcsc_lookup.py bom mpn_list.txt

# 载流计算
python scripts/trace_width.py width --current 3 --copper 1 --layer outer --dt 10
python scripts/trace_width.py current --width 50 --copper 1 --layer outer --dt 10
python scripts/trace_width.py table
```

## 环境要求

- Python 3.8+，只依赖标准库
- 可访问 `jlcpcb.com`（元器件接口）与厂商数据手册站点

## 已知限制

- 无浏览器自动化：立创商城网页是 JS 单页应用，抓 HTML 拿不到商品数据，必须走接口。
- 元器件接口为第三方公开接口，无鉴权但可能变更；失效时脚本会明确报错，需重新探查接口。
- 立创手册链接是在线阅读页而非 PDF 直链，数据手册优先从厂商官网取。
