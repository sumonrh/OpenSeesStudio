"""Ribbon command bar with tabs, command groups and group captions."""

from __future__ import annotations

from typing import Iterable, List

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy,
                               QStackedWidget, QTabBar, QToolButton,
                               QVBoxLayout, QWidget)


def _tooltip(action: QAction) -> str:
    text = action.statusTip() or action.text()
    shortcut = action.shortcut().toString()
    return f"{text}  [{shortcut}]" if shortcut else text


class RibbonGroup(QFrame):
    """One labelled block inside a ribbon tab."""

    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ribbonGroup")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 0)
        lay.setSpacing(2)

        body = QWidget()
        self.row = QHBoxLayout(body)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(3)
        self.row.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lay.addWidget(body, 1)

        label = QLabel(caption)
        label.setObjectName("ribbonCaption")
        label.setAlignment(Qt.AlignCenter)
        label.setFixedHeight(17)
        lay.addWidget(label)

    # ------------------------------------------------------------------ items
    def add_large(self, action: QAction) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ribbonLarge")
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(26, 26))
        button.setAutoRaise(True)
        button.setFixedHeight(62)
        button.setMinimumWidth(58)
        button.setMaximumWidth(88)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setToolTip(_tooltip(action))
        self.row.addWidget(button)
        return button

    def add_small(self, action: QAction) -> QToolButton:
        button = self._small_button(action)
        self.row.addWidget(button)
        return button

    def _small_button(self, action: QAction) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ribbonSmall")
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(16, 16))
        button.setAutoRaise(True)
        button.setFixedHeight(23)
        button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button.setToolTip(_tooltip(action))
        return button

    def add_column(self, actions: Iterable[QAction]) -> QWidget:
        column = QWidget()
        lay = QVBoxLayout(column)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        for action in actions:
            lay.addWidget(self._small_button(action))
        lay.addStretch(1)
        self.row.addWidget(column)
        return column

    def add_field(self, text: str, widget: QWidget) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(2, 2, 2, 0)
        lay.setSpacing(2)
        label = QLabel(text)
        label.setObjectName("ribbonFieldLabel")
        lay.addWidget(label)
        lay.addWidget(widget)
        lay.addStretch(1)
        self.row.addWidget(box)
        return box

    def add_widget(self, widget: QWidget) -> QWidget:
        self.row.addWidget(widget)
        return widget


class RibbonTab(QWidget):
    """A page of ribbon command groups."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ribbonPage")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(3, 2, 3, 3)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def add_group(self, caption: str) -> RibbonGroup:
        group = RibbonGroup(caption)
        self.layout.addWidget(group)
        return group


class Ribbon(QFrame):
    """Tab bar plus command pages, placed in the main window menu area."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ribbon")
        self.setFixedHeight(136)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tabs_row = QFrame()
        tabs_row.setObjectName("ribbonTabs")
        tabs_row.setFixedHeight(31)
        bar = QHBoxLayout(tabs_row)
        bar.setContentsMargins(5, 0, 8, 0)
        bar.setSpacing(2)

        self.app_button = QToolButton()
        self.app_button.setObjectName("ribbonApp")
        self.app_button.setAutoRaise(True)
        self.app_button.setPopupMode(QToolButton.InstantPopup)
        self.app_button.setToolTip("File menu: new, open, save, export and exit")
        self.app_menu = QMenu(self.app_button)
        self.app_button.setMenu(self.app_menu)
        bar.addWidget(self.app_button)

        self._quick = QHBoxLayout()
        self._quick.setContentsMargins(0, 0, 3, 0)
        self._quick.setSpacing(0)
        bar.addLayout(self._quick)

        separator = QFrame()
        separator.setObjectName("ribbonSeparator")
        separator.setFrameShape(QFrame.VLine)
        bar.addWidget(separator)

        self.tabs = QTabBar()
        self.tabs.setObjectName("ribbonTabBar")
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setDrawBase(False)
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.currentChanged.connect(self._tab_changed)
        bar.addWidget(self.tabs)
        bar.addStretch(1)

        outer.addWidget(tabs_row)

        accent = QFrame()
        accent.setObjectName("ribbonAccent")
        accent.setFixedHeight(2)
        outer.addWidget(accent)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ribbonStack")
        outer.addWidget(self.stack, 1)

        self._pages: List[RibbonTab] = []

    # ------------------------------------------------------------------- tabs
    def add_tab(self, title: str) -> RibbonTab:
        page = RibbonTab()
        self._pages.append(page)
        self.stack.addWidget(page)
        self.tabs.addTab(title)
        return page

    def set_current(self, title: str) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == title:
                self.tabs.setCurrentIndex(index)
                return

    def current_title(self) -> str:
        index = self.tabs.currentIndex()
        return self.tabs.tabText(index) if index >= 0 else ""

    def _tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._pages):
            self.stack.setCurrentIndex(index)

    # ------------------------------------------------------------------ extras
    def set_app_icon(self, icon: QIcon) -> None:
        self.app_button.setIcon(icon)
        self.app_button.setIconSize(QSize(20, 20))

    def add_quick(self, action: QAction) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ribbonQuick")
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setIconSize(QSize(16, 16))
        button.setAutoRaise(True)
        button.setFixedSize(25, 24)
        button.setToolTip(_tooltip(action))
        self._quick.addWidget(button)
        return button
