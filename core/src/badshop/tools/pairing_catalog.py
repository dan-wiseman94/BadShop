"""Source pairing tool, available identically to manual users and art directors."""
from badshop.engine.pairing import PairImagesParams, pair_images
from badshop.tools.registry import ToolSpec, register

register(ToolSpec(
    name="pair_images", params=PairImagesParams, category="compose",
    run=pair_images,
    summary="compare subjects and backgrounds with hard-paste previews",
    description=("Rank combinations of donor and background artifacts by geometry, face area and available "
                 "space. Returns only a contact sheet plus pairs with exact paste_params. Supply cutouts when "
                 "ready; otherwise each preview pastes the whole donor and you should cut the subject before "
                 "using fit_box. Scores do not infer identity, expression or facing direction: inspect the "
                 "sheet to choose a pair that makes the joke work. target_box uses each background's pixels."),
))
