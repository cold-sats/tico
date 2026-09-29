# Tico icon

`tico.svg` is the user-supplied master icon, with no background. Its charcoal face
and teal details are the artwork, and the surrounding canvas is transparent.

- `tico-monochrome.svg`: selected monochrome identity, with transparent eye cutouts.
- `tico-slack.png`: transparent monochrome 512×512 export for the installed Slack app.
- `tico-tile.svg` / `tico-tile-mac.svg`: the mark in off-white on an opaque teal tile, generated;
  a transparent charcoal mark vanished on iOS home screens and the dark Dock (2026-09-15).
- `tico-1024.png`: the Mac tile (inset rounded square) for the native app's icon bundle.
- `tico-menubar.svg` / `tico-menubar.png`: monochrome mark with transparent eye
  cutouts. AppKit loads the PNG as an 18-point template image and handles light
  and dark menu bars. Status and recording details remain in the tooltip/menu.
- `../icon-192.png` / `../icon-512.png`: the full-bleed teal tile for the web app (iOS rounds it).

Run `python3 scripts/tico-icons.py` from the repository to regenerate the exports
(requires `rsvg-convert`, available through Homebrew's `librsvg`). Then rebuild
the native app with `scripts/app.sh build` to include the updated icons.

The COO avatar uses the monochrome SVG. The tab favicon uses `tico-tile.svg` (off-white
on teal) so the mark stays visible on dark browser chrome; a charcoal mark reads as a
black blob there. The earlier generated options in `concepts/` are unused explorations.
