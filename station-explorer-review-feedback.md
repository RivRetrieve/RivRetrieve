# Station explorer prototype: review feedback

Branch `feat/station-request-builder-prototype` at `8bb6524`, reviewed 2026-10-10
with the docs preview, the full catalogue and a CARTO key. I downloaded gauges using 
the code! so far it worked perfectly.

## Works as documented

- Build, 21 of 21 Playwright tests, CARTO light and dark tiles, and the theme toggle.
- Opening view is Switzerland on a fresh load, at every width tried.
- Single-provider and multi-provider code, including overlapping station IDs (6,710 IDs
  occur in more than one provider) and leading zeros (`01646500`).
- Copy is blocked, with the reason shown, for a filter conflict, an empty selection,
  start date after end date, and a catalogue-only provider.

## Generated code follows the live filters

`rr.find(...)` is built from the filters active when you copy; `rr.pick` comes from
the selected gauges. The same 246 `ch_foen` gauges give `rr.find(provider="ch_foen",
quantity="discharge")` with the filter on and `rr.find()` with it cleared. The second
requests every quantity listed for those stations (three for `ch_foen`). Neither the
Selection cards nor the Python tab says this.

## Small points

1. Blocked previews mix live filters with the stored selection. Example: add all 246
   `ch_foen` gauges, then change the provider filter to `cz_chmi`. Copy is blocked and
   the commented preview reads:

   ```python
   # selection = rr.find(provider="cz_chmi")
   # gauges = rr.pick(
   #     selection,
   #     provider="ch_foen",
   #     station=["2004", ...],
   # )
   ```

   `rr.find` comes from the current filter and `rr.pick` from the stored selection, so
   the preview describes a request nobody made. With an empty selection the preview
   still shows `rr.find(provider="cz_chmi")` from the leftover filter.

2. When the selection equals the whole result (246 of 246), `rr.pick` repeats all IDs
   and narrows nothing. Could we optimize it?

3. Date errors (e.g., end date before start date)appear only in the Python tab, not beside 
   the date inputs.

4. The start date and end date refer to the download process, and not to the filters, correct?
   I think in the current form it might be a but confusing? Coudl we think about a solution?

5. lowercase and uppercase field labels: End date with "E," but all other columns lowercase. 

6. raw provider IDs in the dropdown: could/should we humanize the namings? Like keeping the code, but
   adding the country spelled our? Or even the agencies names?

7. At 390 px the panel covers about half the map and Add all matches is below the fold (Claude analysis, not mine).


## Smaller points

Very small details that we could discuss (very pedantic and optional):
8. Wording: "1 matching gauges" instead of "gauge"; 

9. The credential comment names variables but not how to set them. 