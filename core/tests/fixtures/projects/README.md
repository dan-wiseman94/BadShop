# Historical BadShop projects

These archives were written by the project serializers at the listed Git revisions.
Their synthetic 6×4 RGB input contains two colors and no external assets. Both
projects contain an image attachment, a message referring to the first edit, and
an invert followed by a second filter that uses the first edit's output.

| Fixture | Producer revision | Archive SHA-256 |
| --- | --- | --- |
| `schema-1.badshop` | `adfb45837ab7055b8484579fb6c255f8f04907b7`, last main revision before schema 2 | `2cc97001e005c8fbc6eb1acdc797f03864d3d9df28a48827ab1f0f8b47381c86` |
| `desktop-v0.1.0.badshop` | `54293a48b0a5d2d78eb356f81daed7caf8706ef8`, source tagged `desktop-v0.1.0` | `dd28becac883fe1ea61bfc3822cae3e726cf45612d90cf9727aa7dc71b4f9ea3` |

The schema-1 project uses sepia as its second filter. The shipped schema-2
format fixture keeps that timeline as **Original** and has **Alternate** active,
forked at the invert step with grayscale as its second filter.

Artifact hashes and expected references are pinned in
`test_project_compatibility.py`. Keep these archives fixed when the current
serializer changes so the tests continue to exercise the original format.
