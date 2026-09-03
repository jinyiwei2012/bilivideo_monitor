"""监控业务逻辑包 — 集中拉取模型。

每 75s 触发一次集中拉取所有视频数据。预测独立于拉取周期。

模块结构:
    _prediction.py  — 预测工具函数
    _service.py     — 集中拉取 + 生命周期 + 公开 API
"""

from ui.monitor._prediction import (  # noqa: F401
    _predict_single,
    _merge_history,
    _save_predictions_to_db,
    _sync_predictions_to_central,
    _json_default,
    _calc_growth_rate,
    _calc_surge_aware_growth_rate,
    _detect_surge_for_ui,
    _online_learning_feedback,
    _update_video_graph,
    _maybe_release_memory,
    _get_up_db,
    _save_up_data,
)

from ui.monitor._service import (  # noqa: F401
    _stop_all_workers,
    _stop_predictor,
    fetch_single_video_data,
    fetch_all_video_data,
    auto_predict_all,
    load_watch_list,
    _load_watch_list_from_db,
    _merged_from_db,
    _merged_from_db_lock,
)
