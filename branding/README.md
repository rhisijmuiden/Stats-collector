# Branding

Every folder here is a brand (huisstijl) that ships with Stats Collector and can be picked in **Admin → Branding → House style**:

- `ijmond360/`: the IJmond360 brand taken from ijmond360.nl (purple `#713C80`, pink `#E92E7F`, Epilogue headings, Inter body text, the IJmond360 logo and icon). This is the default for new installations.
- `default/`: the neutral Stats Collector brand.

Each folder holds:

- `theme.json`: colour tokens for light and dark mode, fonts, per-channel chart colours, corner radius and live wall colours.
- the logo files named under `logo` in `theme.json` (`light`, `dark`, `favicon`); SVG, PNG, WebP, ICO or JPEG.

Administrators change the brand in **Admin → Branding** (logo, favicon, colours, fonts, chart colours). The result applies to the app, PDF reports, interactive reports, emails and the live wall. A brand can be exported as a file and committed here as a new folder, e.g. `branding/<customer>/`; it then appears as a choice after the next update.
