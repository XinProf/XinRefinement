"""导入冒烟测试（P0.1）。"""
import xinrefinement
import xinrefinement.core
import xinrefinement.gui
import xinrefinement.cli
import xinrefinement.i18n


def test_version():
    assert xinrefinement.__version__


def test_import_core():
    assert xinrefinement.core is not None


def test_import_gui():
    assert xinrefinement.gui is not None
