# research/results/a_long/ — A-long lane 结果归档

A-long(A 股长线)的研究/运行结果归档根。约定:新 a_long 切片的产物落到这里(`engine/a_short_run_paths.lane_output_root("a_long")`)。

**重要(为何老产物不在这里):** 现存 a_long 研究产物仍在 `research/results/` **顶层**(`a_long_data_integrity_audit_*`、`a_long_full_main_board_data_integrity_audit_*`、`a_long_large_cap_*`、`a_long_signal_search_*`、`a_long_materialized_*`、`a_share_minimal_data_burst_*` 等)。它们**未迁入本文件夹**,因为整条 a_long 链按硬编码路径互相读取(market_cap audit 读 full_main_board audit……)+ ~20 个测试硬读这些 fixture + preregistration 用这些路径作 provenance 引用。物理搬迁会断链/断测试/悬空 provenance,需一次有审查的迁移切片。

**未来**:下一个 a_long 切片建时,把它的输出 + 读上游路径**一起**指到本 lane(配套改 + 测试),实现增量归档;老产物维持原地直到统一迁移。
