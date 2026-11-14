# Interface themes

The period skins live in `app/src/themes.css`. Their palette and material tokens
also paint the Settings previews. `appearance.ts` owns their names and saved
preference; `ThemeIcon.tsx` supplies local interface icons. Skins do not change
image tools, exported artwork, or session state.

The references establish a visual vocabulary, not an exact reproduction of an
operating system or a particular arcade game:

| Skin | Reference and interpretation |
| --- | --- |
| Classic Desktop, 1995 | [Microsoft's original Windows interface guide](https://ics.uci.edu/~kobsa/courses/ICS104/course-notes/Microsoft_WindowsGuidelines.pdf), especially the visual design section: neutral gray, solid navy title bars, upper-left bevel lighting, sunken white fields, dotted focus and gray default buttons. |
| XP, 2001 | Microsoft's Luna blue visual style: blue window frames, Tahoma text, cream command buttons, orange tab edges, red close buttons and blue list selection. Toolbar icons adapt the existing local drawings with colored outlines and gradients, following [Microsoft's XP icon guidance](https://learn.microsoft.com/en-us/previous-versions/ms997636(v=msdn.10)). No Windows artwork or system font binaries are bundled. |
| Terminal, 1982 | [DEC VT100 User Guide, chapter 3](https://oldmanprogrammer.net/webapps/vt100/doc/vt100-ug/chapter3.html): fixed-pitch text, box rules, restrained phosphor and reverse-video selection. The image viewer remains a modern functional accommodation. |
| GeoCities, 1997 | [Preserved GeoCities homepage](https://www.geocities.ws/Athens/Forum/6777/): tiled wallpaper, serif text, emphatic headings, underlined links, table borders and plain browser form controls. No fabricated visitor counters or dead links. |
| Y2K, 2001 | [Apple's January 2000 Aqua announcement](https://www.apple.com/newsroom/2000/01/05Apple-Unveils-Mac-OS-X/): pinstriped chrome, luminous controls and recessed fields, interpreted as a violet media-player skin. Rounding and gloss belong mainly to controls and window chrome. |
| Paper, 1932 | [Evening Star, September 24, 1932](https://tile.loc.gov/storage-services/service/ndnp/dlc/batch_dlc_1bernal_ver01/data/sn83045462/00280600787/1932092401/0562.pdf): proportional serif text, heavy headlines, black ink, column dividers, fine and double rules. Code retains monospace; ordinary UI is not typewritten. |
| Arcade, 1988 | [Capcom's 1988 sales flyer](https://flyers.arcade-museum.com/videogames/show/5130): cabinet-dark surfaces, saturated limited colors, block lettering and hard trim. This is a cabinet/menu interpretation, not a CRT filter. |

The Arcade display face is the unmodified **Press Start 2P** by CodeMan38, a modern
recreation of arcade lettering. It is bundled locally so the interface works
offline and does not depend on installed fonts. The body uses a readable system
monospace. Font source: [Google Fonts](https://github.com/google/fonts/tree/main/ofl/pressstart2p).
The binary SHA-256 is
`034c77f1f05ec89421e4a63f0e3a4ca1ecf852cc6d2bf611f126f275728e017d`.
Its SIL Open Font License and copyright ship alongside it in
`app/public/fonts/PressStart2P-OFL.txt`.

Keep text scaling, compact density, keyboard focus, native form input behavior,
and selected/disabled states usable in every skin. Never place filters, blend
modes, opacity or overlays on artwork or its ancestors. Decoration belongs on
interface chrome. The focused `app/e2e/retro.spec.ts` skin journeys exercise the
picker, tool dialogs, saved preferences and unchanged artifact bytes, retaining
screenshots for visual inspection.
