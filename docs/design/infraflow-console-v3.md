# InfraFlow Console v3 — workbench direction

**Reason for revision:** The v2 navigation bar, rounded panels, repeated status tiles and default Windows typography felt like a generic generated dashboard. The user asked for a more deliberate font and visual structure.

## Visual decisions

- Use a quiet, light desktop workbench: 228px utility rail, main area devoted to Environment data, no decorative hero or KPI blocks. At 900px and below, navigation becomes a horizontal strip that can scroll.
- Use self-hosted IBM Plex Sans for interface text and Vietnamese glyphs. The two variable WOFF2 subsets and OFL license live in `web/fonts/`; the app has no runtime font CDN dependency. Keep system fallbacks.
- Font source: `@fontsource-variable/ibm-plex-sans` v5.3.0, [IBM Plex](https://github.com/IBM/plex), [Fontsource package](https://fontsource.org/fonts/ibm-plex-sans/about). The bundled license is `web/fonts/OFL.txt`.
- Wordmark is plain InfraFlow text with a 3px blue rule. The earlier blue square with an initial was a placeholder logo and is removed visually.
- Use square-cornered controls and restrained borders. Status is conveyed with text, a small label and, for urgent list rows, a left rule. Color never carries the meaning alone.
- Environment Detail presents management, observed, actual and desired as ruled facts rather than four competing cards. Operation in progress remains the highlighted decision cue.
- Sign-in uses a simple top brand band so a logged-out user does not see an empty desktop rail. The Password focus ring stays 20px clear of the button.

## Product and accessibility limits

The v1 Product UX specification still governs roles, flows and state copy. This revision changes visual presentation only. The existing API still does not provide Register, verified ownership classification or step-by-step operation evidence. Browser screenshots use mocked responses and do not validate AWS behavior.

## Review points

1. Compare the actual 1440px and 375px screenshots against the previous version for hierarchy and visual noise.
2. Check mobile navigation and Environment rows at 320px, including no page overflow.
3. Check Latin and Vietnamese font subsets load locally; inspect fallback behavior if webfonts fail.
4. Check BLOCKED, active operation, sign-in focus and public Wake states without assuming a successful backend result.
