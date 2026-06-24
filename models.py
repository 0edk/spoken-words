from anki.models import ModelManager, TemplateDict

from .flashcard_topology import indices

def delimited(word_count: int, i: int) -> str:
    return " ".join(
        f"[sound:start_beep.mp3] {{{{Clip {j}}}}} [sound:end_beep.mp3]"
        if j == i else f"{{{{Clip {j}}}}}" for j in indices(word_count)
    )

def write_template(
    manager: ModelManager, word_count: int, i: int
) -> TemplateDict:
    template = manager.new_template(f"Write {i}")
    template["qfmt"] = (f"{{{{#Clip {i}}}}}" + delimited(
        word_count, i
    ) + f" <strong>&#x270E;</strong>{{{{/Clip {i}}}}}")
    template["afmt"] = ("{{{{FrontSide}}}}\n<hr id=answer>\n"
        f"{{{{Word {i}}}}}")
    return template

def translate_template(
    manager: ModelManager, word_count: int, i: int
) -> TemplateDict:
    template = manager.new_template(f"Translate {i}")
    template["qfmt"] = (f"{{{{#Clip {i}}}}}" + delimited(
        word_count, i
    ) + f" <strong>&#x21C4;</strong>{{{{/Clip {i}}}}}")
    template["afmt"] = ("{{{{FrontSide}}}}\n<hr id=answer>\n"
        f"{{{{Translation {i}}}}}")
    return template
