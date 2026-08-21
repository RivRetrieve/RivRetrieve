# Source terms finding — jp_mlit

Agency: MLIT Water Information System
Country: Japan
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Page title | Lang | Why a candidate |
|---|---|---|---|
| http://www1.river.go.jp/caution.html | 利用規約等 | ja | The site's own "terms etc." page — a link hub, not the terms document itself |
| http://www1.river.go.jp/WDBrules_20251210.pdf | ウェブDB利用規約, dated 2025-12-10 | ja | **Current** terms PDF, linked from caution.html; contains an explicit 出典の記載 (source-citation) clause |
| http://www1.river.go.jp/WDBrules_20240125.pdf | same document, earlier version | ja | Still live and what search engines surface — **record the 2025 one, not this** |

**Read this before you start on Japan.**

- `www1.river.go.jp` **blocks non-browser clients**: plain fetches get 403 with "This site
  prohibits data acquisition using tools, etc." `record.py` will fail. Save these pages by
  hand from your browser (**Save As → Web Page, HTML only**) into `pages/`, and write a JSON
  sidecar by hand with the url, the UTC instant and the sha256 — or ask for help; do not skip it.
- The site is **frameset-based** and served in **EUC-JP**, so titles look garbled in
  UTF-8 tools. That is an encoding artefact, not a wrong page.
- The current terms document is a **PDF**. The checker cannot machine-verify a quote inside a
  PDF, so it will tell you to explain that in Notes. Quote it accurately anyway.

## licence

- Page URL: http://www1.river.go.jp/caution.html
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T09:46:54+00:00
- Language: ja
- Agency publishes nothing: no

```text
水文水質データベースをご利用いただく際、掲載しているデータの利用について、許可等は必要ありません。 「公共データ利用規約（第1.0版）」に従い、データをご利用ください。
```

## citation

- Page URL: http://www1.river.go.jp/WDBrules_20251210.pdf
- Recording: citation-1
- Retrieved (UTC): 2026-08-21T09:47:00+00:00
- Language: ja
- Agency publishes nothing: no

```text
出典： 国土交通省 水文水質データベース （https://www1.river.go.jp/）（○年○月○日に参 照）、PDL1.0（http://www1.river.go.jp/）
```

## Notes

> **`check.py` reports a problem on both slots for this provider. Both are limitations of the
> checker, not defects in the finding, and both are set out below with the evidence to verify
> them by hand.** This is the one provider in the survey that cannot reach `ok`.

### Why the licence slot cannot be machine-verified

`check.py`'s `page_text()` decodes every recording with `body.decode("utf-8", errors="replace")`.
`caution.html` is served as **EUC-JP** and says so in its own bytes (`charset=EUC-JP`). Decoded
as UTF-8 the Japanese becomes replacement characters, so no Japanese quote can ever match, and
the checker reports `THE QUOTE IS NOT ON THE RECORDED PAGE`.

**The quote is on the recorded page.** Demonstrated with the checker's own parser and
normaliser, changing only the codec:

| Decoding | `normalise(quote) in page_text` |
|---|---|
| `utf-8` — what `check.py` does | **False** |
| `euc_jp` — what the page declares | **True** |

Anyone can reproduce that against `pages/licence-1.html`. The failure is in the decoding step,
not in the quote.

### Why the citation slot cannot be machine-verified

The citation wording exists only in the terms PDF. `check.py` refuses to check a quote inside a
non-HTML recording and says so. The quote was extracted with `pypdf`, not retyped; the PDF's
text layer inserts spacing inside runs of characters, so whitespace was collapsed. Nothing else
was changed.

### The folder's two warnings, both wrong on test

- **"`www1.river.go.jp` blocks non-browser clients; plain fetches get 403; `record.py` will
  fail."** It did not. Both `caution.html` and the terms PDF returned **HTTP 200** to
  `record.py`'s own User-Agent, and again to a browser User-Agent, on 2026-08-21. A data
  endpoint (`SiteInfoDetail.exe`) also returned 200. **No hand-saving was needed** and both
  recordings are ordinary `record.py` captures with real sidecars.
- **"`caution.html` is a link hub, not the terms document itself."** It is not a hub. It carries
  the licence statement quoted above, the disclaimer, the map attribution and the request about
  automated collection below. Its only links are the terms PDF and `river.go.jp`.

### MLIT asks people not to do what RivRetrieve does

On the same page, under システム利用における注意事項:

```text
当ホームページは一般を対象としており、通常のブラウザで閲覧することを前提に情報を掲載しております。ツール等による、自動的なデータ収集等はサーバに負荷がかかり、情報提供できなくなる恐れがありますので原則としてご遠慮ください。ご理解・ご協力お願いします。
```

In substance: the site is intended for the general public and published on the assumption of
viewing with an ordinary browser; automatic data collection by tools places load on the server
and risks making the service unavailable, so please refrain from it as a rule.

`provider.json` records this provider's method as *"HTML scrape + Shift-JIS .dat download"*.

This is recorded because it is what the agency says, and it is the most direct statement in the
whole survey about the manner of access rather than the terms of reuse. **It is a request, not
a prohibition, and it is not a licence condition** — it sits in a different section from the
terms. What to do about it is not decided here.

### What the licence actually is

`caution.html` states no permission is required and points at 「公共データ利用規約（第1.0版）」,
the **Public Data License 1.0 (PDL1.0)**, whose text is the recorded PDF. From that document:

```text
当ウェブサイトで公開している情報（以下「コンテンツ」といいます。）は、別の利用ルールが適用される コンテンツを除き、どなたでも以下の１）～７）に 定める利用ルール（以下「本利用ルール」 といいます。） に従って、複製、公衆送信、翻訳・変形等の翻案等、自由に 利用できます（本利用ルールに従って利用 できるコンテンツを、以下「本コンテンツ」といいます。） 。商用利用も可能です。
```

— free reproduction, public transmission, translation and adaptation, and commercial use is
also possible.

```text
本 利 用 ル ー ル は 、 ク リ エ イ テ ィ ブ ・ コ モ ン ズ ・ ラ イ セ ン ス の 表 示4.0 国際 ラ イ セ ン ス （https://creativecommons.org/licenses/by/4.0/legalcode.ja に規定される著作権利用許諾条件。 以下「CC BY」といいます。）と互換性があります。
```

— PDL1.0 is stated to be compatible with **CC BY 4.0**.

The PDF also gives a second citation form for edited or processed data
(*「…を加工して作成」*) and notes that the access date must be given because the database is
updated after accuracy checks. Both are in the recording.

### Map attribution, relevant to the coordinates

`caution.html` carries a separate attribution for the base maps, approved by the
Geospatial Information Authority of Japan (国土地理院), approval number 平１５総使第６５３号.
Recorded because `jp_mlit` ships station coordinates; per `TRAIL.md` those come from MLIT's own
`世界測地系` field and not from the maps, so this attribution is noted rather than applied.

### The older terms PDF

`WDBrules_20240125.pdf` is still live and is what search engines surface. The candidate table
said to record the 2025 one, and that is what `citation-1` is: `WDBrules_20251210.pdf`, dated
2025-12-10. The rules text itself states it was set on 令和６年７月５日 (5 July 2024).

### Not part of this folder's work

`TRAIL.md` records the Japanese coordinate provenance as **RESOLVED** — rebuilt from MLIT's own
per-station register with a full manifest — and says not to re-open it. It was not re-opened.
Note that the job email that commissioned this survey asks for the Japan coordinate trail to be
chased; `TRAIL.md` supersedes that.

### The shipped catalogue

`provider.json` carries `"license": null` and `"citation": null`.
