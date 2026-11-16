"""Toolbar customization dialog."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)


class ToolbarCustomizeDialog(QDialog):
    """Choose and order the actions shown in one toolbar."""

    def __init__(self, title: str, actions: Sequence[Tuple[str, str]],
                 current: Sequence[str], defaults: Sequence[str] = (),
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 500)
        self._actions: List[Tuple[str, str]] = list(actions)
        self._defaults = list(defaults)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Add buttons from the left list, remove them from the right list, "
            "and use Up/Down to arrange the toolbar."))

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Available buttons"))
        self.available = QListWidget()
        self.available.itemDoubleClicked.connect(lambda _item: self._add())
        left.addWidget(self.available)
        body.addLayout(left, 1)

        middle = QVBoxLayout()
        middle.addStretch(1)
        add = QPushButton("Add >")
        add.clicked.connect(self._add)
        remove = QPushButton("< Remove")
        remove.clicked.connect(self._remove)
        up = QPushButton("Move up")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("Move down")
        down.clicked.connect(lambda: self._move(1))
        for button in (add, remove, up, down):
            middle.addWidget(button)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset)
        middle.addSpacing(12)
        middle.addWidget(reset)
        middle.addStretch(1)
        body.addLayout(middle)

        right = QVBoxLayout()
        right.addWidget(QLabel("Toolbar buttons (top to bottom)"))
        self.current = QListWidget()
        self.current.itemDoubleClicked.connect(lambda _item: self._remove())
        right.addWidget(self.current)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._set_current(current)
        self._refresh_available()

    # ------------------------------------------------------------------ state
    def _set_current(self, keys: Iterable[str]) -> None:
        self.current.clear()
        for key in keys:
            if key == "separator":
                item = QListWidgetItem("Separator")
            else:
                item = QListWidgetItem(self._label(key))
            item.setData(Qt.UserRole, key)
            self.current.addItem(item)
        if self.current.count():
            self.current.setCurrentRow(0)

    def _label(self, key: str) -> str:
        for action_key, label in self._actions:
            if action_key == key:
                return label
        return key

    def _refresh_available(self) -> None:
        used = {self.current.item(i).data(Qt.UserRole)
                for i in range(self.current.count())}
        selected = (self.available.currentItem().data(Qt.UserRole)
                    if self.available.currentItem() else None)
        self.available.clear()
        for key, label in self._actions:
            if key in used:
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.available.addItem(item)
            if key == selected:
                self.available.setCurrentItem(item)

    # ---------------------------------------------------------------- actions
    def _add(self) -> None:
        item = self.available.currentItem()
        if item is None:
            return
        key = item.data(Qt.UserRole)
        new_item = QListWidgetItem("Separator" if key == "separator"
                                   else self._label(key))
        new_item.setData(Qt.UserRole, key)
        self.current.addItem(new_item)
        self.current.setCurrentItem(new_item)
        self._refresh_available()

    def _remove(self) -> None:
        row = self.current.currentRow()
        if row < 0:
            return
        self.current.takeItem(row)
        self._refresh_available()

    def _move(self, delta: int) -> None:
        row = self.current.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.current.count()):
            return
        item = self.current.takeItem(row)
        self.current.insertItem(target, item)
        self.current.setCurrentRow(target)

    def _reset(self) -> None:
        self._set_current(self._defaults or [])
        self._refresh_available()

    def selected_keys(self) -> List[str]:
        return [self.current.item(i).data(Qt.UserRole)
                for i in range(self.current.count())]
