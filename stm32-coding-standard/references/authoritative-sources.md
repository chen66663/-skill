# 权威与公开参考来源

以下来源用于校准技能中的原则。它们不是把整本标准复制进技能，而是帮助在冲突时判断“强制要求、推荐做法、工具链约束”三者的边界。

## ARM CMSIS

- CMSIS-Core 文档：https://arm-software.github.io/CMSIS_5/Core/html/index.html
- 用途：核内 intrinsic、SysTick、NVIC、异常入口、编译器抽象和 `volatile`/内存访问边界；`__DMB()`/`__DSB()`/`__ISB()` 以及 `SCB_CleanDCache_by_Addr`/`SCB_InvalidateDCache_by_Addr` 等缓存维护函数同样来自 CMSIS-Core。使用前确认芯片设备头、工具链版本和目标核是否带 Cache/FPU。

## ARM 架构内存模型

- ARMv7-M Architecture Reference Manual（ARM DDI 0403）与 ARMv8-M 对应版本：https://developer.arm.com/documentation/ddi0403/latest/
- 用途：内存访问顺序与屏障语义、D-Cache/I-Cache 行为、MPU 区域属性、非对齐访问在 M0/M0+ 与 M3/M4/M7 上的差异、异常压栈与栈对齐要求。缓存一致性和非对齐访问的判断必须引用具体章节，不能只凭经验或示例工程。

## ST 官方 STM32 文档

- STM32CubeIDE 用户指南（UM2609）：https://www.st.com/resource/en/user_manual/um2609-stm32cubeide-user-guide-stmicroelectronics.pdf
- STM32Cube MCU/MPU 软件包入口：https://www.st.com/en/embedded-software/stm32cube-mcu-mpu-packages.html
- STM32 产品与参考手册入口：https://www.st.com/en/microcontrollers-microprocessors/stm32-32-bit-arm-cortex-mcus.html
- 用途：外设初始化顺序、时钟树、APB 定时器倍频、GPIO 复用、NVIC、DMA、错误标志和生成代码边界。最终时序以具体芯片 Reference Manual 为准，不以示例代码注释为准。

## MISRA C

- MISRA 官方资源页：https://www.misra.org.uk/Resources/Resources/Resources
- 用途：规则分级、偏离记录、可分析性、未定义行为、控制流和接口约束。MISRA 是合规框架，不等于每个项目必须机械启用所有规则；报告时区分 mandatory、required、advisory 和项目自定义门禁。
- 版本口径（锁定）：本技能引用的是 **MISRA C:2012**（按含 Amendment 1–4 的规则编号理解），不引用 MISRA C:2023 的重新编号结论，也不假定 C:2023 对 `goto`、单一出口等条目的放宽适用于本项目。若项目改用 C:2023，必须重新核对条号、分级和偏离流程后再引用；本次编制未取得标准原文，引用前应在离线环境对照正式版本确认条号与 mandatory/required/advisory 级别。

## SEI CERT C

- SEI CERT C Coding Standard：https://wiki.sei.cmu.edu/confluence/display/c/SEI+CERT+C+Coding+Standard
- 用途：整数转换、数组边界、生命周期、错误处理、并发和未定义行为。把 CERT 规则转换为 MCU 可执行检查时，结合无操作系统、ISR 和固定内存模型。

## 工程化质量原则

- NASA/JPL Power of Ten（公开论文）：https://spinroot.com/gerard/pdf/P10.pdf
- 用途：限制复杂控制流、循环可证明终止、清晰的所有权和可静态分析性。它是高可靠性参考，不应覆盖用户已有的功能需求或工具链现实。

## 通用 C 编码共识与编号纠偏

以下条目来自公开的嵌入式 C 规范整理（十条法则：初始化、检查返回值、少用全局变量、禁 `goto`、限制复杂度、`const`、避免魔数、数组边界、避免不安全函数、静态分析）。这些条目已并入入口技能，引用时的编号按下面的口径：

| 原则 | 可引用出处 | 纠正说明 |
| --- | --- | --- |
| 变量使用前初始化 | MISRA C:2012 Rule 9.1；CERT C `EXP33-C` | 常被误标为 MISRA Rule 8.5；8.5 讲的是外部对象/函数只声明一次 |
| 检查所有返回值 | MISRA C:2012 Rule 17.7；CERT C `ERR33-C` | 常见说法“未检查返回值”本身不属于 MISRA，需映射到 17.7 才有强制力 |
| 少用全局变量 | MISRA C:2012 关于外部对象与作用域的要求；本项目门禁 | 通用建议，非单条标准；落地为 `static` 限作用域 + 访问函数 + 临界区 |
| 禁止 `goto` | MISRA C:2012 Rule 15.1 | Linux 内核风格允许 `goto` 做集中清理，本项目按 MISRA 从严，统一用 `do { } while (0)` 或清理函数替代 |
| 限制函数复杂度 | HIS 代码度量、IEC 61508 与高可靠性实践 | 圈复杂度 ≤ 10 不是 MISRA C 正文条款；MISRA 侧重结构约束（15.1 禁 `goto`，15.5 单一出口为 advisory） |
| 用 `const` 保护只读数据 | CERT C `DCL00-C`；本项目门禁 | 需区分 `const T *`、`T *const`、`const T *const` 三种含义 |
| 避免魔法数字 | MISRA C:2012 Rule 7.x 关于字面量与本质类型；本项目门禁 | 物理量必须带单位宏或枚举，不能用裸数字 |
| 数组与缓冲区边界 | CERT C `STR31-C`、`STR07-C`；MISRA C:2012 Rule 17.x | 外部长度必须在拷贝前钳到目标容量 |
| 不用不安全函数 | MISRA C:2012 Rule 21.3（禁用 `stdlib.h` 分配）、Rule 21.6（禁用标准 I/O）；CERT C `STR31-C` | `strcpy`/`strcat`/`sprintf`/`gets`/`scanf` 由 CERT 字符串规则覆盖 |
| 使用静态分析工具 | 工具自带规则集（cppcheck、PC-lint Plus、Clang Static Analyzer、SonarQube），MISRA 规则文本需另行取得 | 工具报告的“新增/遗留”要分开归档，禁止用大面积抑制把报告刷绿；`cppcheck --addon=misra.py` 缺少合法 MISRA 规则文本时只会报规则缺失，不能作为合规证据；命令见 `check-commands.md` |

说明：本次未联网复核上述规则编号的官方原文，引用前应在离线环境对照 MISRA C:2012 与 CERT C 的正式版本确认条号与分级（mandatory/required/advisory）。公开博客（如《嵌入式编程规范，还有这些黄金法则》https://lixiaoyao.blog.csdn.net/article/details/156916687 ）可用于印证原则，但规则编号必须回标准正文核对后再引用，博客本身不作为唯一依据。

## 来源使用规则

1. 官方芯片参考手册和工程配置优先于网上博客。
2. 标准中的“推荐”不能被写成无条件“必须”；若用户项目已有偏离，记录偏离和验证方法。
3. 联网资料不可访问时，仍使用本技能的本地规则，并明确未完成外部核验；不要编造版本号、寄存器位或 API 行为。
