"""e2e fixture: <data>/hooks.py. Acts only on decks made with the "desk" template, so the
other specs see no change."""


def after_slide(slide):
    if slide.layout_group == "desk":
        slide.content["title"] = "Desk: " + str(slide.content.get("title", ""))


def before_export(deck):
    if deck["slides"] and deck["slides"][0]["layout_group"] == "desk":
        for slide in deck["slides"]:
            slide["content"]["title"] = slide["content"]["title"] + " [export]"
