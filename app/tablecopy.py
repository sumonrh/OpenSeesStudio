"""Excel-compatible copy support for every table in the application."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QTableWidget

_FILTER = None


def table_tsv(table: QTableWidget) -> str:
    """Return the selected cells as tab-separated text."""
    ranges = table.selectedRanges()
    if ranges:
        r0 = min(r.topRow() for r in ranges)
        r1 = max(r.bottomRow() for r in ranges)
        c0 = min(r.leftColumn() for r in ranges)
        c1 = max(r.rightColumn() for r in ranges)
    else:
        r0, r1 = table.currentRow(), table.currentRow()
        c0, c1 = table.currentColumn(), table.currentColumn()
    if r0 < 0 or c0 < 0:
        return ""
    lines = []
    for row in range(r0, r1 + 1):
        cells = []
        for col in range(c0, c1 + 1):
            item = table.item(row, col)
            cells.append(item.text() if item is not None else "")
        lines.append("\t".join(cells))
    return "\n".join(lines)


class TableCopyFilter(QObject):
    """Ctrl+C and right-click Copy for any QTableWidget in the app."""

    def eventFilter(self, obj, event) -> bool:
        if not isinstance(obj, QTableWidget):
            return False
        if event.type() == QEvent.KeyPress and event.matches(QKeySequence.Copy):
            text = table_tsv(obj)
            if text:
                QApplication.clipboard().setText(text)
            return True
        if event.type() == QEvent.ContextMenu:
            menu = QMenu(obj)
            copy = menu.addAction("Copy")
            copy.setShortcut(QKeySequence.Copy)
            copy.setEnabled(bool(obj.selectedRanges()))
            copy.triggered.connect(
                lambda: QApplication.clipboard().setText(table_tsv(obj)))
            select_all = menu.addAction("Select All")
            select_all.triggered.connect(obj.selectAll)
            menu.exec(event.globalPos())
            return True
        return False


def install(app: QApplication) -> None:
    global _FILTER
    if _FILTER is not None:
        return
    _FILTER = TableCopyFilter(app)
    app.installEventFilter(_FILTER)
