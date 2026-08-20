# Source terms finding — fr_hubeau

Agency: Hubeau / SCHAPI
Country: France
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Page title | Lang | Why a candidate |
|---|---|---|---|
| https://hubeau.eaufrance.fr/page/conditions-generales | Conditions générales d'utilisation | fr | Hubeau's own CGU page, footer-linked from every API page; §5.1.3 covers reuse/attribution |
| https://hubeau.eaufrance.fr/mentions-legales-credits | Mentions Légales / Crédits | fr | Companion legal page — the crediting side |

Plain HTML, no login, no key. Note `https://hubeau.eaufrance.fr/page/mentions-legales` is a
404 — the real path has no `/page/` prefix.

## licence

- Page URL: https://hubeau.eaufrance.fr/page/conditions-generales
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T15:39:10+00:00
- Language: fr
- Agency publishes nothing: no

```text
La réutilisation des Jeux de données est régie par la licence ouverte Etalab, https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement et gratuitement utilisables et réutilisables, y compris dans un but commercial.
```

## citation

- Page URL: https://hubeau.eaufrance.fr/page/conditions-generales
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T15:39:10+00:00
- Language: fr
- Agency publishes nothing: no

```text
L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données.
```

## Notes

Both slots come from **§ 5.1.3 *Jeux de données diffusés par les API offertes par la
Plateforme*** of Hub'Eau's *Conditions générales d'utilisation*. The licence sentence and the
attribution sentence are consecutive in that section.

### The citation ask does not name Hub'Eau

Read it closely: the user must *citer l'auteur des Jeux de données* — **the author of the
datasets**, not Hub'Eau and not the OFB. The same section explains why, and this is recorded
because it is the reason no single credit line can be lifted from the page:

```text
Les Jeux de données contiennent des données brutes, c'est-à-dire fournies sans retraitement ni mise en perspective particulière, telles que produites par les acteurs du SIE, et telles que rendues publiques sur les sites de la toile eaufrance, https://www.eaufrance.fr. Les contributeurs de ces sites sont seuls responsables des données.
```

So Hub'Eau positions itself as the distributor and points attribution at the producing SIE
actors, while naming none of them for hydrometry. **There is no formatted citation string
anywhere on the platform.** Which producer should be credited for the hydrometric datasets
RivRetrieve reads is not answered by this page, and is not answered here.

Checked and empty: the *Mentions Légales / Crédits* page (`licence-2`) is not a second citation
source. Its *Crédits* section covers graphic design, technical development, hosting and photo
credits — BRGM and Cat-Amania — and its *Editeur* block names the Office français de la
biodiversité as site publisher. None of that is an instruction about crediting data.

### What we actually fetch

All five of the provider's endpoints are on the agency's own host, `hubeau.eaufrance.fr` —
`api/v2/hydrometrie/referentiel/sites`, `.../stations`, and `api/v1/temperature/station`. There
is **no intermediary**, unlike `ch_foen` and `ba_fhmzbih`.

The API responses carry no licence field. A station request returns `count`, `first`, `last`,
`prev`, `next`, `api_version` and `data` — nothing about terms. So, as with `ca_eccc`, the
licence is not machine-discoverable from the service.

### Third-party flag

The licence is **named** on Hub'Eau's own domain, but its text is not: § 5.1.3 points to
`https://www.etalab.gouv.fr/licence-ouverte-open-licence`. That is a French government domain
but not Hub'Eau's, so it is recorded separately as `licence-3` rather than treated as the
agency's own words. The brief asks that third-party statements be identified as such.

### Other statements in the same document, not quoted above

§ 5.1.3 also sets out the statutory framework — Titre Ier and Titre II du Livre III du CRPA,
article L300-4, article 1er de la loi Pour une République Numérique, and articles L124 and R124
du Code de l'environnement. § 5.1.4 *Contenus informationnelles* places the Éditeur's content
under the Licence Ouverte with the exception of logos and iconographic material. All present in
the recording, none summarised here.

### Access notes

- The folder's warning is **confirmed**: `https://hubeau.eaufrance.fr/page/mentions-legales`
  returns 404. The real path has no `/page/` prefix and is
  `https://hubeau.eaufrance.fr/mentions-legales-credits`.
- All three pages recorded with `record.py` in one pass. Plain HTML, no login, no API key, no
  JavaScript — the easiest provider in the survey so far.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
