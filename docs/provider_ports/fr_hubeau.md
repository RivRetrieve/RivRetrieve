# fr_hubeau provider port

The live adapter uses `fetch.py`, `parse.py`, and `config.py`. It was contributed by Thiago von Däniken.

Daily elaborated observations use Hub Eau `obs_elab` with `date_debut_obs_elab`, `date_fin_obs_elab`, and `grandeur_hydro_elab`. Temperature uses `temperature/chronique`. Pagination follows each complete response `next` URL as a new request without appending the original parameters. Daily and temperature zones remain unknown.

Hub Eau `observations_tr` reproducibly returned HTTP 500. Instantaneous H and Q therefore use the official anonymous HydroPortail series route. H uses station `Y251002001`; Q uses its evidenced site `Y2510020`. HydroPortail publishes UTC, H in mm, Q in l/s, and raw status, quality, method, and continuity codes. The route is official but unversioned. Publisher receipts preserve all response fields byte-for-byte. The shared engine owns conversion and clipping.

The certified catalogue has six exact edges: three daily products at `1011000101`, temperature at `01001336`, and H/Q instantaneous products at `Y251002001`. Official identity responses name the producing SIE bodies as DEAL Guadeloupe - UH Guadeloupe, Agence de l'Eau Artois-Picardie, and DREAL Occitanie - UH Méditerranée O. Hub Eau and HydroPortail are recorded as transports/operators, not substituted as producers. Bounds are unknown and cross-products are absent.
