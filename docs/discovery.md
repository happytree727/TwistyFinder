# TwistyFinder - Discovery & Design Decisions

Status: DRAFT, 2026-11-17. Pre-code. Pricing and limits below came from quick research and must be re-verified before committing.

Mockups: Paper file "TwistyFinder - Brand & Mockups" (Projects folder), page "Aesthetic directions".

## Product summary

Website first, mobile app later. Free, non-monetized, crowd-funded. Helps motorcycle riders find twisty roads near them.

Differentiators:
1. Location-first: open the site, get a ranked list of twisties near you. No map hunting.
2. Multi-stop route planning with handoff to Google Maps / Apple Maps / Waze (+ GPX).
3. Community: accounts, comments, up/down votes, suggest roads, private friend groups.
4. Smarter detection: filter out curvy neighborhood/subdivision streets.
5. Modern, minimalist design.

## Competitive landscape

| Product | Model | Gap vs. TwistyFinder |
|---|---|---|
| roadcurvature.com | Free web map, KML export | No search/location list, no accounts, no routing, flags neighborhoods and cul-de-sacs |
| Calimoto | Freemium app, ~EUR 60/yr premium | Twisty routing paywalled, GPX export only |
| Scenic | Freemium app, ~$60/yr | Twisty routing/offline paywalled |
| REVER | Freemium, Pro ~$20-40/yr | Ride tracking/social, not discovery; reliability complaints |
| Kurviger | Free web/app planner + subscription | Strong planner, steep learning curve, weak navigator |
| MotorcycleRoads.com | Community website since 1998 | Dated UX, no curvature data, no routing |
| Butler Maps | Paper maps, sold in REVER Pro | Curated, not dynamic |

Takeaways:
- **Free + no paywall** is a real wedge. Every strong competitor paywalls twisty routing.
- **No one offers one-tap multi-stop handoff** to Google/Apple/Waze.
- **No one combines votes + private groups** for road discovery.
- **Neighborhood false positives** are roadcurvature's #1 public complaint.

## Risks to design around

- **OSM license (ODbL):** attribution required in the UI. A publicly distributed derived database (e.g. our scored segment dataset) must be share-alike under ODbL. Fine for an open project; plan for it.
- **Nav handoff limits:**
  - Google Maps URLs support a small number of waypoints (exact limit to verify; reportedly ~9-10 on mobile).
  - Apple Maps URL scheme is officially origin + destination only.
  - Waze deep links take one destination.
  - Design: Google gets the full multi-stop link; Apple/Waze get "leg by leg" handoff (open next stop); GPX for everything else. Say this plainly in the UI.
- **curvature project is GPL v3:** if we reuse its code (not just its idea), our processing pipeline inherits GPL. Probably fine for an open-source hobby project; decide deliberately.

## Twisty detection (false-positive strategy)

Base: roadcurvature's algorithm (circumcircle radius on point triplets, weighted by turn tightness, summed per section). Add the filtering it lacks:

1. **Hard exclude:** `highway` not in {primary, secondary, tertiary, unclassified, residential*}; any `service=*`; `access=private|no`; unpaved `surface`; sections < ~300 m.
2. **Context penalties (multipliers):**
   - `highway=residential` base penalty
   - residential landuse / building density along a 50 m buffer (> ~20 buildings/km)
   - junction / signal / stop density (> ~4/km)
   - high share of dead ends (degree-1 nodes), short loops: subdivision pattern, discard
   - inside town/village polygons
   - `maxspeed` <= 25-35 mph penalty, >= 45 mph bonus
3. **Normalize** per km; keep sections >= ~2 km.
4. **Bonuses:** elevation gain (SRTM / USGS 3DEP), scenic context (forest, water, viewpoints, national forest/park).
5. **Community feedback loop:**
   - votes and "this is a neighborhood" flags keyed by geometry hash (OSM way IDs churn)
   - Bayesian-blended score
   - 3+ neighborhood flags trigger a heavy penalty + review queue
   - later: fit penalty weights from vote data

Tooling: Geofabrik US extract (~11.4 GB PBF) -> osmium tags-filter -> osm2pgsql flex -> PostGIS. Pilot on a single state (e.g. NC or Colorado, a few hundred MB).

## Hosting options (non-AWS)

| Stack | Launch (~1k users) | Growing (~50k MAU) | Ops |
|---|---|---|---|
| **Cheapest:** Cloudflare Pages + R2 (PMTiles) + one Hetzner US VPS (Postgres/PostGIS, app, routing) | ~$25-40/mo | ~$60-150/mo | Highest; you own backups and patching |
| **Least ops:** Supabase Pro (Postgres/PostGIS + Auth) + Cloudflare Pages + R2 + hosted routing (OpenRouteService) | ~$30/mo | ~$100-250/mo | Low |
| **Balanced:** Supabase (DB + Auth) + Hetzner box for routing engine + Cloudflare Pages/R2 | ~$35-60/mo | ~$120-250/mo | Medium |

Notes:
- **Map tiles:** self-host Protomaps PMTiles on Cloudflare R2. Zero egress fees, ~$2/mo storage. Avoids MapTiler/Stadia per-session billing.
- **Batch OSM processing:** run monthly on an hourly-billed Hetzner VM (a few dollars per run) or a home machine with >= 32 GB RAM.
- **Avoid as sole prod:** Oracle Always Free (idle reclaim, no SLA).
- **Verify before committing:** Hetzner US USD pricing, Supabase PostGIS + compute sizing, OpenRouteService free quota.

Leaning: **Balanced**, or Least-ops to start and move routing onto Hetzner when quotas bite.

## Aesthetic directions (Paper)

Each direction has a 1440x900 desktop (primary) and a 390x844 mobile screen.

- **A - Dashboard:** instrument black x amber LED. Space Grotesk + JetBrains Mono. Night-ride, gauge-like data readouts. Strongest "rider tool" feel.
- **B - Alpine:** snow/frost x evergreen, topo contour lines. Instrument Serif + Inter. Calm, premium, cartographic. Most approachable for non-hardcore riders.
- **C - Signage:** white/asphalt x center-line yellow. Archivo condensed + Inter. Road-sign, Swiss-poster boldness. Most distinctive brand, double-yellow route line.

## Decisions (2026-11-17)

1. **Design:** hybrid. **C (Signage)** branding, type, and UI chrome (Archivo condensed + Inter, asphalt + center-line yellow, yellow score badges) on **B's calmer topographic map style**. Light **and dark mode** required. See Paper page "Chosen: Signage x Alpine".
2. **Hosting:** Balanced stack.
   - Cloudflare Pages: frontend
   - Cloudflare R2: Protomaps PMTiles
   - Supabase: Postgres/PostGIS + Auth
   - Hetzner US VPS: routing engine
   - Hourly Hetzner VM: monthly OSM batch
3. **Code:** public repo at github.com/happytree727/TwistyFinder.

## Code hosting

GitHub, public, under the personal `happytree727` account. Personal project, not affiliated with AGI. Commits use the happytree727 no-reply email (set repo-local).
