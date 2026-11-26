"""List model behind the live console."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot


class LogModel(QAbstractListModel):
    TextRole = Qt.UserRole + 1
    LevelRole = Qt.UserRole + 2
    TimeRole = Qt.UserRole + 3
    MAX_ROWS = 5000
    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, str, str]] = []

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    def roleNames(self):
        return {self.TextRole: b"text", self.LevelRole: b"level", self.TimeRole: b"time"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        text, level, stamp = self._rows[index.row()]
        return {self.TextRole: text, self.LevelRole: level, self.TimeRole: stamp}.get(role)

    def append(self, text: str, level: str = "info") -> None:
        if len(self._rows) >= self.MAX_ROWS:
            self.beginRemoveRows(QModelIndex(), 0, 499)
            del self._rows[:500]
            self.endRemoveRows()
        pos = len(self._rows)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._rows.append((text, level, datetime.now().strftime("%H:%M:%S")))
        self.endInsertRows()
        self.countChanged.emit()

    @Slot()
    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()
        self.countChanged.emit()

    @Slot(result=str)
    def asText(self) -> str:
        return "\n".join(f"{t}  {x}" for x, _l, t in self._rows)
