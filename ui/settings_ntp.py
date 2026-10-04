"""NTP time calibration settings tab."""

from datetime import datetime
import re
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from ui.dialog_base import DialogBase
from ui.invoker import invoke
from ui.theme import C


class SettingsNtpMixin:
    """Build and manage the NTP calibration settings tab."""

    _cfg: dict[str, Any]
    dlg: DialogBase

    if TYPE_CHECKING:

        def _section(self, parent: QWidget, title: str, padding: tuple[int, ...] | None = None) -> QWidget:
            raise NotImplementedError

    def _build_ntp_tab(self, tabs: QTabWidget) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs.addTab(page, "  时间校准  ")

        cfg = self._cfg.get("ntp", {})
        try:
            from utils.ntp_time import refresh_config

            refresh_config(cfg)
        except Exception:
            # Runtime sync remains optional while the settings window is opening.
            pass

        sec = self._section(page, "NTP 时间校准")
        sec_layout = sec.layout()
        if sec_layout is None:
            return

        self.ntp_enabled = QCheckBox("启用 NTP 时间校准")
        self.ntp_enabled.setChecked(bool(cfg.get("enabled", True)))
        self.ntp_enabled.setStyleSheet(f"color: {C['text_2']};")
        sec_layout.addWidget(self.ntp_enabled)

        self.ntp_apply_to_records = QCheckBox("将校准时间应用于监控记录")
        self.ntp_apply_to_records.setChecked(bool(cfg.get("apply_to_records", True)))
        self.ntp_apply_to_records.setStyleSheet(f"color: {C['text_2']};")
        sec_layout.addWidget(self.ntp_apply_to_records)

        hint = QLabel("同步失败或未校准时自动回退本地时间，不阻塞监测")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        sec_layout.addWidget(hint)

        servers = cfg.get("servers", [])
        server_text = ", ".join(str(server).strip() for server in servers if str(server).strip())
        server_row = QWidget()
        server_layout = QHBoxLayout(server_row)
        server_layout.setContentsMargins(0, 2, 0, 2)
        server_label = QLabel("NTP 服务器")
        server_label.setFixedWidth(130)
        server_label.setStyleSheet(f"color: {C['text_2']};")
        server_layout.addWidget(server_label)
        self.ntp_servers = QLineEdit(server_text)
        self.ntp_servers.setPlaceholderText("多个服务器用逗号分隔，例如 ntp.aliyun.com")
        self.ntp_servers.setStyleSheet(f"background-color: {C['bg_base']}; color: {C['text_1']};")
        server_layout.addWidget(self.ntp_servers, 1)
        sec_layout.addWidget(server_row)

        interval = QSpinBox()
        interval.setRange(1, 168)
        interval.setValue(max(1, min(168, int(float(cfg.get("auto_sync_hours", 6))))))
        interval.setSuffix(" 小时")
        self.ntp_auto_sync_hours = interval
        interval_row = QWidget()
        interval_layout = QHBoxLayout(interval_row)
        interval_layout.setContentsMargins(0, 2, 0, 2)
        interval_label = QLabel("自动同步间隔")
        interval_label.setFixedWidth(130)
        interval_label.setStyleSheet(f"color: {C['text_2']};")
        interval_layout.addWidget(interval_label)
        interval_layout.addWidget(interval)
        interval_layout.addStretch()
        sec_layout.addWidget(interval_row)

        action_row = QWidget()
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 6, 0, 0)
        self.ntp_sync_button = QPushButton("立即同步")
        self.ntp_sync_button.clicked.connect(self._sync_ntp_now)
        action_layout.addWidget(self.ntp_sync_button)
        self.ntp_operation_label = QLabel()
        self.ntp_status_label = QLabel()
        self.ntp_offset_label = QLabel()
        self.ntp_last_sync_label = QLabel()
        self.ntp_source_label = QLabel()
        for label in (
            self.ntp_operation_label,
            self.ntp_status_label,
            self.ntp_offset_label,
            self.ntp_last_sync_label,
            self.ntp_source_label,
        ):
            label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
            action_layout.addWidget(label)
        action_layout.addStretch()
        sec_layout.addWidget(action_row)
        self._refresh_ntp_status()

    @staticmethod
    def _ntp_servers_from_text(text: str) -> list[str]:
        result: list[str] = []
        for item in re.split(r"[,，]", text):
            server = item.strip()
            if server and server not in result:
                result.append(server)
        return result

    def _refresh_ntp_status(self, status: dict[str, Any] | None = None) -> None:
        if status is None:
            try:
                from utils.ntp_time import get_status

                status = get_status()
            except Exception:
                status = {}
        synced = bool(status.get("synced", False))
        quality = str(status.get("quality", "local_unsynced"))
        freshness = str(status.get("freshness", "never"))
        error = str(status.get("last_error", "") or "")
        quality_text = {"ntp_verified": "NTP 已验证", "http_coarse": "HTTP 粗校准"}.get(quality, "本地未校准")
        freshness_text = {"stale": "，已陈旧", "expired": "，已过期"}.get(freshness, "")
        state_text = quality_text + freshness_text
        if error:
            state_text += f"；最近同步：{error}" if synced else f"：{error}"
        self.ntp_status_label.setText(f"状态：{state_text}")
        offset = float(status.get("offset_ms", 0.0) or 0.0)
        self.ntp_offset_label.setText(f"偏差：{offset:+.2f} ms")
        timestamp = float(status.get("last_sync_ts", 0.0) or 0.0)
        last_sync = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "未同步"
        self.ntp_last_sync_label.setText(f"上次同步：{last_sync}")
        server = str(status.get("server", "") or "")
        source = str(status.get("source", "") or "")
        source_text = f"{server}（{source}）" if server or source else "—"
        self.ntp_source_label.setText(f"来源：{source_text}")

    def _sync_ntp_now(self) -> None:
        servers = self._ntp_servers_from_text(self.ntp_servers.text())
        if not servers:
            QMessageBox.warning(self.dlg, "无法同步", "请先填写至少一个有效的 NTP 服务器主机名。")
            return
        self.ntp_sync_button.setEnabled(False)
        self.ntp_sync_button.setText("同步中…")
        self.ntp_operation_label.setText("本次操作：同步中…")

        def _worker() -> None:
            try:
                from utils.ntp_time import get_status, sync_now

                result = sync_now(servers=servers)
                operation = "成功" if result.ok else f"失败：{result.error}"
                status = get_status()
            except Exception as exc:
                operation = f"失败：{exc}"
                status = None
            invoke(lambda: self._finish_ntp_sync(operation, status))

        from threading import Thread

        Thread(target=_worker, daemon=True).start()

    def _finish_ntp_sync(self, operation: str, status: dict[str, Any] | None) -> None:
        self.ntp_sync_button.setEnabled(True)
        self.ntp_sync_button.setText("立即同步")
        self.ntp_operation_label.setText(f"本次操作：{operation}")
        self._refresh_ntp_status(status)

    def _validate_ntp_settings(self) -> bool:
        if not self.ntp_enabled.isChecked():
            return True
        servers = self._ntp_servers_from_text(self.ntp_servers.text())
        hostname = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
        if not servers or any(not hostname.fullmatch(server) for server in servers):
            QMessageBox.warning(self.dlg, "设置有误", "启用 NTP 时间校准时，请填写有效的服务器主机名。")
            return False
        return True

    def _collect_ntp_settings(self) -> None:
        ntp_cfg = dict(self._cfg.get("ntp", {}))
        ntp_cfg.update(
            {
                "enabled": bool(self.ntp_enabled.isChecked()),
                "apply_to_records": bool(self.ntp_apply_to_records.isChecked()),
                "servers": self._ntp_servers_from_text(self.ntp_servers.text()),
                "auto_sync_hours": float(self.ntp_auto_sync_hours.value()),
            }
        )
        self._cfg["ntp"] = ntp_cfg
