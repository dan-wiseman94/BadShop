# Third-party notices

Badshop is MIT licensed (see LICENSE). The deterministic engine uses Pillow (HPND),
NumPy (BSD-3-Clause), OpenCV (Apache-2.0), ONNX Runtime (MIT), rembg (MIT), Pydantic (MIT),
LiteLLM (MIT), keyring (MIT), platformdirs (MIT), websockets (BSD-3-Clause), psutil
(BSD-3-Clause), MCP Python SDK (MIT), and PyInstaller (GPL-2.0-or-later with bundling exception).
The desktop uses Tauri and its plugins (MIT/Apache-2.0), React (MIT), Vite (MIT),
TanStack Query (MIT), Zustand (MIT), RJSF (Apache-2.0), and Tailwind CSS (MIT).

Builds include installed Python distribution license files plus a `legal/` directory with
`sbom.json`, dependency notices and `coverage.json`. JavaScript production dependencies,
the resolved Cargo graph and the installed Python build environment are inventoried;
the latter two include build tools and packages for other targets. This is broader than
the executable's runtime contents. License texts come from installed upstream packages,
not lockfiles. The coverage file explicitly lists packages without a notice file for
release review. Metadata and an SPDX expression do not replace required license notices.

Supplemental notices retain immutable upstream source references in the SBOM. Missing notice
files fail packaging. The separate manual-review list must still be resolved before public
redistribution, including upstream Apple SDK-derived binding questions. Unmodified MPL Cargo
package sources are included in `legal/covered-source/`; see each component's property for its
relative source directory. The inventory is not an automatic legal-compatibility determination.

The interface bundles the unmodified Press Start 2P font by CodeMan38 under the SIL
Open Font License 1.1. Its copyright and license are included at
`app/public/fonts/PressStart2P-OFL.txt` (distributed as `fonts/PressStart2P-OFL.txt`
in the frontend). This font is used for the Arcade interface, not image processing.

Engine models and fonts are downloaded separately into the user's app data directory. See
`docs/model-licenses.md` for model sources and license review. Fonts Anton and Comic Neue are
SIL Open Font License 1.1. Twemoji images are CC-BY 4.0; users must retain fetched images'
source/creator/license attributions. Public image sources can impose additional conditions.
No general copyright license is granted by retrieving an image through badshop.
