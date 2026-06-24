import itertools
from typing import Iterable, Optional

from anki.models import TemplateDict
from anki.notes import NoteId
import aqt

from .flashcard_topology import indices, NoteTopology, TopologyDialog
from .gui import ClipsViewDialog
from .models import roundup, write_template, translate_template

class ClipsTopology(NoteTopology):
    @staticmethod
    def description() -> str:
        return "Sentence Listening"

    def make_templates(self, order: int) -> Iterable[TemplateDict]:
        manager = self.mw.col.models
        return itertools.chain(*((
            write_template(manager, order, i),
            translate_template(manager, order, i),
        ) for i in indices(order)))

    @staticmethod
    def make_fields(order: int) -> Iterable[str]:
        return itertools.chain(*((
            f"Clip {i}", f"Word {i}", f"Translation {i}",
        ) for i in indices(order)))

    def custom_css(self, order: int) -> str:
        return ""

    def sort_field(self, order: int) -> int:
        return 1

    @staticmethod
    def next_order(order: Optional[int] = None) -> int:
        return roundup(order or 3, True)

    @staticmethod
    def measure_order(fields: dict[str, str]) -> int:
        i = 1
        while (f"Clip {i}" in fields and f"Word {i}" in fields
            and f"Translation {i}" in fields):
            i += 1
        return i - 1

    def make_editor(
        self, fields: dict[str, str], note_id: Optional[NoteId]
    ) -> TopologyDialog:
        return ClipsViewDialog(fields, note_id, self)

ClipsTopology(aqt.mw)
