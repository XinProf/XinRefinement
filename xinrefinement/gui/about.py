"""「关于 XinRefinement」对话框（版式继承 XinMatch 家族规范）。

小 Logo + 软件名 + 版本 + 定位/功能简介 + 联系方式 + 版权/许可。
版权主体（PolyXRD Team）、联系方式（sshztx@outlook.com）与双许可
（Academic / Commercial，见根目录 LICENSE / LICENSE-CN）**继承自
XinMatch**，家族内保持一致。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

import xinrefinement
from xinrefinement.gui.assets import load_pixmap

_ACCENT = "#0D285C"  # 家族品牌色（科技蓝调深）


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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setMinimumWidth(420)
