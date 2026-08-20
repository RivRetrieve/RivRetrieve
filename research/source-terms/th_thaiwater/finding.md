# Source terms finding — th_thaiwater

Agency: ThaiWater / Hydro-Informatics Institute HII
Country: Thailand
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

**NOT FOUND on the agency's own domain.** The likeliest statement is on a third party, which
is itself a finding worth recording.

| URL | Title | Lang | Note |
|---|---|---|---|
| https://data.go.th/dataset/set-of-water-level-by-station | — | th | **THIRD PARTY.** Thailand's national open-data portal, organisation `hii`. Portal dataset pages carry a licence field, so this may be the only place a licence is stated. Returned 403 to the lead-finder |
| https://data.go.th/en/dataset?organization=hii | — | en/th | Same portal, HII's dataset listing. Also 403 |
| https://www.thaiwater.net/ | คลังข้อมูลน้ำแห่งชาติ — National Hydroinformatics Data Center | th | **JS-only.** The served HTML has zero footer links; a terms link may appear only once the app boots. **Needs a real browser** |
| https://www.hii.or.th/privacy-policy/ | นโยบายความเป็นส่วนตัว | th | A privacy policy, **not** a data licence. Listed only so it is not mistaken for the terms |
| https://api-v3.thaiwater.net | — | — | API host referenced by the site; not probed |

Already searched and empty: thaiwater.net raw links, hii.or.th homepage links filtered for
policy/terms/licence, hii.or.th/en/faq, standard.thaiwater.net, tiwrm.hii.or.th, and Thai
searches for นโยบายการใช้งาน / ข้อตกลงการใช้บริการ / เงื่อนไขการให้บริการ.
`api.thaiwater.net` and `data.hii.or.th` time out entirely.

If the licence turns out to live only on `data.go.th`, record it there **and say clearly in
Notes that it is a third-party portal, not HII's own statement.**

## licence

- Page URL: https://standard.thaiwater.net/
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T16:12:19+00:00
- Language: th
- Agency publishes nothing: yes

No statement of terms of use or licence was found. The recordings are kept as evidence of
absence. The one rights assertion that does exist is quoted in Notes, where it cannot be
mistaken for terms.

```text
```

## citation

- Page URL: https://standard.thaiwater.net/
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T16:12:19+00:00
- Language: th
- Agency publishes nothing: yes

```text
```

## Notes

**No licence was found, and no citation request.** Both slots are therefore
`Agency publishes nothing: yes` under BRIEF § 4, with the pages recorded as evidence of absence
rather than a bare claim. `licence-1` is named in both as the page that would carry such a
statement if one existed.

The only statement about rights anywhere on HII's web presence is a footer copyright line,
identical on every host:

```text
Copyright © 2024 Hydro-Informatics Institute of Ministry of Higher Education, Science, Research and Innovation in Thailand, All rights reserved.
```

It is quoted here, not in a slot, because **it is a copyright assertion and not a licence**: it
grants nothing, permits nothing, and asks for no particular credit. Putting it in a field
labelled *licence* would invite the next reader to treat it as the terms, which is the reading
the brief forbids. This follows the same call made for `ba_fhmzbih`.

### What we actually fetch, and what it contains

`th_thaiwater` reads two hosts:

```
https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load
https://standard.thaiwater.net/docs/…/การระบุพิกัดตำแหน่ง/
```

The candidate table listed `api-v3.thaiwater.net` as **"not probed"**. It has now been probed.
It returns **2,061,814 characters** of JSON across seven blocks — `waterlevel_data`,
`waterlevel_manual_data`, `basin`, `agency`, `station`, `scale`, `province`. It was scanned for
thirteen terms in English and Thai:

`licen`, `Licen`, `LICEN`, `copyright`, `Copyright`, `terms`, `Terms`, `attribution`, `credit`,
`สัญญาอนุญาต`, `ลิขสิทธิ์`, `เงื่อนไข`, `ข้อตกลง`

**Every one returned zero matches.** The bytes RivRetrieve consumes carry no statement of terms,
no copyright notice and no attribution field. The payload was not recorded: it is 2.4 MB of live
water levels that changes every ten minutes, so a snapshot would be bulk rather than evidence.
The URL above is public and unauthenticated, so the scan can be repeated by anyone.

`standard.thaiwater.net` is recorded as `licence-1`. Its only rights statement is the footer
line quoted above. Two occurrences of `เงื่อนไข` ("conditions") appear in its source; both are
**JavaScript comments about table-sorting logic**, not terms. Checked rather than counted.

### Where else was looked

| Where | Result |
|---|---|
| `www.hii.or.th` (`licence-2`) | Same footer copyright line, identical wording. No terms page. Its only policy-shaped link is *นโยบายและยุทธศาสตร์* — institutional policy and strategy, not data terms |
| `www.hii.or.th/privacy-policy/` (`licence-3`) | A privacy policy. **Not** a data licence. Recorded so it is not mistaken for one, as the candidate table warned |
| `www.thaiwater.net` (`licence-4`) | **JS-only, confirmed.** The served bytes contain 77 characters of visible text — the page title alone. The in-app browser could not load the site at all, so the rendered DOM could not be inspected |
| `data.go.th` | **Blocked, not merely 403 to a script.** A real browser receives an *"Access Denied — Your request has been blocked by our security systems"* interstitial with a Ray ID, on 2026-08-20. `record.py` gets HTTP 403. Nothing could be recorded |

The `data.go.th` page was not saved: what the browser receives is a 2.6 MB block interstitial,
not the dataset page, so committing it would preserve the blocker rather than the source.

**This matters for the strength of the finding.** HII's own domains are fully reachable and
carry nothing, so "HII publishes no terms" is established. The Thai national open-data portal
could not be reached from here, so **whether a licence field exists on `data.go.th` is not
established either way** — the candidate table's suspicion that it may be the only place a
licence is stated remains untested. A reader in Thailand, or on a different network, may see
something we cannot.

### Enquiry sent 2026-08-20

Nothing was found, so HII was asked directly.

| | |
|---|---|
| Sent | **2026-08-20** |
| To | `contact@hii.or.th`, the general enquiry address on `hii.or.th` |
| By | Thiago Nascimento, Eawag |
| Language | English |

The two questions asked, verbatim:

```text
1. Are there published terms of use or a licence for the reuse of data from
   the ThaiWater public API?

2. How would you like HII to be credited as the source? We would like the exact
   wording you prefer.
```

The enquiry asked only what the Institute publishes. It did not ask permission, and none is
implied by it having been sent.

**No reply as of the date of this recording.** A reply belongs here quoted verbatim with its
date. If none comes, "asked on 2026-08-20, no reply" is the result, and it distinguishes having
asked from nobody having asked.

The registry address `saraban@hii.or.th` also appears on `hii.or.th` and is the formal
correspondence inbox, if a follow-up is needed.

### Access notes

- Four pages recorded with `record.py`. `standard.thaiwater.net` and `hii.or.th` need no key,
  no login and no JavaScript for the footer.
- The candidate table reported `api.thaiwater.net` and `data.hii.or.th` time out entirely; not
  retested, since neither is an endpoint the provider uses.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
