from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import Settings, load_settings
from app.db.connection import Database
from app.db.migrations import current_schema_version, run_migrations
from app.db.repository import Repository
from app.feedback.manager import FeedbackManager
from app.ingestion.importer import ImportService
from app.ocr.image_io import configure_tesseract_executable
from app.search.engine import SearchEngine
from app.services.export import (
    all_entities_csv,
    review_queue_csv,
    serial_harvest_conflicts_csv,
    serial_harvest_csv,
    serial_harvest_review_csv,
    serial_harvest_rows,
    serial_harvest_txt,
    serial_rows_csv,
)


class ImportThread(QThread):
    progress = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_url: str, settings: Settings, folder: Path, backend: str) -> None:
        super().__init__()
        self.database_url = database_url
        self.settings = settings
        self.folder = folder
        self.backend = backend

    def run(self) -> None:
        try:
            database = Database(self.database_url)
            service = ImportService(database, self.settings)
            result = service.import_folder(
                self.folder,
                backend=self.backend,
                progress_callback=self.progress.emit,
            )
            self.finished_ok.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class PhotoIntelligenceWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.database = Database(self.settings.database_url)
        with self.database.session() as conn:
            run_migrations(conn)

        self.import_thread: ImportThread | None = None
        self.current_photo_id: str | None = None
        self.current_query_id: str | None = None
        self.current_query_fingerprint = ""
        self.current_query_text = ""
        self.current_result_rank: int | None = None
        self.search_results: list[dict[str, Any]] = []
        self.zoom_factor = 1.0
        self.current_pixmap: QPixmap | None = None

        self.setWindowTitle("Photo Intelligence")
        self.resize(1320, 820)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.dashboard_tab = self._build_dashboard_tab()
        self.import_tab = self._build_import_tab()
        self.search_tab = self._build_search_tab()
        self.detail_tab = self._build_detail_tab()
        self.review_tab = self._build_review_tab()
        self.export_tab = self._build_export_tab()

        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.import_tab, "Import")
        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.detail_tab, "Photo Detail")
        self.tabs.addTab(self.review_tab, "Review Queue")
        self.tabs.addTab(self.export_tab, "Export")

        self.refresh_dashboard()
        self.refresh_review_queue()

    def _repo(self) -> Repository:
        raise RuntimeError("Use database.session() for repository operations.")

    def _build_dashboard_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        status_box = QGroupBox("System Status")
        form = QFormLayout(status_box)
        self.db_status_label = QLabel()
        self.schema_version_label = QLabel()
        self.tesseract_status_label = QLabel()
        self.photo_count_label = QLabel()
        self.entity_count_label = QLabel()
        self.review_count_label = QLabel()
        self.last_job_label = QLabel()
        form.addRow("Database", self.db_status_label)
        form.addRow("Schema version", self.schema_version_label)
        form.addRow("Tesseract", self.tesseract_status_label)
        form.addRow("Photos", self.photo_count_label)
        form.addRow("Entities", self.entity_count_label)
        form.addRow("Review needed", self.review_count_label)
        form.addRow("Last import job", self.last_job_label)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_dashboard)
        layout.addWidget(status_box)
        layout.addWidget(refresh, alignment=Qt.AlignLeft)
        layout.addStretch()
        return widget

    def _build_import_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        row = QHBoxLayout()
        self.import_folder_input = QLineEdit(str(self.settings.import_folder))
        browse = QPushButton("Choose Folder")
        browse.clicked.connect(self.choose_import_folder)
        row.addWidget(self.import_folder_input)
        row.addWidget(browse)

        controls = QHBoxLayout()
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("audit", "audit")
        self.backend_combo.addItem("barcode", "barcode")
        self.backend_combo.addItem("ocr", "tesseract")
        self.backend_combo.addItem("auto", "auto")
        self.start_import_button = QPushButton("Start Import")
        self.start_import_button.clicked.connect(self.start_import)
        controls.addWidget(QLabel("Backend"))
        controls.addWidget(self.backend_combo)
        controls.addWidget(self.start_import_button)
        controls.addStretch()

        self.import_progress = QProgressBar()
        self.import_progress.setRange(0, 1)
        self.import_progress.setValue(0)
        self.import_log = QPlainTextEdit()
        self.import_log.setReadOnly(True)

        layout.addLayout(row)
        layout.addLayout(controls)
        layout.addWidget(self.import_progress)
        layout.addWidget(QLabel("Progress, skipped files, and failures"))
        layout.addWidget(self.import_log)
        return widget

    def _build_search_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("PO 11234 SN MT2331FT15720")
        self.search_mode_combo = QComboBox()
        self.search_mode_combo.addItem("Fast Search", "fast")
        self.search_mode_combo.addItem("Deep Search", "deep")
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.run_search)
        self.search_input.returnPressed.connect(self.run_search)
        row.addWidget(self.search_input)
        row.addWidget(self.search_mode_combo)
        row.addWidget(search_button)

        self.search_diagnostics_label = QLabel()
        self.results_table = QTableWidget(0, 6)
        self.results_table.setHorizontalHeaderLabels(["Score", "File", "Status", "Sources", "Reasons", "Path"])
        self.results_table.cellDoubleClicked.connect(self.open_search_result)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addLayout(row)
        layout.addWidget(self.search_diagnostics_label)
        layout.addWidget(self.results_table)
        return widget

    def _build_detail_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        nav = QHBoxLayout()
        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.open_full_button = QPushButton("Open Full Size")
        self.zoom_in_button = QPushButton("Zoom In")
        self.zoom_out_button = QPushButton("Zoom Out")
        self.fit_button = QPushButton("Fit")
        self.previous_button.clicked.connect(lambda: self.navigate_photo("previous"))
        self.next_button.clicked.connect(lambda: self.navigate_photo("next"))
        self.open_full_button.clicked.connect(self.open_full_photo)
        self.zoom_in_button.clicked.connect(lambda: self.adjust_zoom(1.25))
        self.zoom_out_button.clicked.connect(lambda: self.adjust_zoom(0.8))
        self.fit_button.clicked.connect(self.fit_photo)
        for button in (
            self.previous_button,
            self.next_button,
            self.open_full_button,
            self.zoom_in_button,
            self.zoom_out_button,
            self.fit_button,
        ):
            nav.addWidget(button)
        nav.addStretch()

        splitter = QSplitter()
        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        self.photo_path_label = QLabel("No photo selected")
        self.opened_from_query_label = QLabel("")
        self.opened_from_query_label.setStyleSheet("color: #5c6670;")
        self.mismatch_label = QLabel()
        self.mismatch_label.setStyleSheet("color: #a53232; font-weight: 700;")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setWidgetResizable(True)
        image_layout.addWidget(self.photo_path_label)
        image_layout.addWidget(self.opened_from_query_label)
        image_layout.addWidget(self.mismatch_label)
        image_layout.addWidget(self.image_scroll)

        evidence_panel = QWidget()
        evidence_layout = QVBoxLayout(evidence_panel)
        self.entities_text = QTextEdit()
        self.entities_text.setReadOnly(True)
        self.barcodes_text = QTextEdit()
        self.barcodes_text.setReadOnly(True)
        self.ocr_text = QTextEdit()
        self.ocr_text.setReadOnly(True)

        correction_box = QGroupBox("Correction")
        correction_layout = QGridLayout(correction_box)
        self.correction_type = QComboBox()
        for value in (
            "serial_number",
            "printed_serial_number",
            "barcode_serial_number",
            "purchase_order",
            "sales_order",
            "part_number",
            "model_number",
        ):
            self.correction_type.addItem(value)
        self.correction_value = QLineEdit()
        save_correction = QPushButton("Save Correction")
        save_correction.clicked.connect(self.save_correction)
        self.correct_button = QPushButton("Mark Correct")
        self.wrong_button = QPushButton("Mark Wrong")
        self.review_button = QPushButton("Needs Review")
        self.correct_button.clicked.connect(lambda: self.send_feedback("correct"))
        self.wrong_button.clicked.connect(lambda: self.send_feedback("wrong"))
        self.review_button.clicked.connect(lambda: self.send_feedback("needs_review"))
        correction_layout.addWidget(self.correction_type, 0, 0)
        correction_layout.addWidget(self.correction_value, 0, 1)
        correction_layout.addWidget(save_correction, 0, 2)
        correction_layout.addWidget(self.correct_button, 1, 0)
        correction_layout.addWidget(self.wrong_button, 1, 1)
        correction_layout.addWidget(self.review_button, 1, 2)

        evidence_layout.addWidget(QLabel("Extracted Entities"))
        evidence_layout.addWidget(self.entities_text)
        evidence_layout.addWidget(QLabel("Barcode / QR Values"))
        evidence_layout.addWidget(self.barcodes_text)
        evidence_layout.addWidget(QLabel("OCR Text"))
        evidence_layout.addWidget(self.ocr_text)
        evidence_layout.addWidget(correction_box)

        splitter.addWidget(image_panel)
        splitter.addWidget(evidence_panel)
        splitter.setSizes([620, 700])

        layout.addLayout(nav)
        layout.addWidget(splitter)
        return widget

    def _build_review_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_review_queue)
        resolve = QPushButton("Mark Resolved")
        confirm = QPushButton("Confirm Mismatch")
        false_positive = QPushButton("False Positive")
        resolve.clicked.connect(lambda: self.resolve_selected_review("resolved"))
        confirm.clicked.connect(lambda: self.resolve_selected_review("confirmed_mismatch"))
        false_positive.clicked.connect(lambda: self.resolve_selected_review("false_positive"))
        controls.addWidget(refresh)
        controls.addWidget(resolve)
        controls.addWidget(confirm)
        controls.addWidget(false_positive)
        controls.addStretch()

        self.review_table = QTableWidget(0, 5)
        self.review_table.setHorizontalHeaderLabels(["Priority", "Status", "Reason", "File", "Review ID"])
        self.review_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addLayout(controls)
        layout.addWidget(self.review_table)
        return widget

    def _build_export_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        harvest_box = QGroupBox("Serial Harvest - simple unique serial list")
        harvest_layout = QVBoxLayout(harvest_box)
        harvest_filter_row = QHBoxLayout()
        self.harvest_scope_combo = QComboBox()
        self.harvest_date_from_input = QLineEdit()
        self.harvest_date_to_input = QLineEdit()
        self.harvest_gap_input = QLineEdit("10")
        self.harvest_date_from_input.setPlaceholderText("From date YYYY-MM-DD optional")
        self.harvest_date_to_input.setPlaceholderText("To date YYYY-MM-DD optional")
        self.harvest_gap_input.setPlaceholderText("Photo gap")
        self.harvest_gap_input.setMaximumWidth(90)
        harvest_filter_row.addWidget(QLabel("Scope"))
        harvest_filter_row.addWidget(self.harvest_scope_combo, stretch=2)
        harvest_filter_row.addWidget(QLabel("Date"))
        harvest_filter_row.addWidget(self.harvest_date_from_input)
        harvest_filter_row.addWidget(self.harvest_date_to_input)
        harvest_filter_row.addWidget(QLabel("New group gap"))
        harvest_filter_row.addWidget(self.harvest_gap_input)

        harvest_button_row = QHBoxLayout()
        harvest_preview = QPushButton("Generate Preview")
        harvest_copy = QPushButton("Copy Serials Only")
        harvest_export = QPushButton("Export TXT + CSV")
        harvest_refresh = QPushButton("Refresh Sessions")
        harvest_preview.clicked.connect(self.generate_serial_harvest_preview)
        harvest_copy.clicked.connect(self.copy_serial_harvest_to_clipboard)
        harvest_export.clicked.connect(self.export_serial_harvest_files)
        harvest_refresh.clicked.connect(self.refresh_harvest_sessions)
        harvest_button_row.addWidget(harvest_preview)
        harvest_button_row.addWidget(harvest_copy)
        harvest_button_row.addWidget(harvest_export)
        harvest_button_row.addWidget(harvest_refresh)
        harvest_button_row.addStretch()

        self.harvest_summary_label = QLabel("Generate preview to see unique serial count.")
        self.harvest_text = QPlainTextEdit()
        self.harvest_text.setReadOnly(True)
        self.harvest_text.setPlaceholderText("Unique serial numbers will appear here, one per line.")
        harvest_layout.addLayout(harvest_filter_row)
        harvest_layout.addLayout(harvest_button_row)
        harvest_layout.addWidget(self.harvest_summary_label)
        harvest_layout.addWidget(self.harvest_text)

        detailed_box = QGroupBox("Detailed audit exports")
        detailed_layout = QVBoxLayout(detailed_box)
        serial_button = QPushButton("Export Serial Rows CSV")
        entities_button = QPushButton("Export All Entities CSV")
        review_button = QPushButton("Export Review Queue CSV")
        serial_button.clicked.connect(lambda: self.export_csv("serial"))
        entities_button.clicked.connect(lambda: self.export_csv("entities"))
        review_button.clicked.connect(lambda: self.export_csv("review"))
        detailed_layout.addWidget(serial_button, alignment=Qt.AlignLeft)
        detailed_layout.addWidget(entities_button, alignment=Qt.AlignLeft)
        detailed_layout.addWidget(review_button, alignment=Qt.AlignLeft)

        self.export_log = QPlainTextEdit()
        self.export_log.setReadOnly(True)
        layout.addWidget(harvest_box)
        layout.addWidget(detailed_box)
        layout.addWidget(QLabel("Export log"))
        layout.addWidget(self.export_log)
        self.refresh_harvest_sessions()
        return widget

    def refresh_dashboard(self) -> None:
        try:
            with self.database.session() as conn:
                run_migrations(conn)
                repo = Repository(conn)
                photo_count = repo.photo_count()
                entity_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM entities WHERE is_current = 1"
                ).fetchone()["count"]
                review_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM review_queue WHERE status = 'open'"
                ).fetchone()["count"]
                last_job = conn.execute(
                    "SELECT status, source_path, updated_at FROM import_jobs ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                schema_version = current_schema_version(conn)
            tesseract = configure_tesseract_executable()
            self.db_status_label.setText(self.settings.database_url)
            self.schema_version_label.setText(str(schema_version))
            self.tesseract_status_label.setText(tesseract or "Not found")
            self.photo_count_label.setText(str(photo_count))
            self.entity_count_label.setText(str(entity_count))
            self.review_count_label.setText(str(review_count))
            if last_job:
                self.last_job_label.setText(
                    f"{last_job['status']} | {last_job['updated_at']} | {last_job['source_path']}"
                )
            else:
                self.last_job_label.setText("No import jobs yet")
        except Exception as exc:
            self.show_error("Dashboard refresh failed", exc)

    def choose_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose photo folder", self.import_folder_input.text())
        if folder:
            self.import_folder_input.setText(folder)

    def start_import(self) -> None:
        folder = Path(self.import_folder_input.text())
        if not folder.exists():
            QMessageBox.warning(self, "Import", f"Folder does not exist:\n{folder}")
            return
        if self.import_thread and self.import_thread.isRunning():
            QMessageBox.information(self, "Import", "An import is already running.")
            return
        backend = self.backend_combo.currentData()
        self.import_log.appendPlainText(f"Starting import: {folder}")
        self.import_progress.setRange(0, 0)
        self.start_import_button.setEnabled(False)
        self.import_thread = ImportThread(self.settings.database_url, self.settings, folder, backend)
        self.import_thread.progress.connect(self.import_log.appendPlainText)
        self.import_thread.finished_ok.connect(self.import_finished)
        self.import_thread.failed.connect(self.import_failed)
        self.import_thread.start()

    def import_finished(self, result: dict) -> None:
        self.import_progress.setRange(0, 1)
        self.import_progress.setValue(1)
        self.start_import_button.setEnabled(True)
        self.import_log.appendPlainText(f"Finished: {result}")
        self.refresh_dashboard()
        self.refresh_review_queue()
        self.refresh_harvest_sessions()

    def import_failed(self, error: str) -> None:
        self.import_progress.setRange(0, 1)
        self.import_progress.setValue(0)
        self.start_import_button.setEnabled(True)
        self.import_log.appendPlainText(error)
        QMessageBox.critical(self, "Import failed", error[:4000])

    def run_search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            return
        try:
            mode = self.search_mode_combo.currentData()
            with self.database.session() as conn:
                result = SearchEngine(Repository(conn)).search(query, limit=200, mode=mode)
            self.current_query_id = result["query_id"]
            self.current_query_fingerprint = result["query_fingerprint"]
            self.current_query_text = query
            self.current_result_rank = None
            self.search_results = result["results"]
            warning = f" | {result['warning']}" if result.get("warning") else ""
            self.search_diagnostics_label.setText(
                f"Mode: {result['search_mode']} | candidates: {result['candidate_count']} "
                f"| total photos: {result['total_photo_count']} | deep scan: {result['used_deep_scan']}{warning}"
            )
            self.results_table.setRowCount(len(self.search_results))
            for row_idx, item in enumerate(self.search_results):
                values = [
                    str(item["score"]),
                    Path(item["path"]).name,
                    item.get("status", ""),
                    " | ".join(item.get("match_sources", [])),
                    " | ".join(item.get("reasons", [])),
                    item["path"],
                ]
                for col_idx, value in enumerate(values):
                    table_item = QTableWidgetItem(value)
                    table_item.setData(Qt.UserRole, item["photo_id"])
                    self.results_table.setItem(row_idx, col_idx, table_item)
            self.results_table.resizeColumnsToContents()
        except Exception as exc:
            self.show_error("Search failed", exc)

    def open_search_result(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.search_results):
            return
        item = self.search_results[row]
        try:
            with self.database.session() as conn:
                Repository(conn).record_search_click(
                    item["photo_id"],
                    query_id=item.get("query_id"),
                    result_rank=item.get("rank"),
                    action="open",
                    query_fingerprint=item.get("query_fingerprint", ""),
                )
        except Exception:
            pass
        self.load_photo_detail(
            item["photo_id"],
            query_id=item.get("query_id"),
            query_fingerprint=item.get("query_fingerprint", ""),
            query_text=self.current_query_text,
            result_rank=item.get("rank"),
        )

    def load_photo_detail(
        self,
        photo_id: str,
        query_id: str | None = None,
        query_fingerprint: str = "",
        query_text: str = "",
        result_rank: int | None = None,
    ) -> None:
        try:
            with self.database.session() as conn:
                item = Repository(conn).get_photo(photo_id)
            if not item:
                QMessageBox.warning(self, "Photo detail", "Photo not found.")
                return
            self.current_photo_id = photo_id
            self.current_query_id = query_id or self.current_query_id
            self.current_query_fingerprint = query_fingerprint or self.current_query_fingerprint
            self.current_query_text = query_text or self.current_query_text
            self.current_result_rank = result_rank if result_rank is not None else self.current_result_rank
            self.tabs.setCurrentWidget(self.detail_tab)
            self.photo_path_label.setText(item["path"])
            if self.current_query_text and self.current_result_rank:
                self.opened_from_query_label.setText(
                    f"Opened from query: {self.current_query_text}, rank {self.current_result_rank}"
                )
            else:
                self.opened_from_query_label.setText("")
            self.entities_text.setPlainText(self._format_entities(item.get("entities", []), item.get("context", [])))
            self.barcodes_text.setPlainText("\n".join(row["value"] for row in item.get("raw_barcodes", [])))
            self.ocr_text.setPlainText("\n\n---\n\n".join(row["text"] for row in item.get("raw_ocr", [])))
            self.mismatch_label.setText(self._mismatch_text(item.get("entities", [])))
            self._set_navigation_enabled(item.get("navigation") or {})
            self.load_image_preview(item)
        except Exception as exc:
            self.show_error("Photo detail failed", exc)

    def _format_entities(self, entities: list[dict], context: list[dict]) -> str:
        lines = []
        for entity in entities:
            lines.append(
                f"{entity['entity_type']}: {entity['value']} "
                f"({entity['confidence']}, {entity['source_type']})"
            )
        for ctx in context:
            lines.append(
                f"context {ctx['entity_type']}: {ctx['value']} "
                f"({ctx['confidence']}) - {ctx['reason']}"
            )
        return "\n".join(lines)

    def _mismatch_text(self, entities: list[dict]) -> str:
        printed = sorted({e["value"] for e in entities if e["entity_type"] == "printed_serial_number"})
        barcode = sorted({e["value"] for e in entities if e["entity_type"] == "barcode_serial_number"})
        if printed and barcode and set(printed) != set(barcode):
            return f"Printed/barcode mismatch: printed={printed} barcode={barcode}"
        if printed and not barcode:
            return "Printed-only serial evidence"
        if barcode and not printed:
            return "Barcode-only serial evidence; review physical label if needed"
        return ""

    def _set_navigation_enabled(self, navigation: dict) -> None:
        previous = navigation.get("previous")
        next_item = navigation.get("next")
        self.previous_button.setEnabled(bool(previous))
        self.next_button.setEnabled(bool(next_item))
        self.previous_button.setProperty("photo_id", previous["id"] if previous else "")
        self.next_button.setProperty("photo_id", next_item["id"] if next_item else "")

    def load_image_preview(self, item: dict) -> None:
        path = Path(item.get("thumbnail_path") or item.get("storage_path") or item.get("path") or "")
        if not path.exists():
            path = Path(item.get("path") or "")
        self.current_pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
        self.zoom_factor = 1.0
        self.fit_photo()

    def fit_photo(self) -> None:
        if not self.current_pixmap or self.current_pixmap.isNull():
            self.image_label.setText("No preview available")
            return
        viewport = self.image_scroll.viewport().size()
        scaled = self.current_pixmap.scaled(
            viewport.width() - 12,
            viewport.height() - 12,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def adjust_zoom(self, factor: float) -> None:
        if not self.current_pixmap or self.current_pixmap.isNull():
            return
        self.zoom_factor *= factor
        width = max(100, int(self.current_pixmap.width() * self.zoom_factor))
        height = max(100, int(self.current_pixmap.height() * self.zoom_factor))
        self.image_label.setPixmap(
            self.current_pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def navigate_photo(self, direction: str) -> None:
        button = self.previous_button if direction == "previous" else self.next_button
        photo_id = button.property("photo_id")
        if photo_id:
            self.current_result_rank = None
            self.load_photo_detail(
                str(photo_id),
                self.current_query_id,
                self.current_query_fingerprint,
                self.current_query_text,
                None,
            )

    def open_full_photo(self) -> None:
        if not self.current_photo_id:
            return
        with self.database.session() as conn:
            item = Repository(conn).get_photo(self.current_photo_id)
        if not item:
            return
        path = Path(item.get("storage_path") or item.get("path") or item.get("original_path") or "")
        if path.exists():
            os.startfile(str(path))  # type: ignore[attr-defined]

    def save_correction(self) -> None:
        if not self.current_photo_id:
            return
        value = self.correction_value.text().strip()
        if not value:
            return
        try:
            with self.database.session() as conn:
                FeedbackManager(Repository(conn)).add_correction(
                    self.current_photo_id,
                    self.correction_type.currentText(),
                    value,
                    corrected_by="desktop",
                )
            self.correction_value.clear()
            self.load_photo_detail(self.current_photo_id)
        except Exception as exc:
            self.show_error("Correction failed", exc)

    def send_feedback(self, rating: str) -> None:
        if not self.current_photo_id:
            return
        try:
            with self.database.session() as conn:
                FeedbackManager(Repository(conn)).add_feedback(
                    self.current_photo_id,
                    rating,
                    query_id=self.current_query_id,
                    query_fingerprint=self.current_query_fingerprint,
                    result_rank=self.current_result_rank,
                )
            QMessageBox.information(self, "Feedback", f"Saved feedback: {rating}")
        except Exception as exc:
            self.show_error("Feedback failed", exc)

    def refresh_review_queue(self) -> None:
        try:
            with self.database.session() as conn:
                rows = Repository(conn).list_review_queue(status="open", limit=500)
            self.review_table.setRowCount(len(rows))
            for row_idx, item in enumerate(rows):
                values = [
                    str(item["priority"]),
                    item["status"],
                    item["reason"],
                    Path(item["path"]).name,
                    item["id"],
                ]
                for col_idx, value in enumerate(values):
                    table_item = QTableWidgetItem(value)
                    table_item.setData(Qt.UserRole, item["id"])
                    self.review_table.setItem(row_idx, col_idx, table_item)
            self.review_table.resizeColumnsToContents()
            self.refresh_dashboard()
        except Exception as exc:
            self.show_error("Review refresh failed", exc)

    def selected_review_id(self) -> str | None:
        row = self.review_table.currentRow()
        if row < 0:
            return None
        item = self.review_table.item(row, 4)
        return item.text() if item else None

    def resolve_selected_review(self, action: str) -> None:
        review_id = self.selected_review_id()
        if not review_id:
            return
        try:
            with self.database.session() as conn:
                Repository(conn).resolve_review_item(review_id, action)
            self.refresh_review_queue()
        except Exception as exc:
            self.show_error("Review update failed", exc)


    def refresh_harvest_sessions(self) -> None:
        if not hasattr(self, "harvest_scope_combo"):
            return
        current = self.harvest_scope_combo.currentData()
        self.harvest_scope_combo.blockSignals(True)
        self.harvest_scope_combo.clear()
        self.harvest_scope_combo.addItem("Latest import session", "__latest__")
        self.harvest_scope_combo.addItem("All photos in database", "")
        try:
            with self.database.session() as conn:
                rows = conn.execute(
                    """
                    SELECT id, source_path, status, started_at, imported_count
                    FROM import_sessions
                    ORDER BY started_at DESC
                    LIMIT 100
                    """
                ).fetchall()
            for row in rows:
                source = Path(row["source_path"] or "").name or str(row["source_path"] or "")
                label = f"{row['started_at']} | {row['imported_count']} photos | {source}"
                self.harvest_scope_combo.addItem(label, row["id"])
            if current is not None:
                index = self.harvest_scope_combo.findData(current)
                if index >= 0:
                    self.harvest_scope_combo.setCurrentIndex(index)
        except Exception as exc:
            if hasattr(self, "export_log"):
                self.export_log.appendPlainText(f"Could not refresh import sessions: {exc}")
        finally:
            self.harvest_scope_combo.blockSignals(False)

    def _latest_harvest_session_id(self, conn) -> str | None:
        row = conn.execute(
            """
            SELECT id
            FROM import_sessions
            WHERE imported_count > 0
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        return str(row["id"]) if row else None

    def _selected_harvest_session_id(self, conn) -> str | None:
        scope = self.harvest_scope_combo.currentData() if hasattr(self, "harvest_scope_combo") else "__latest__"
        if scope == "__latest__":
            return self._latest_harvest_session_id(conn)
        if scope:
            return str(scope)
        return None

    def _build_serial_harvest_rows(self) -> list[dict[str, Any]]:
        with self.database.session() as conn:
            session_id = self._selected_harvest_session_id(conn)
            return serial_harvest_rows(
                Repository(conn),
                session_id=session_id,
                date_from=self.harvest_date_from_input.text(),
                date_to=self.harvest_date_to_input.text(),
                gap_threshold=int(self.harvest_gap_input.text().strip() or "10"),
            )

    def generate_serial_harvest_preview(self) -> None:
        try:
            rows = self._build_serial_harvest_rows()
            review_count = sum(1 for row in rows if row.get("confidence") == "review")
            duplicate_hits = sum(max(0, int(row.get("duplicate_count") or 0) - 1) for row in rows)
            group_count = len({row.get("group_id") for row in rows if row.get("group_id")})
            self.harvest_text.setPlainText(serial_harvest_txt(rows))
            self.harvest_summary_label.setText(
                f"Unique serials: {len(rows)} | groups: {group_count} | review-needed: {review_count} | duplicate detections removed: {duplicate_hits}"
            )
            self.export_log.appendPlainText(f"Serial Harvest preview generated: {len(rows)} unique serials")
        except Exception as exc:
            self.show_error("Serial Harvest failed", exc)

    def copy_serial_harvest_to_clipboard(self) -> None:
        if not self.harvest_text.toPlainText().strip():
            self.generate_serial_harvest_preview()
        QApplication.clipboard().setText(self.harvest_text.toPlainText())
        self.export_log.appendPlainText("Copied Serial Harvest serials to clipboard")

    def export_serial_harvest_files(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Serial Harvest export folder", str(self.settings.export_root))
        if not folder:
            return
        try:
            rows = self._build_serial_harvest_rows()
            output_dir = Path(folder)
            output_dir.mkdir(parents=True, exist_ok=True)
            serials_path = output_dir / "serials_only.txt"
            csv_path = output_dir / "serials_with_photos.csv"
            review_path = output_dir / "review_needed_serials.csv"
            conflicts_path = output_dir / "serial_conflicts_by_photo.csv"
            serials_path.write_text(serial_harvest_txt(rows), encoding="utf-8")
            csv_path.write_text(serial_harvest_csv(rows), encoding="utf-8-sig", newline="")
            review_path.write_text(serial_harvest_review_csv(rows), encoding="utf-8-sig", newline="")
            with self.database.session() as conn:
                conflicts_path.write_text(
                    serial_harvest_conflicts_csv(Repository(conn), session_id=self._selected_harvest_session_id(conn)),
                    encoding="utf-8-sig",
                    newline="",
                )
            self.harvest_text.setPlainText(serial_harvest_txt(rows))
            review_count = sum(1 for row in rows if row.get("confidence") == "review")
            group_count = len({row.get("group_id") for row in rows if row.get("group_id")})
            self.harvest_summary_label.setText(f"Exported {len(rows)} unique serials in {group_count} group(s). Review-needed: {review_count}.")
            self.export_log.appendPlainText(f"Wrote {serials_path}")
            self.export_log.appendPlainText(f"Wrote {csv_path}")
            self.export_log.appendPlainText(f"Wrote {review_path}")
            self.export_log.appendPlainText(f"Wrote {conflicts_path}")
        except Exception as exc:
            self.show_error("Serial Harvest export failed", exc)

    def export_csv(self, kind: str) -> None:
        names = {
            "serial": "serial_rows_printed_vs_barcode_audit.csv",
            "entities": "all_entities.csv",
            "review": "review_queue.csv",
        }
        default = self.settings.export_root / names[kind]
        output, _ = QFileDialog.getSaveFileName(self, "Export CSV", str(default), "CSV files (*.csv)")
        if not output:
            return
        try:
            with self.database.session() as conn:
                repo = Repository(conn)
                if kind == "serial":
                    csv_text = serial_rows_csv(repo)
                elif kind == "entities":
                    csv_text = all_entities_csv(repo)
                else:
                    csv_text = review_queue_csv(repo)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(csv_text, encoding="utf-8-sig", newline="")
            self.export_log.appendPlainText(f"Wrote {output}")
        except Exception as exc:
            self.show_error("Export failed", exc)

    def show_error(self, title: str, exc: BaseException) -> None:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        QMessageBox.critical(self, title, details[:4000])


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Photo Intelligence")
    try:
        window = PhotoIntelligenceWindow()
        window.show()
        smoke_exit_ms = os.environ.get("PHOTO_INTELLIGENCE_SMOKE_EXIT_MS")
        if smoke_exit_ms:
            QTimer.singleShot(int(smoke_exit_ms), app.quit)
        return app.exec()
    except Exception as exc:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        QMessageBox.critical(None, "Photo Intelligence startup failed", details[:4000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
