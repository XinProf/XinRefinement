"""「关于 XinRefinement」与「版权与许可」对话框（版式继承 XinMatch 家族规范）。

小 Logo + 软件名 + 版本 + 定位/功能简介 + 联系方式 + 版权/许可。
版权主体（PolyXRD Team）、联系方式（sshztx@outlook.com）与双许可
（Academic / Commercial，见根目录 LICENSE / LICENSE-CN）**继承自
XinMatch**，家族内保持一致。

v1.6.1：用户要求「帮助页加上版权和许可」。除了 About 里那两行摘要，新增
独立的 :class:`LicenseDialog`——可滚动查看许可**全文**（安装目录里的
``LICENSE`` / ``LICENSE-CN``，打包时随 ``licenses/`` 一起分发）。
许可正文只读磁盘、不在代码里复写一份，避免两处文本漂移。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

import xinrefinement
from xinrefinement.gui.assets import load_pixmap
from xinrefinement.i18n import get_language, tr

_ACCENT = "#0D285C"  # 家族品牌色（科技蓝调深）


def license_path(lang: str | None = None) -> Path | None:
    """定位许可全文文件（打包后 ``licenses/`` 下，源码树为仓库根）。"""
    name = "LICENSE" if (lang or get_language()) == "en" else "LICENSE-CN"
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    # 源码 / onedir：包目录上两级即仓库根
    roots.append(Path(__file__).resolve().parents[2])
    roots.append(Path(sys.executable).resolve().parent)
    for root in roots:
        for candidate in (root / "licenses" / name, root / name):
            if candidate.is_file():
                return candidate
    return None


def license_text(lang: str | None = None) -> str:
    """许可全文；文件缺失时回落到一句说明（不编造条款）。"""
    path = license_path(lang)
    if path is None:
        return tr("license.missing")
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return tr("license.missing")


class LicenseDialog(QtWidgets.QDialog):
    """版权与许可：摘要 + 可滚动全文。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("license.title"))
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)

        head = QtWidgets.QLabel(tr("license.head"))
        font = head.font()
        font.setPointSizeF(font.pointSizeF() + 1.5)
        font.setBold(True)
        head.setFont(font)
        head.setStyleSheet(f"color: {_ACCENT};")
        layout.addWidget(head)

        summary = QtWidgets.QLabel(tr("license.summary"))
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #555;")
        layout.addWidget(summary)

        self.view = QtWidgets.QTextBrowser()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
        self.view.setStyleSheet(
            "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 11px;")
        self.view.setPlainText(license_text())
        self.view.setMinimumSize(560, 380)
        layout.addWidget(self.view, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.resize(620, 520)


class AboutDialog(QtWidgets.QDialog):
    """模态关于对话框。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 XinRefinement")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(8)

        # --- 顶部行：小 Logo（左）+ 软件名 / 版本（右） -----------------
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(16)

        logo_label = QtWidgets.QLabel()
        pix = load_pixmap("logo_transparent.png")
        if pix.isNull():
            pix = load_pixmap("logo.png")
        if not pix.isNull():
            pix = pix.scaled(
                96, 96,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        logo_label.setPixmap(pix)
        logo_label.setFixedSize(96, 96)
        logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.addWidget(logo_label)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)

        title = QtWidgets.QLabel("XinRefinement")
        title.setStyleSheet(f"color: {_ACCENT};")
        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)
        title_col.addWidget(title)

        version_label = QtWidgets.QLabel(f"版本 {xinrefinement.__version__}")
        version_label.setStyleSheet("color: #777;")
        title_col.addWidget(version_label)

        # 构建变体：正式版显示注册状态，内部评估版明确标注（同 XinMatch）
        from xinrefinement import build_variant

        reg = getattr(parent, "_registration", None)
        if build_variant.is_release():
            status = reg.state.status_text if reg is not None else "未注册"
            variant_text = f"正式版 · {status}"
            variant_style = "color: #777;"
        else:
            variant_text = "内部评估版 · 未启用注册机制"
            variant_style = "color: #d32f2f; font-weight: bold;"
        variant_label = QtWidgets.QLabel(variant_text)
        variant_label.setStyleSheet(variant_style)
        title_col.addWidget(variant_label)

        title_col.addStretch(1)
        header.addLayout(title_col)
        header.addStretch(1)
        layout.addLayout(header)

        # --- 分隔线 -----------------------------------------------------
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addSpacing(4)
        layout.addWidget(line)
        layout.addSpacing(6)

        # --- 定位与功能简介 ---------------------------------------------
        role = QtWidgets.QLabel("X 射线衍射全谱拟合 / 结构精修软件")
        role.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = role.font()
        font.setPointSize(10)
        role.setFont(font)
        layout.addWidget(role)

        features = QtWidgets.QLabel(
            "Rietveld / Le Bail 全谱拟合 · 多物相定量 (QPA) · "
            "微结构与择优取向 · e.s.d. 不确定度"
        )
        features.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        features.setStyleSheet("color: #777;")
        layout.addWidget(features)

        layout.addSpacing(8)

        # --- 联系方式（mailto 可点击） ----------------------------------
        contact = QtWidgets.QLabel(
            '联系方式：<a href="mailto:sshztx@outlook.com" '
            f'style="color:{_ACCENT}">sshztx@outlook.com</a>'
        )
        contact.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        contact.setOpenExternalLinks(True)
        contact.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        layout.addWidget(contact)

        # --- 版权与许可（继承 XinMatch / PolyXRD Team） -----------------
        copyright_label = QtWidgets.QLabel("©2026 版权所有 · PolyXRD Team")
        copyright_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        copyright_label.setStyleSheet("color: #999;")
        layout.addWidget(copyright_label)

        license_label = QtWidgets.QLabel(
            "双许可：Academic / Commercial（详见安装目录 LICENSE 文件）"
        )
        license_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        license_label.setStyleSheet("color: #999;")
        layout.addWidget(license_label)

        layout.addSpacing(10)

        # --- 确定按钮 ---------------------------------------------------
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("确定")
        # v1.6.1：版权行旁边给一个直接看许可全文的入口
        self.btn_license = buttons.addButton(
            tr("license.view"),
            QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_license.clicked.connect(self._show_license)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setMinimumWidth(420)

    def _show_license(self) -> None:
        """关于页 → 许可全文（模态叠模态，关闭后回到关于页）。"""
        LicenseDialog(self).exec()
