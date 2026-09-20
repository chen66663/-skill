# 外部权威资源索引

> 执行检查时按需抓取，不要凭记忆执行检查。本环境没有浏览器自动化工具，
> 用 shell 抓取即可（`Invoke-WebRequest` / `curl`），checklist 页多为静态 HTML。

## 一、原理图检查 Checklist

### 1.1 Schemalyzer 100+ 项原理图审查清单（中文，最全面）

- URL: `https://www.schemalyzer.com/zh/blog/schematic-review/checklists/schematic-review-checklist`
- 覆盖 10 大类：原理图设置与文档、电源设计（输入保护/稳压器/去耦滤波/电源分配/时序）、
  信号完整性（数字/模拟/时钟/高速）、元件验证、微控制器与 FPGA、保护与安全（ESD/过压/过流/热）、
  可测试性与调试、制造与 BOM、EMC 与合规、最终验证
- 抓取关键词：去耦、ESD、I2C、晶振、电源时序、电平转换

### 1.2 embd.cc Agentic 原理图与 PCB 审查清单（AI 友好）

- URL: `http://embd.cc/agentic-schematics-and-pcb-review-checklist`
- 特点：条目化，专为自动化审查设计，可逐条核对
- 覆盖：连通性与正确性、电源与供电、引脚与上下拉、稳压器/时钟/域接口、元件额定值与封装、
  网络与阻抗、PCB 信号完整性、PCB 电源/热/铜皮、验证与文档、可制造性
- 抓取关键词：decoupling、level shift、footprint、impedance、thermal via

### 1.3 GitHub hardware-design-checklist

- URL: `https://github.com/argenox/hardware-design-checklist/blob/master/schematic-design-checklist.md`
- 覆盖：ESD 保护、无源元件降额、BOM 可用性
- 核心规则：电容耐压降额 ≥50% 裕量、电源电容纹波电流额定值、所有 IO 端口 ESD 保护

### 1.4 GitHub pcb-checklist (azonenberg)

- URL: `https://github.com/azonenberg/pcb-checklist/blob/master/schematic-checklist.md`
- 覆盖：ERC 清洁、引脚编号核对、封装匹配、散热焊盘连接、调试接口电源

### 1.5 十大关键检查项（时间紧迫时至少完成这些）

1. 每个 IC 电源引脚都有去耦电容
2. 所有符号引脚编号与数据手册核对过
3. 所有开漏/开集输出都有上拉或下拉
4. 稳压器稳定性已验证（负载电容、ESR）
5. 复位引脚有外部上拉和 RC 滤波
6. 启动/配置（strapping）引脚配置正确
7. 所有外部接口有 ESD 保护
8. 极性元件（电容、二极管）极性正确
9. UART TX/RX、SPI MOSI/MISO 正确交叉
10. ERC/DRC 无未解决错误

## 二、数据手册获取

### 2.1 获取顺序

1. **厂商官网 PDF**（优先，通常可直接下载）：STM32 等取 `https://www.st.com/resource/en/datasheet/<型号>.pdf`，TI 取 `https://www.ti.com/lit/ds/<...>.pdf`。
2. **接口返回的 `dataManualUrl`**：`scripts/lcsc_lookup.py` 会打印，但它是 LCSC 的在线阅读页，不是 PDF 直链，抓下来通常是 HTML。
3. 分销商站点：Digi-Key、Mouser、Octopart。

### 2.2 校验下载结果

- 真正的 PDF 文件头是 `%PDF-`。
- 文件头若是 `<!doctype html>`，说明拿到的是网页（被反爬或链接失效），换来源重取。

### 2.3 必须读到的章节

- Pin Configuration / Pinout — 引脚名称与功能
- Recommended Operating Conditions — 推荐工作条件
- Electrical Characteristics — 电气特性（输入阈值、驱动电流）
- Absolute Maximum Ratings — 绝对最大额定值（耐压核对依据）
- Application Information / Typical Application — 典型应用电路
- Layout Guidelines — 布局布线建议（如有）

## 三、PCB 设计标准

- IPC-2221：印制板设计通用标准（载流计算依据）
- IPC-2612：原理图文档要求
- IEEE 315：图形符号标准

载流公式：I = k × ΔT^0.44 × A^0.725，k = 0.048（外层）/ 0.024（内层）。
数据表见 [trace-current-table.md](trace-current-table.md)；计算用 `scripts/trace_width.py`。

## 四、元器件供应链

- 立创商城（国内）：`https://www.szlcsc.com/`
- LCSC（国际）：`https://www.lcsc.com/`
- 查询方式、可用接口与字段说明见 [lcsc-guide.md](lcsc-guide.md)

## 五、使用方式

1. 根据电路类型选 1~2 个 checklist，抓取相关章节。
2. 把 checklist 条目当作检查骨架，结合数据手册逐项核对。
3. 结论标注依据来源（如 "Schemalyzer checklist §2.3"、"embd.cc §4.8"）。
