PRIMARY = "#2563eb"

STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: #1e293b;
}}
QMainWindow, QDialog {{ background: #f1f5f9; }}

QFrame#Card {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}}
QLabel#Title {{ font-size: 18pt; font-weight: 600; color: #0f172a; }}
QLabel#Subtitle {{ color: #64748b; }}
QLabel#Section {{ font-weight: 600; color: #334155; }}
QLabel#Muted {{ color: #64748b; font-size: 9pt; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus, QListWidget:focus {{
    border: 1px solid {PRIMARY};
}}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"], QListWidget[invalid="true"], QSpinBox[invalid="true"] {{
    border: 1px solid #dc2626;
    background: #fef2f2;
}}
QLineEdit:read-only {{ background: #f8fafc; color: #475569; }}

QPushButton {{
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: #f8fafc; border-color: #94a3b8; }}
QPushButton:disabled {{ color: #94a3b8; background: #f1f5f9; }}
QPushButton#Primary {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY};
    color: #ffffff;
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#Primary:hover {{ background: #1d4ed8; }}
QPushButton#Primary:disabled {{ background: #93c5fd; border-color: #93c5fd; }}
QPushButton#Link {{
    border: none; background: transparent; color: {PRIMARY}; padding: 2px 4px;
}}
QPushButton#Link:hover {{ text-decoration: underline; }}

QLabel#Banner {{ border-radius: 6px; padding: 9px 11px; }}
QLabel#Banner[kind="error"] {{ background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; }}
QLabel#Banner[kind="warn"]  {{ background: #fffbeb; border: 1px solid #fde68a; color: #92400e; }}
QLabel#Banner[kind="ok"]    {{ background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; }}
QLabel#Banner[kind="info"]  {{ background: #eff6ff; border: 1px solid #bfdbfe; color: #1e40af; }}

QPlainTextEdit#ProtocolLog {{
    font-family: "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 9pt;
    background: #0f172a;
    color: #e2e8f0;
    border: 1px solid #1e293b;
}}
QGroupBox {{
    border: 1px solid #e2e8f0; border-radius: 8px; margin-top: 14px; background: #ffffff;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #334155; font-weight: 600; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #e2e8f0; }}
"""
