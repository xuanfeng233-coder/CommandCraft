# 知识库数据审计与补全 — 设计文档

- 日期: 2026-06-21
- 范围: **仅数据补全 + CLAUDE.md 更新**，不改后端逻辑（loader / registry / agent / RAG / skills 算法）。
- 覆盖: Java 版 + 基岩版的全部数据列表（命令、物品、实体、NBT、附魔、药水/状态效果、生物事件等），含"应有却缺失的整张列表"。

## 目标

1. 审计 `knowledge_base/bedrock/` 与 `knowledge_base/java/` 下每一张数据列表，补全缺失条目。
2. 识别并新建"应该存在却完全缺失"的列表。
3. 多版本支持：对齐到**最新稳定版（1.21.9x 线）并全向后兼容**，保留旧版 ID 与旧用法。
4. 同步前端编辑器硬编码列表、后端 skills 硬编码列表；清理 `knowledge_base/` 根目录与 `bedrock/` 字节相同的旧副本。
5. 更新 CLAUDE.md 使其与项目实际一致。

## 关键事实（已勘探）

- 权威数据目录由 `backend/config.py` 指定：`KNOWLEDGE_BASE_BEDROCK_DIR = knowledge_base/bedrock`，`KNOWLEDGE_BASE_JAVA_DIR = knowledge_base/java`。
- `knowledge_base/` 根目录下的 `ids/`、`commands/` 等与 `bedrock/` **字节完全相同**，loader 从不读取它们 → 旧副本，应清理。
- ID 条目 schema：`{ id, name, category, description }`（effects 另有 `numeric_id`）。`IDRegistry` 仅读取 `id` 字段做校验。
- 当前条目数（bedrock / java）：items 562/369、blocks 1064/308、sounds 1753/115、entities 132/131、effects 37/39、enchantments 39/42、particles 183/112、biomes 99/65、gamerules 37/52、structures 17/33；java 独有 attributes 32、paintings 50、data_component_types 70；bedrock 独有 animations 142、spawn_events 144、fog 78。
- **大缺口**：Java items/blocks/sounds 严重不全（real items ~1400+、blocks ~1000、sounds 数千）。

## Schema 增量（向后兼容，loader/registry 无需改）

现有字段保留。仅新增**可选**字段：

- `since` — 引入版本，如 `"1.21.0"`，仅在值得标注时填。
- `deprecated` / `removed_in` — 被移除或被取代的 ID。
- `aliases` — 旧名/重命名标识（如 `grass`→`short_grass`、Java 属性重命名）。**当旧 ID 在游戏内仍有效时，它同时保留为独立条目**，以便 registry 继续校验通过。
- 命令文档：可选 `version_notes` / `legacy_syntax` 记录新旧用法。

## 权威来源策略

- 大列表 / 严重不全（Java items/blocks/sounds/particles、bedrock items/blocks/sounds）→ WebFetch minecraft.wiki 权威清单做 diff 补全。
- 小列表（effects、enchantments、gamerules、biomes、attributes、structures、entities 等）→ 模型知识 + 多 agent 对抗交叉审。
- `version_info.json` 随对齐版本更新。

## 执行阶段（各为一个 Workflow）

- **P0 盘点（只读）**：枚举 bedrock/java/前端编辑器/后端 skills 的所有列表，记录数量与 schema；联网核对大列表权威总数与缺口；识别缺失整张列表。
- **P1 审计补全现有列表**：逐 (edition, list) 流水线：读现有 → 建权威参考 → diff → 按 schema 产出补充条目 → 对抗校验抽样 → 合并。
- **P2 新建缺失列表**：生成 P0 识别出的新列表文件。
- **P3 一致性同步**：前端编辑器硬编码列表 + 后端 skills 列表对齐已补全的 KB；删除根目录旧副本。
- **P4 CLAUDE.md 刷新**：逐条核对 CLAUDE.md 与仓库实际（过期域名、部署细节、数据布局等），更新。

## 覆盖诚实性

sounds 等长尾极大（数千条）。会激进扩充并核对，但**明确记录覆盖 vs. 截断**，不静默截断；结束时按列表汇报 before/after 条目数与置信度。

## 不做（边界）

- 不改 loader/registry/agent/RAG/skills 的算法逻辑。
- 不引入需要改加载逻辑的新数据格式（如按版本拆分文件）。
- 仅改数据文件、前端/后端硬编码数据数组、CLAUDE.md。
