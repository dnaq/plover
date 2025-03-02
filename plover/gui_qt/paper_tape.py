import time

from PyQt5.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Qt,
)
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFileDialog,
    QFontDialog,
    QMessageBox,
)

from wcwidth import wcwidth

from plover import _, system

from plover.gui_qt.paper_tape_ui import Ui_PaperTape
from plover.gui_qt.utils import ToolBar
from plover.gui_qt.tool import Tool


STYLE_PAPER, STYLE_RAW = (
    # i18n: Paper tape style.
    _('Paper'),
    # i18n: Paper tape style.
    _('Raw'),
)
TAPE_STYLES = (STYLE_PAPER, STYLE_RAW)


class TapeModel(QAbstractListModel):

    def __init__(self):
        super().__init__()
        self._stroke_list = []
        self._style = None
        self._all_keys = None
        self._numbers = None

    def rowCount(self, parent):
        return 0 if parent.isValid() else len(self._stroke_list)

    @property
    def style(self):
        return self._style

    @style.setter
    def style(self, style):
        assert style in TAPE_STYLES
        self.layoutAboutToBeChanged.emit()
        self._style = style
        self.layoutChanged.emit()

    def _paper_format(self, stroke):
        text = self._all_keys_filler * 1
        keys = stroke.steno_keys[:]
        if any(key in self._numbers for key in keys):
            keys.append('#')
        for key in keys:
            index = system.KEY_ORDER[key]
            text[index] = self._all_keys[index]
        return ''.join(text)

    @staticmethod
    def _raw_format(stroke):
        return stroke.rtfcre

    def headerData(self, section, orientation, role):
        if (section != 0 or orientation != Qt.Horizontal or
            role != Qt.DisplayRole or self._style != STYLE_PAPER):
            return None
        return self._all_keys

    def data(self, index, role):
        if not index.isValid():
            return None
        stroke = self._stroke_list[index.row()]
        if role == Qt.DisplayRole:
            if self._style == STYLE_PAPER:
                return self._paper_format(stroke)
            if self._style == STYLE_RAW:
                return self._raw_format(stroke)
        if role == Qt.AccessibleTextRole:
            return stroke.rtfcre
        return None

    def reset(self):
        self.modelAboutToBeReset.emit()
        self._all_keys = ''.join(key.strip('-') for key in system.KEYS)
        self._all_keys_filler = [
            ' ' * wcwidth(k)
            for k in self._all_keys
        ]
        self._numbers = set(system.NUMBERS.values())
        self._stroke_list.clear()
        self.modelReset.emit()
        return self._all_keys

    def append(self, stroke):
        row = len(self._stroke_list)
        self.beginInsertRows(QModelIndex(), row, row)
        self._stroke_list.append(stroke)
        self.endInsertRows()


class PaperTape(Tool, Ui_PaperTape):

    # i18n: Widget: “PaperTape”, tooltip.
    __doc__ = _('Paper tape display of strokes.')

    TITLE = _('Paper Tape')
    ICON = ':/tape.svg'
    ROLE = 'paper_tape'
    SHORTCUT = 'Ctrl+T'

    def __init__(self, engine):
        super().__init__(engine)
        self.setupUi(self)
        self._model = TapeModel()
        self.header.setContentsMargins(4, 0, 0, 0)
        self.styles.addItems(TAPE_STYLES)
        self.tape.setModel(self._model)
        # Toolbar.
        self.layout().addWidget(ToolBar(
            self.action_ToggleOnTop,
            self.action_SelectFont,
            self.action_Clear,
            self.action_Save,
        ))
        self.action_Clear.setEnabled(False)
        self.action_Save.setEnabled(False)
        engine.signal_connect('config_changed', self.on_config_changed)
        self.on_config_changed(engine.config)
        engine.signal_connect('stroked', self.on_stroke)
        self.tape.setFocus()
        self.restore_state()
        self.finished.connect(self.save_state)

    def _restore_state(self, settings):
        style = settings.value('style', None, int)
        if style is not None:
            style = TAPE_STYLES[style]
            self.styles.setCurrentText(style)
            self.on_style_changed(style)
        font_string = settings.value('font')
        if font_string is not None:
            font = QFont()
            if font.fromString(font_string):
                self.header.setFont(font)
                self.tape.setFont(font)
        ontop = settings.value('ontop', None, bool)
        if ontop is not None:
            self.action_ToggleOnTop.setChecked(ontop)
            self.on_toggle_ontop(ontop)

    def _save_state(self, settings):
        settings.setValue('style', TAPE_STYLES.index(self._style))
        settings.setValue('font', self.tape.font().toString())
        ontop = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        settings.setValue('ontop', ontop)

    def on_config_changed(self, config):
        if 'system_name' in config:
            self._model.reset()

    @property
    def _scroll_at_end(self):
        scrollbar = self.tape.verticalScrollBar()
        return scrollbar.value() == scrollbar.maximum()

    @property
    def _style(self):
        return self.styles.currentText()

    def on_stroke(self, stroke):
        scroll_at_end = self._scroll_at_end
        self._model.append(stroke)
        if scroll_at_end:
            self.tape.scrollToBottom()
        self.action_Clear.setEnabled(True)
        self.action_Save.setEnabled(True)

    def on_style_changed(self, style):
        assert style in TAPE_STYLES
        scroll_at_end = self._scroll_at_end
        self._model.style = style
        self.header.setVisible(style == STYLE_PAPER)
        if scroll_at_end:
            self.tape.scrollToBottom()

    def on_select_font(self):
        font, ok = QFontDialog.getFont(self.tape.font(), self, '',
                                       QFontDialog.MonospacedFonts)
        if ok:
            self.header.setFont(font)
            self.tape.setFont(font)

    def on_toggle_ontop(self, ontop):
        flags = self.windowFlags()
        if ontop:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def on_clear(self):
        flags = self.windowFlags()
        msgbox = QMessageBox()
        msgbox.setText(_('Do you want to clear the paper tape?'))
        msgbox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        # Make sure the message box ends up above the paper tape!
        msgbox.setWindowFlags(msgbox.windowFlags() | (flags & Qt.WindowStaysOnTopHint))
        if QMessageBox.Yes != msgbox.exec_():
            return
        self._strokes = []
        self.action_Clear.setEnabled(False)
        self.action_Save.setEnabled(False)
        self._model.reset()

    def on_save(self):
        filename_suggestion = 'steno-notes-%s.txt' % time.strftime('%Y-%m-%d-%H-%M')
        filename = QFileDialog.getSaveFileName(
            self, _('Save Paper Tape'), filename_suggestion,
            # i18n: Paper tape, "save" file picker.
            _('Text files (*.txt)'),
        )[0]
        if not filename:
            return
        with open(filename, 'w') as fp:
            for row in range(self._model.rowCount(self._model.index(-1, -1))):
                print(self._model.data(self._model.index(row, 0), Qt.DisplayRole), file=fp)
