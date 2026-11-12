"""Application theme (light)."""

from PySide6.QtGui import QColor, QLinearGradient, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#0f6fb8"
ACCENT_DARK = "#0b5187"
ACCENT_SOFT = "#e3f0fb"
ORANGE = "#e8622c"
GREEN = "#16a34a"
TEXT = "#1e293b"
MUTED = "#64748b"
BORDER = "#d5dde7"
PANEL = "#ffffff"
APP_BG = "#eef2f7"

VIEW_TOP = QColor("#ffffff")
VIEW_BOTTOM = QColor("#eef3f9")
GRID_MINOR = QColor("#dde6f0")
GRID_MAJOR = QColor("#c6d3e2")
AXIS_X = QColor("#d94a4a")
AXIS_Y = QColor("#2f9e5f")
AXIS_Z = QColor("#3f74c9")
NODE_COLOR = QColor("#22456b")
NODE_HALO = QColor("#ffffff")
ELEM_BEAM = QColor("#2b3f57")
ELEM_TRUSS = QColor("#5a7391")
ELEM_SHELL = QColor("#7188a5")
SELECTED = QColor("#e8622c")
LOAD_COLOR = QColor("#0f6fb8")
SUPPORT_COLOR = QColor("#2f9e5f")
DEFORMED = QColor("#e8622c")
GHOST = QColor("#9fb0c4")


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(APP_BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.AlternateBase, QColor("#f7f9fc"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#1e3a5f"))
    pal.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
* {{ font-family: 'Segoe UI'; font-size: 12px; color: {TEXT}; }}

QMainWindow, QDialog {{ background: {APP_BG}; }}

QMenuBar {{ background: #ffffff; border-bottom: 1px solid {BORDER}; padding: 2px 4px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}

QMenu {{ background: #ffffff; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 22px; border-radius: 3px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 #f6f8fb);
            border-bottom: 1px solid {BORDER}; spacing: 2px; padding: 3px 6px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 6px 6px; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px;
               padding: 3px 4px; min-width: 46px; font-size: 11px; }}
QToolButton:hover {{ background: #eaf3fb; border: 1px solid #c9dff2; }}
QToolButton:pressed {{ background: #d7e9f8; }}
QToolButton:checked {{ background: {ACCENT_SOFT}; border: 1px solid #a9cdea; }}

QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{ background: #e8eef6; padding: 6px 8px; border-bottom: 1px solid {BORDER};
                      font-weight: 600; color: #33475f; }}

QTreeWidget, QListWidget, QTableWidget, QTableView, QPlainTextEdit, QTextEdit {{
    background: #ffffff; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; alternate-background-color: #f7f9fc; gridline-color: #e6ecf4;
}}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QHeaderView::section {{ background: #eef3f9; border: none; border-right: 1px solid #e0e7f0;
                        border-bottom: 1px solid {BORDER}; padding: 5px 6px; font-weight: 600;
                        color: #33475f; }}
QTableCornerButton::section {{ background: #eef3f9; border: none; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; background: #ffffff; }}
QTabBar::tab {{ background: #e8eef6; border: 1px solid {BORDER}; border-bottom: none;
                padding: 6px 14px; margin-right: 2px; border-top-left-radius: 4px;
                border-top-right-radius: 4px; color: #445a73; }}
QTabBar::tab:selected {{ background: #ffffff; color: {ACCENT_DARK}; font-weight: 600; }}
QTabBar::tab:hover {{ background: #f2f7fc; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #ffffff; border: 1px solid #c8d4e2; border-radius: 3px; padding: 4px 6px;
    min-height: 18px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT}; }}

QPushButton {{ background: #f3f7fb; border: 1px solid #c8d4e2; border-radius: 4px;
               padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: #e9f3fb; border-color: #a9cdea; }}
QPushButton:pressed {{ background: #dbeaf7; }}
QPushButton:default, QPushButton[accent="true"] {{ background: {ACCENT}; border: 1px solid {ACCENT_DARK};
               color: #ffffff; font-weight: 600; }}
QPushButton:default:hover, QPushButton[accent="true"]:hover {{ background: #1380d0; }}
QPushButton:disabled {{ color: #9aa9b9; background: #f0f3f7; }}

QCheckBox, QRadioButton {{ spacing: 6px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; margin-top: 12px; padding-top: 6px;
             background: #ffffff; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT_DARK};
                    font-weight: 600; }}

QSplitter::handle {{ background: #e2e8f0; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: #f2f5f9; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #c3d1e0; min-height: 24px; border-radius: 5px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: #a8bcce; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: #f2f5f9; height: 12px; }}
QScrollBar::handle:horizontal {{ background: #c3d1e0; min-width: 24px; border-radius: 5px; margin: 2px; }}

QToolTip {{ background: #1e3a5f; color: #ffffff; border: none; padding: 4px 6px; }}

/* ---------------------------------------------------------------- ribbon */
QFrame#ribbon {{ background: #f4f7fb; border-bottom: 1px solid #c5d2e0; }}
QFrame#ribbonTabs {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                      stop:0 #eaf0f7, stop:1 #cfdae7);
                     border-bottom: 1px solid #b9c8d8; }}
QFrame#ribbonAccent {{ background: #c0392b; }}
QFrame#ribbonSeparator {{ background: #b6c5d5; max-width: 1px; margin: 6px 4px; }}
QTabBar#ribbonTabBar {{ background: transparent; }}
QTabBar#ribbonTabBar::tab {{ background: transparent; color: #334960;
                             padding: 5px 15px; margin: 2px 1px 0 1px;
                             border: 1px solid transparent;
                             border-top-left-radius: 4px; border-top-right-radius: 4px;
                             font-size: 12px; }}
QTabBar#ribbonTabBar::tab:selected {{ background: #ffffff; color: #102a44;
                                      border: 1px solid #b9c8d8; border-bottom-color: #ffffff;
                                      font-weight: 600; }}
QTabBar#ribbonTabBar::tab:hover:!selected {{ background: rgba(255, 255, 255, 150); }}
QStackedWidget#ribbonStack, QWidget#ribbonPage {{ background: #f4f7fb; }}
QFrame#ribbonGroup {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                      stop:0 #fbfcfe, stop:1 #f0f4f9);
                      border-right: 1px solid #d3dde8; border-left: 1px solid #ffffff; }}
QLabel#ribbonCaption {{ background: #e2e9f2; border-top: 1px solid #d0dbe7;
                        border-bottom: 1px solid #cdd8e4; color: #53667d;
                        font-size: 10px; padding: 0 4px; }}
QLabel#ribbonFieldLabel {{ color: #5b6f86; font-size: 10px; }}
QToolButton#ribbonLarge {{ min-width: 54px; max-width: 88px; padding: 3px;
                           font-size: 10px; border: 1px solid transparent;
                           border-radius: 4px; }}
QToolButton#ribbonLarge:hover {{ background: #e4f0fb; border: 1px solid #b7d5ee; }}
QToolButton#ribbonLarge:pressed {{ background: #d3e7f8; }}
QToolButton#ribbonLarge:checked {{ background: #dcebf9; border: 1px solid #9fc8e8; }}
QToolButton#ribbonSmall {{ min-width: 0; padding: 2px 5px; font-size: 11px;
                           text-align: left; border: 1px solid transparent;
                           border-radius: 3px; }}
QToolButton#ribbonSmall:hover {{ background: #e4f0fb; border: 1px solid #c2dcf1; }}
QToolButton#ribbonSmall:checked {{ background: #dcebf9; border: 1px solid #9fc8e8; }}
QToolButton#ribbonQuick {{ min-width: 22px; max-width: 25px; padding: 1px;
                           border: 1px solid transparent; border-radius: 3px; }}
QToolButton#ribbonQuick:hover {{ background: #ffffff; border: 1px solid #b9c8d8; }}
QToolButton#ribbonApp {{ background: #ffffff; border: 1px solid #b9c8d8;
                         border-radius: 4px; padding: 1px; }}
QToolButton#ribbonApp:hover {{ background: #fff4e8; border-color: #e0a37a; }}
"""
