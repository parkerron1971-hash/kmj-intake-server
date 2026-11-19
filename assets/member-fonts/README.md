# Member app fonts (Lumen Next)

The type of the member app's new look (`member_lumen_fonts.py`). Kevin picked
pairing A on 2026-11-19 and asked that each church can choose from the three
on the Lumen Next type board:

| Pairing | Headings + italic word | Everything you tap | Bible reading | Amounts |
|---|---|---|---|---|
| A · Literata + Figtree (default) | Literata | Figtree | Literata | Literata, tabular |
| B · Fraunces + Onest | Fraunces (soft) | Onest | Literata | Onest, tabular |
| C · Mona Sans | Mona Sans (wide) | Mona Sans | Source Serif 4 | Mona Sans, regular figures |

Every file is a variable font, unmodified, exactly as Google Fonts serves it
(fonts.gstatic.com, fetched 2026-11-19 through the css2 API with a current
Chrome user agent): the `latin` and `latin-ext` subsets of each style. Each
family is licensed under the SIL Open Font License 1.1; its licence, with
its copyright line, is the `OFL-<family>.txt` beside it. Mona Sans reserves
the font name "Mona", so these files are never changed: to update one,
fetch it again from Google Fonts.

| File | Source |
|---|---|
| literata-normal-latin.woff2 | https://fonts.gstatic.com/s/literata/v40/or3hQ6P12-iJxAIgLYTwJrU.woff2 |
| literata-normal-latin-ext.woff2 | https://fonts.gstatic.com/s/literata/v40/or3hQ6P12-iJxAIgLYT-JrUFng.woff2 |
| literata-italic-latin.woff2 | https://fonts.gstatic.com/s/literata/v40/or3nQ6P12-iJxAIgLYT1Frcdmg.woff2 |
| literata-italic-latin-ext.woff2 | https://fonts.gstatic.com/s/literata/v40/or3nQ6P12-iJxAIgLYT1FrkdmgPn.woff2 |
| figtree-normal-latin.woff2 | https://fonts.gstatic.com/s/figtree/v9/_Xms-HUzqDCFdgfMm4S9DQ.woff2 |
| figtree-normal-latin-ext.woff2 | https://fonts.gstatic.com/s/figtree/v9/_Xms-HUzqDCFdgfMm4q9DbZs.woff2 |
| fraunces-normal-latin.woff2 | https://fonts.gstatic.com/s/fraunces/v38/6NUV8FyLNQOQZAnv9ZwIlOk.woff2 |
| fraunces-normal-latin-ext.woff2 | https://fonts.gstatic.com/s/fraunces/v38/6NUV8FyLNQOQZAnv9ZwGlOk8yA.woff2 |
| fraunces-italic-latin.woff2 | https://fonts.gstatic.com/s/fraunces/v38/6NUT8FyLNQOQZAnv9ZwNpOskzA.woff2 |
| fraunces-italic-latin-ext.woff2 | https://fonts.gstatic.com/s/fraunces/v38/6NUT8FyLNQOQZAnv9ZwNpOUkzO1A.woff2 |
| onest-normal-latin.woff2 | https://fonts.gstatic.com/s/onest/v11/gNMKW3F-SZuj7xmf-HY.woff2 |
| onest-normal-latin-ext.woff2 | https://fonts.gstatic.com/s/onest/v11/gNMKW3F-SZuj7xmR-HY6EQ.woff2 |
| mona-sans-normal-latin.woff2 | https://fonts.gstatic.com/s/monasans/v4/o-0IIpQmx24alC5A4PNr5TRA.woff2 |
| mona-sans-normal-latin-ext.woff2 | https://fonts.gstatic.com/s/monasans/v4/o-0IIpQmx24alC5A4PNr6zRAW_0.woff2 |
| mona-sans-italic-latin.woff2 | https://fonts.gstatic.com/s/monasans/v4/o-0OIpQmx24alC5A4PNr4ARCQ_k.woff2 |
| mona-sans-italic-latin-ext.woff2 | https://fonts.gstatic.com/s/monasans/v4/o-0OIpQmx24alC5A4PNr4ARMQ_m87A.woff2 |
| source-serif-4-normal-latin.woff2 | https://fonts.gstatic.com/s/sourceserif4/v15/vEFI2_tTDB4M7-auWDN0ahZJW1gb8tc.woff2 |
| source-serif-4-normal-latin-ext.woff2 | https://fonts.gstatic.com/s/sourceserif4/v15/vEFI2_tTDB4M7-auWDN0ahZJW1gV8tenXg.woff2 |
| source-serif-4-italic-latin.woff2 | https://fonts.gstatic.com/s/sourceserif4/v15/vEFK2_tTDB4M7-auWDN0ahZJW1gewtW_Wg.woff2 |
| source-serif-4-italic-latin-ext.woff2 | https://fonts.gstatic.com/s/sourceserif4/v15/vEFK2_tTDB4M7-auWDN0ahZJW1gewtu_Wo7H.woff2 |

The fallback metrics in `member_lumen_fonts.FALLBACKS` (so text doesn't jump
when the real face arrives) were measured from each family's default
instance against Georgia (the serifs) and Arial (the sans faces): size-adjust
is the ratio of average letter widths weighted by English letter frequency,
and each vertical metric is the face's hhea value divided by it, the way
next/font works them out.
