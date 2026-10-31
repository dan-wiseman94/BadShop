# Models, fonts and image attribution

The app explicitly selects a model for background removal; it never uses rembg's default
model selection. No generative image model is used. Models are downloaded on demand,
not embedded in installers. The exact files, sizes and published hashes live in
`core/src/badshop/engine/manifest.py`.

Reviewed against upstream sources on 2026-10-31:

| Asset | Upstream terms/source | Distribution in badshop |
|---|---|---|
| u2net, u2net_human_seg | [U²-Net Apache-2.0 license](https://github.com/xuebinqin/U-2-Net/blob/master/LICENSE) and [upstream checkpoints](https://github.com/xuebinqin/U-2-Net) | Explicit ONNX conversions linked by [rembg](https://github.com/danielgatis/rembg#models), pinned MD5 and size |
| isnet-anime | [SkyTNT anime-segmentation Apache-2.0 license](https://github.com/SkyTNT/anime-segmentation/blob/main/LICENSE) | Explicit rembg ONNX conversion, pinned MD5 and size |
| birefnet-general | [BiRefNet MIT license](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE); [official model card](https://huggingface.co/ZhengPeng7/BiRefNet) also declares MIT | Explicit general epoch-244 ONNX conversion, pinned MD5 and size |
| YuNet | [OpenCV Zoo model license](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | Pinned detector file and SHA-256 |
| Anton, Comic Neue | [Google Fonts Anton](https://github.com/google/fonts/tree/main/ofl/anton), [Comic Neue](https://github.com/google/fonts/tree/main/ofl/comicneue), SIL OFL 1.1 | Pinned font files and SHA-256 |
| Twemoji graphics | [CC-BY 4.0 artwork license](https://github.com/jdecked/twemoji/blob/main/LICENSE-GRAPHICS) | Per-image attribution in source metadata |

`bria-rmbg` is not offered. Model licensing is separate from the MIT license of rembg itself.
Retain the applicable upstream license and notices when redistributing downloaded files.

Retrieved photos keep their page, URL, creator and available license metadata in the
project. Unknown metadata is shown as unknown; a missing label is not a permission grant.
Wikipedia image attribution is queried from the file metadata API when a file name is
available. User imports retain provenance but do not imply ownership or licensing.

The installer includes `THIRD_PARTY_NOTICES.md`, Python distribution metadata/license files,
and `dependencies.json`. Source lockfiles record JS and Rust dependencies.
