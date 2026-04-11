# 《宪法》方案 C（c03_breakpoint）基准与方案 D 对比说明

## 1. 基准三件套（与测试一致）

| 文件 | 说明 |
| --- | --- |
| [tests/test_chunking/fixtures/宪法.md](../../tests/test_chunking/fixtures/宪法.md) | 源文，与 `data/md_minerU/md3__宪法.md` 同步 |
| [tests/test_chunking/fixtures/宪法_c03_breakpoint_export.md](../../tests/test_chunking/fixtures/宪法_c03_breakpoint_export.md) | c03 导出快照，与 `data/chunk_md/c03_breakpoint/md3__宪法.md` 同步 |
| [tests/test_chunking/fixtures/宪法_c03_breakpoint_golden.json](../../tests/test_chunking/fixtures/宪法_c03_breakpoint_golden.json) | 各块在源文中的 `[char_start, char_end)` 区间 |

回归测试：[test_constitution_md_golden.py](../../tests/test_chunking/test_constitution_md_golden.py) 校验「拆导出 → 拼接 = 源文」且区间与 JSON 一致。

## 2. 分隔符识别

块边界使用 [`default_chunk_separator()`](../../src/chunking/breakpoint_embed.py) 生成的固定分隔条（`#`×88、`CHUNK_BOUNDARY (breakpoint_embed C)` 等）。代码侧请使用 [`split_breakpoint_export_to_chunks()`](../../src/chunking/breakpoint_embed.py)，勿手写分隔串。

## 3. 与方案 D 对比

在相同源文 `fixtures/宪法.md` 上运行方案 D 分段后，将 D 的块区间与 `宪法_c03_breakpoint_golden.json` 中的方案 C 区间对比（块数、平均块长、条款锚点是否被切断等）。评测清单见 [v1.1.7-scheme-d-eval.md](../plan/v1.1.7-scheme-d-eval.md)。

## 4. 与旧「1500/100 句边界 golden」的关系

原 `宪法_1500_100_boundary_golden.json`（边界感知滑窗）已移除；若仍需该策略的统计，参见本目录下历史报告（如 `宪法_边界切分完整性统计.md`），其语料路径可能仍为旧版 `data/宪法.md`，与当前 MinerU 源文长度可能不一致。
