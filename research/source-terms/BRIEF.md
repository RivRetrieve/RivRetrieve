# Research brief: what each agency says about its own data

**This file is self-contained.** You can paste it whole into an AI assistant. It assumes
no knowledge of RivRetrieve and you do not need to read any other file in this repository.

You are not writing code. You will not open a Python file. You fill in forms and save web
pages.

---

## 1. Why this exists

RivRetrieve is a Python library that downloads river gauge data — water level and flow —
from thirteen national agencies around the world, and hands it to researchers in one
consistent shape. It ships a packaged catalogue of about 64,000 gauging stations.

Two things are missing, and both are about honesty rather than about features.

**We do not know what any of the thirteen agencies asks of us.** Every result the library
returns currently carries a small note saying, in effect, "RivRetrieve has not established
the terms or the citation for this source." That note is true for all thirteen. We want to
replace it with the agency's own words.

**We publish about 2,300 station coordinates we cannot account for.** Japan's and Poland's
coordinates were inherited from older code with no record of where they came from. Until
someone can say where they came from, we should not be shipping them.

Your work closes both.

---

## 2. The one rule that matters

> **Write down what the agency says. Never write down what it means.**

You are not deciding whether we may republish anything. Nobody is asking you to. That
judgement belongs to whoever reads the terms later, and this project has a standing
decision never to publish its own reading of a licence.

So:

| Do | Do not |
|---|---|
| Copy the agency's sentence, character for character, in its original language | Translate it, paraphrase it, or tidy it up |
| Record "the agency publishes nothing about this" when that is what you found | Guess, or write "probably open data" |
| Say "I could not find it" and list where you looked | Supply a plausible-looking address to fill the box |

**If you use an AI assistant, this is where it will fail you.** Asked "what is the licence
for Polish hydrological data?", a model will produce a confident, well-formed, plausible
URL and a confident, well-formed, plausible quotation — and both may be invented. This is
not a hypothetical; it is the single most likely way this task goes wrong.

That is why every quote must come out of a page you actually saved. The checker verifies,
by machine, that the sentence you wrote appears in the bytes of the page you recorded. A
quote that is not on the page is caught immediately. Use the AI to *find candidate pages*
and to *read languages you do not speak*. Never let it supply the quote.

---

## 3. What you do, per agency

There are thirteen. Each has a folder here named after it. Work one at a time.

### Step 1 — find the page

Find where the agency states its **terms of use / licence** for the data. Then find where
it states **how it wants to be cited**. These are often two different pages, and sometimes
one page covers both.

Each folder's `finding.md` already lists **candidate addresses** to start from. They are
marked UNVERIFIED and were found by an AI, so treat them as leads, not answers. Some will
be wrong.

Prefer the agency's own website over anyone describing it. If the only statement you can
find lives on a third-party site, record it and say so in Notes.

### Step 2 — save the page

```
python research/source-terms/record.py <provider_id> licence  <url>
python research/source-terms/record.py <provider_id> citation <url>
```

For example:

```
python research/source-terms/record.py pl_imgw licence https://danepubliczne.imgw.pl/pl/datastore
```

It saves the page's exact bytes, its address, the moment you fetched it, and a
fingerprint. It prints the filename to put in the form. It never overwrites: run it twice
and you get two dated captures.

If the page needs a browser, a login, or defeats the tool for any reason, save it by hand
with your browser's **Save As → Web Page, HTML only** into that provider's `pages/`
folder, and write what happened in Notes.

### Step 3 — fill in the form

Open the folder's `finding.md` and complete it. The verbatim quote goes inside the
` ```text ` block, copied out of the page — ideally by selecting the text in your browser
and pressing copy, not by retyping.

Keep the quote tight: the sentence or two that actually states the terms. Not the whole
page, not one word.

### Step 4 — check your own work

```
python research/source-terms/check.py pl_imgw
```

It tells you exactly what is still missing. When it prints `ok`, you are done with that
agency. You do not need to ask anyone.

### Step 5 — open a pull request

**One pull request per agency.** Thirteen small reviews, so a problem in Lithuania does
not hold up Canada.

---

## 4. When the agency says nothing

This is a real and useful finding, not a failure. Plenty of agencies publish data with no
terms page at all.

Record it: set `Agency publishes nothing: yes` in that slot, and **still save a page** —
the data portal's front page, or its footer, or its "about" page — showing there is no
statement there. Then say in Notes where you looked.

The reason we insist on a saved page even for a negative finding: "we looked and found
nothing" and "nobody looked" are different claims about the world, and only one of them is
worth anything in two years.

---

## 5. The two special jobs

Two agencies need detective work rather than reading. Their folders contain a `TRAIL.md`
with everything already established and a draft message.

### Japan (`jp_mlit`)

We ship 1,023 Japanese station coordinates. They were not gathered by this project. The
trail runs back through an AI translation, into the original R package this library
descends from, and stops at a commit dated **21 March 2023 by Ryan Riggs** titled "japan
gauges added". No script, no note.

Two routes: the published paper behind that R package may document it, and Ryan Riggs is a
named, contactable researcher. Read `TRAIL.md`, then send the message.

**What we need is narrow: where did those coordinates come from, and roughly when were
they obtained.** Not permission, not an opinion, not a favour.

### Poland (`pl_imgw`)

We ship 1,301 Polish station coordinates. The trail is shorter and colder. The file
originally had no coordinates at all; they were added on **29 November 2025 by Frederik
Kratzert** in a change whose entire description reads "Update station catalog with more
information."

Same narrow question, same shape. `TRAIL.md` has the details.

If both come back empty, that is an answer too, and we act on it.

---

## 6. What happens to your work

Each finding becomes the licence and citation a user sees on every result they download
from that agency — in the agency's own words, with the page you saved standing behind it,
so anyone can check the quote and see when it was true.

And the two trails decide whether about 2,300 stations keep their coordinates.

---

## 7. The thirteen

| Folder | Agency | Country |
|---|---|---|
| `ba_fhmzbih` | Federal Hydrometeorological Institute FHMZBiH | Bosnia and Herzegovina |
| `br_ana` | ANA Hidroweb, National Water and Sanitation Agency | Brazil |
| `ca_eccc` | Environment and Climate Change Canada | Canada |
| `ch_foen` | Federal Office for the Environment FOEN/BAFU | Switzerland |
| `cz_chmi` | Czech Hydrometeorological Institute CHMI | Czechia |
| `fr_hubeau` | Hubeau / SCHAPI | France |
| `jp_mlit` | MLIT Water Information System — **also see `TRAIL.md`** | Japan |
| `lt_lhmt` | Hydrometeorological Service LHMT | Lithuania |
| `no_nve` | NVE HydAPI | Norway |
| `pl_imgw` | IMGW — **also see `TRAIL.md`** | Poland |
| `th_thaiwater` | ThaiWater / Hydro-Informatics Institute HII | Thailand |
| `usgs_nwis` | U.S. Geological Survey NWIS | United States |
| `za_dws` | Department of Water and Sanitation DWS | South Africa |

Questions that are not answered here are questions to ask, not to guess at.
