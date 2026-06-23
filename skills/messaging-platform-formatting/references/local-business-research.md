# Local Business Research — Workflow & Pitfalls

Developed during Jim's Colorado Springs spa/sauna lookup (Jun 2026).

## Recommended sequence

1. **web_search** — broad category + city query to surface top results and Yelp snippets
2. **web_extract** — pull 2-3 business websites directly (hours, amenities, prices at source)
3. **Targeted confirmation search** — specific query for the key detail (e.g. `"steam room" "Colorado Springs"`)
4. **Cross-check Reddit** — `site:reddit.com/r/ColoradoSprings` often has current local intel
5. **Call to confirm** — if hours/price/amenity are ambiguous, note "worth calling" in the response

## Yelp is unreliable — do not treat as primary

- `web_extract` on yelp.com → `Failed to fetch url`
- `browser_navigate` on yelp.com → DataDome CAPTCHA, blocked
- **What works:** `web_search` with `site:yelp.com` surfaces description snippets from search results — useful for business names and ratings but NOT full listings
- Never say "searched Yelp" when you only saw search snippets. Say "Yelp search results show..."

## Amenity-specific research

When user specifies a specific amenity (e.g. "steam room" not "sauna"), adjust:
- Add the exact term to the search: `"steam room" Colorado Springs`
- Verify the business website explicitly mentions it — don't assume "spa" = "steam room"
- Dry sauna ≠ infrared sauna ≠ steam room — confirm the exact type

## Output format (Jim's rules)

Every business mentioned must include:
- **[Business Name](website-url)** — hyperlinked name
- 📍 **[Full Address](https://maps.google.com/?q=URL-encoded-address)** — Google Maps link
- 📞 **[(NNN) NNN-NNNN](tel:NNNNNNNNNN)** — tel: link
- ⏰ Hours
- 💰 Price / drop-in fee
- 📅 **[Add to Calendar: Event](gcal-deeplink)** — when a time/date is relevant

See `references/google-calendar-deeplink.md` for the Calendar URL template.

## Colorado Springs specific notes (USAW NCW Jun 2026)

- Jim staying at Hyatt near Ed Robson Arena (849 N Tejon St)
- VASA Fitness Union Blvd: $15 drop-in, opens 4 AM, has steam room + dry sauna + cold plunge
- SunWater Spa (Manitou Springs, 15 min): steam sauna + mineral tubs, Tue-Sun 8AM-10PM, ~$20-28
- Strata Spa at Garden of the Gods: steam room + Himalayan salt sauna, ~$75 day pass, open to non-guests
- Broadmoor Spa: restricted to overnight guests and golf club members — skip for day-pass searches
