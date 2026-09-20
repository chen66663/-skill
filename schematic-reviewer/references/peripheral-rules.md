# 外围电路核心规则速查

> 本文件仅作核心规则速查。详细检查项请fetch外部权威checklist：
> - Schemalyzer 100+项清单: https://www.schemalyzer.com/zh/blog/schematic-review/checklists/schematic-review-checklist
> - embd.cc Agentic清单: http://embd.cc/agentic-schematics-and-pcb-review-checklist
> - GitHub checklist: https://github.com/argenox/hardware-design-checklist/blob/master/schematic-design-checklist.md

## 一、电源去耦

- **每个VDD引脚**：就近放置0.1µF X7R陶瓷电容，距离≤2mm
- **电源入口**：1µF~10µF大容量储能电容
- **多电源域**（AVDD/DVDD/VDDQ）：每个域独立去耦，不可共用
- **模拟/数字分离**：AVDD与DVDD之间用磁珠（600Ω@100MHz）或0Ω电阻单点连接
- **电容耐压**：≥工作电压×1.5~2倍；陶瓷电容注意直流偏压降额（X7R降30%~50%）

## 二、复位与配置

- **RESET#（低有效）**：上拉到VDD，通常10kΩ；建议加100nF滤波电容
- **strapping引脚**：通过电阻上下拉，不可直接接电源/地（除非手册允许）
- **未使用输入**：必须接地或上拉，不可悬空（CMOS输入悬空会振荡）
- **未使用输出**：悬空即可

## 三、时钟电路

- **负载电容匹配公式**：CL = (C1×C2)/(C1+C2) + Cs，Cs≈2~5pF
- 通常C1=C2≈2×(CL-Cs)。例：CL=12pF → C1=C2≈18pF
- **常见错误**：C1/C2直接取CL值（如CL=12pF就用12pF），导致频率偏低
- **布局**：晶振靠近XTAL引脚≤5mm，下方铺地屏蔽，远离DCDC电感

## 四、接口与电平

- **I2C**：SDA/SCL必须上拉；100kHz用2.2k~10kΩ，400kHz用1k~4.7kΩ，1MHz+用470Ω~2.2kΩ
- **SPI**：CS上拉（防止上电误选中）；高速>10MHz可串22~33Ω阻尼电阻
- **UART**：TX→RX交叉连接；3.3V不可直接接5V器件
- **开漏输出**：必须外部上拉；低速10kΩ，高速1k~4.7kΩ
- **CAN**：总线两端各120Ω终端电阻
- **电平转换**：不同电压域之间必须用电平转换IC，不可直接连接

## 五、功率路径

- **电源输入**：反接保护（肖特基/P-MOS）+ TVS + 保险丝
- **LDO**：VIN-VOUT≥压差；PD=(VIN-VOUT)×IOUT≤封装散热能力
- **DCDC**：电感Isat≥峰值电流×1.2；输入电容靠近VIN；SW走线短而宽
- **反馈电阻**：VOUT=VREF×(1+R1/R2)，R2通常10k~100kΩ
- **感性负载**：继电器/电机/螺线管必须加续流二极管
- **充电电路**：NTC热敏电阻检测电池温度；充电电流路径走线加宽

## 六、ESD保护

- **所有对外接口**：USB、HDMI、音频、按键、连接器必须有ESD器件
- **USB高速线**：低电容ESD（<1pF），如USBLC6、ESD9B3.3ST5G
- **TVS选型**：VRWM≥最大正常工作电压；VC≤后级IC绝对最大耐压
- **按键输入**：串1k~10kΩ电阻 + 100nF去抖电容

## 七、常见错误速查

| 错误现象 | 可能原因 |
|---|---|
| 芯片不工作 | 去耦缺失/太远；复位悬空；电源电压错；BOOT配置错 |
| 电源电压偏低 | LDO压差不足；DCDC过载；走线过细压降；电容耐压不足 |
| I2C通信失败 | 上拉缺失/过大；总线电容过大；电平不匹配；地址冲突 |
| 晶振不起振 | 负载电容不匹配；走线过长；靠近干扰源；电源噪声大 |
| ADC读数不准 | VREF无去耦；输入无滤波；模数地共地干扰；电源纹波大 |
| DCDC纹波大 | 电感饱和；输出电容不足；SW走线长；补偿不当 |
| 芯片发热 | 功耗超散热；LDO压差大电流大；短路；振荡 |
| EMI超标 | 时钟走线长无屏蔽；DCDC布局差；接口无滤波；地平面不完整 |
