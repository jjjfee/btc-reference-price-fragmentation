# When does a formally multi-venue benchmark cease to represent fragmented market conditions?
## Evidence from fragmented BTCUSD markets

This repository accompanies the paper:

**When does a formally multi-venue benchmark cease to represent fragmented market conditions? Evidence from fragmented BTCUSD markets**

本仓库对应论文 **When does a formally multi-venue benchmark cease to represent fragmented market conditions? Evidence from fragmented BTCUSD markets**，用于整理论文相关的代码、图表、表格、运行信息，以及未直接纳入 GitHub 主仓库的大文件说明。

---

## Repository purpose / 仓库用途

This repository is a structured companion archive for the paper. It is designed to make the empirical workflow, output provenance, and replication logic transparent, while keeping very large intermediate datasets outside the main GitHub repository.

本仓库是论文的结构化配套仓库，目标是：

- 整理用于数据构建、实验、审计和绘图的源代码
- 对应主文与附录中实际使用的图表和表格
- 保留关键输出的运行信息与诊断材料
- 用 manifest 文件说明未直接纳入主仓库的大型原始/中间数据文件

---

## Paper focus / 论文主线

The paper studies when a formally multi-venue benchmark may cease to represent fragmented market conditions as concentration rises in BTCUSD markets.

The central argument is not a universal ranking of aggregation rules. Instead, the paper asks whether a formally multi-venue benchmark still represents fragmented market conditions when market concentration rises.

The main contrast is:

- **LWMP**: boundary-centered transition into pivot lock-in
- **VWAP**: continuous narrowing toward the dominant-exchange price

The DV-only design is used to isolate the pure reweighting channel rather than the total effect of all market dynamics.

本文的核心问题不是对聚合器做一个普遍优劣排序，而是考察：当市场集中度上升时，一个**形式上跨交易所**的 benchmark，是否仍然能够代表**碎片化市场条件**。

当前主文中的主要机制对照为：

- **LWMP**：boundary-centered transition into pivot lock-in
- **VWAP**：continuous narrowing toward the dominant-exchange price

其中 DV-only 设计用于隔离 **pure reweighting channel**，而不是识别所有市场动态的总效应。

---

## Current manuscript structure / 当前论文结构

### Main text / 主文
The current main text relies primarily on:

- **Figure 1**: LWMP main result
- **Figure 2**: VWAP main result
- **Table 1**: Observed-market persistence of the over-half state (LWMP lock-in state)

### Appendix / 附录
The appendix is currently organized as:

- **A**: Definition / Measurement and Threshold Robustness
- **B**: Subsample Robustness
- **C**: Structural-Exclusion Robustness
- **D**: LWMP Audit / Mechanism-Consistency Checks
- **E**: Supplementary VWAP Evidence
- **F**: Observed-Market Persistence of LWMP Lock-In

---

## Repository structure / 仓库结构

```text
btc-reference-price-fragmentation/
├─ src/
│  ├─ build/
│  ├─ experiments/
│  ├─ audit/
│  └─ plotting/
├─ scripts/
├─ outputs/
│  ├─ main_text/
│  │  ├─ figures/
│  │  └─ tables/
│  ├─ appendix/
│  │  ├─ figures/
│  │  └─ tables/
│  └─ metadata/
├─ docs/
│  ├─ runinfo/
│  └─ diagnostics/
├─ data/
│  └─ external/
│     └─ manifests/
└─ archive/
   ├─ exploratory/
   ├─ duplicates/
   └─ tests/