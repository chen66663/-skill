# 嘉立创 EDA / BOM 导出格式

## 典型记录

```text
C0402 ! CC0402JRNPO9BN470容值:47pF;精度:±5%;额定电压:50V;材质(温度系数):NP0;https://atta.szlcsc.com/example.pdf ! 47pF ,
        ; CC3
,
```

BOM 卡片也可能把位号放在同一行：

```text
C0402 ! CC0402JRNPO9BN470 ! '47pF' ; CC3
```

CSV/TSV 元件表必须先用表头识别列。常见表头包括
`Comment,Designator,Footprint,LCSC Part #`、`MPN`、`Package`、
`References`、`Value`、`Description` 和 `Datasheet`。

字段含义：

| 位置 | 含义 | 示例 |
|---|---|---|
| 第一个 `!` 前 | 封装 | `C0402`、`C0603` |
| 两个 `!` 之间 | 型号、规格属性和数据手册链接 | `CC0402JRNPO9BN470...` |
| 第二个 `!` 后 | 表格中的参数值 | `47pF`、`100nF` |
| 同一行或后续以 `;` 开头的内容 | 使用该型号的位号 | `C1 C2` |
| 单独一行 `,` | 记录分隔符 | `,` |
| CSV/TSV 表头 | 列角色 | `Designator`, `Footprint`, `LCSC Part #` |

## 快速预检（首选）

拿到导出文件后，先执行一次批量预检。该命令会解析、按型号去重、默认以 6
路并发查询立创/JLC，并只输出需要处理的项目：

```bash
python scripts/review_export.py export.txt --jobs 6
python scripts/review_export.py export.txt --verbose
python scripts/review_export.py export.txt --json
```

- 默认只输出解析告警、未精确匹配、无现货、封装冲突、参数冲突和关键参数无法核实项。
- 查询结果默认缓存 24 小时；可用 `--no-cache`、`--cache-ttl` 和 `--cache-file` 调整。
- `--verbose` 同时显示通过项，`--json` 用于后续自动化处理。
- 只有在需要原始清单、位号明细或自定义格式时，才继续调用解析器。

## 解析命令（补充）

```bash
python scripts/parse_schematic_export.py export.txt
python scripts/parse_schematic_export.py export.txt --format json
python scripts/parse_schematic_export.py export.txt --format lcsc
```

- 默认 `tsv` 输出适合人工核对。
- `json` 输出保留属性、位号、原始行号和解析告警。
- `lcsc` 输出每行一个去重型号，可直接保存后交给：
  `python scripts/lcsc_lookup.py bom <型号清单>`

## 证据边界

这类文件经常只是**元件清单**，不等同于完整原理图网表：

- 它能证明存在哪些位号、型号、封装、参数和手册链接。
- 它不能证明某个电容连接到了哪个 VDD 引脚，也不能证明 I2C 上拉、UART 交叉、晶振负载电容或 DCDC 网络是否正确，除非文件中另有明确的网络与引脚连接记录。
- 缺少精度、耐压或温度系数属于导出信息不完整，不能单独判定为电路设计错误；应结合完整型号、数据手册和电路工作条件核实。
- 同一型号可能拆成多条记录，不能只按行数判断器件数量；以位号去重后的数量为准。
- 型号、属性和位号发生冲突时，先把冲突作为待确认证据列出，不要静默采用其中一条。
- 预检中的参数冲突来自导出值与接口值比对；只能证明两处资料不一致，最终设计结论仍需结合数据手册和实际工作条件。

## 解析器行为

`parse_schematic_export.py` 会：

- 识别多行 BOM 卡片、同行 BOM 卡片和带表头的 CSV/TSV 元件表。
- 容忍行首行尾空格、引号包裹的参数值和多行位号。
- 展开 `C1-C3`、`R1-R4` 这类位号范围。
- 从型号文本中拆分 `容值`、`阻值`、`精度`、`额定电压`、`温度系数` 等属性。
- 提取 `http://` 或 `https://` 数据手册链接。
- 汇总同一记录中的多个位号。
- 对缺少位号、参数值冲突、位号重复、同型号封装冲突和未识别字段给出告警。
- 检测到 `$PACKAGES` 与 `$NETS` 时停止元件表解析，并提示改用
  `parse_tel_netlist.py`。

解析器不会推断不存在的网络连接，也不会自动修改输入文件。


## .tel 网表（含网络连接）

当文件含 `$PACKAGES` 与 `$NETS` 时，改用：

```bash
python scripts/parse_tel_netlist.py netlist.tel
python scripts/parse_tel_netlist.py netlist.tel --pins U1
python scripts/parse_tel_netlist.py netlist.tel --net GND
```

记录形状：

```text
$PACKAGES
C0402 ! CC0402JRNPO9BN470 ! 47pF ; C1
$NETS
NRST ; C1.2 R1.1 U1.25
$END
```

- `$PACKAGES` 提供封装、型号、参数值和位号。
- `$NETS` 提供网络名和 `位号.引脚号`。这是连接证据，可用于核对复位、电源、晶振、接口交叉和单引脚网络。- 网表段落顺序不固定；解析器会扫描 `$PACKAGES`/`$COMPONENTS` 和 `$NETS`/`$NETWORKS` 等别名，不依赖 `$PACKAGES` 必须在 `$NETS` 前。
- 引脚号不一定是纯数字，也可能是 `A1`、`EP`、`PAD1` 等字母数字形式；连接证据只要求稳定的 `REF.PIN` 结构。- `{Value}` 和 `{Datasheet}` 是原理图库字段占位符，不应被当成真实参数或 URL：前者进入 `value_status=placeholder`，后者进入 `datasheet_status=placeholder`；若同一记录有真实 URL，则状态以 `url` 为准。
- 连写检查必须区分：同一引脚重复出现在两个网络是明确错误；同一器件多个引脚出现在同一网络可能是并联功率脚、连接器双触点或内部功能脚，只列为待确认项。
- 续行以空格开头，逗号只是行续接符。
- 没有器件坐标或封装引脚名，不能判断去耦距离、极性方向或实际走线宽度。
- 不要把这种文件交给 `parse_schematic_export.py` 取连接证据。该命令现在会明确提示改用 `parse_tel_netlist.py`；网络连接只从后者的 `$NETS` 输出读取。
