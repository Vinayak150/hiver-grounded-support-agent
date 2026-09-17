# Brand Selection

## Dataset

**Status: Phase 1 complete.** The profiler ran on the local TWCS export with SHA-256 `cd297fcfa1bf6f99938be242e8e578980bc6d1b96adc8691abec9a39175b03c0`.

**FACT:** The CSV contains 2,811,774 rows and the columns `tweet_id`, `author_id`, `inbound`, `created_at`, `text`, `response_tweet_id`, and `in_response_to_tweet_id`. It is 516,508,641 bytes, parses as UTF-8, and has valid parsed timestamps from 2008-05-08T20:13:59+00:00 through 2017-12-03T23:14:01+00:00. The early timestamp is reported as present; this phase does not infer why it occurs.

The raw export is intentionally ignored by Git. [The manifest](../data/manifests/twcs_manifest.json) records reproducible file metadata, schema, checksums, and aggregate counts; it never contains tweet text.

## Reconstruction Quality

The profiler treats `in_response_to_tweet_id`-style parent linkage as canonical where present. It retains `response_tweet_id`-style child linkage for plural-reference parsing and consistency checks. Missing parents, malformed references, duplicates, self-references, cycles, timestamp failures, and chronological inconsistencies are measured rather than silently discarded. Thread IDs derive deterministically from the canonical component root.

**FACT:** There are 1,537,843 inbound and 1,273,931 outbound messages; 2,013,577 valid parent links; 794,335 root messages; and 3,862 orphan parent references. These reconcile exactly: `794,335 + 2,013,577 + 3,862 = 2,811,774`. The reconstruction produced 798,197 threads: 0 single-message, 435,398 two-message, and 362,799 multi-turn threads. There are 129,042 branching threads, 172,500 child references whose target is absent, and no duplicate IDs, malformed IDs/lineage references, self-references, cyclic components, timestamp parse failures, chronological inconsistencies, or inconsistent present child references.

## Candidate Discovery

Candidate accounts are discovered from measured outbound (`inbound = false`) activity across the dataset, not from a hard-coded brand list. Only accounts with at least the fixed `selection.minimum_outbound_messages` floor in `configs/profiling.yaml` are eligible. That floor is a pre-declared stability guard, not a brand-optimised parameter.

**FACT:** 101 outbound accounts met the 500-message eligibility floor. The complete machine-readable comparison is in [brand_profile.json](../results/brand_profile.json) and [brand_profile.csv](../results/brand_profile.csv).

## Metrics

The profile reports raw counts for volume, direct customer-brand links, related threads, and multi-turn threads. It also reports the following explicitly imperfect proxies:

- **Substantive-reply proxy:** outbound replies at or above the configured word-count floor.
- **Generic/redirect-reply proxy:** replies matching a configured generic, apology, redirect, or private-contact phrase, with no configured actionable phrase and no clarifying question. The question exclusion prevents apology-plus-diagnosis replies from being counted as generic merely because they lack a configured action verb.
- **Actionable-reply proxy:** replies containing a configured assistance phrase.
- **Public-containment proxy:** replies that are substantive and not generic/redirect by the above heuristic.
- **Template-collapse signals:** exact normalized duplicate rate, unique normalized reply ratio, and top-template concentration. Mentions, URLs, and whitespace are normalized, but substantive text is retained.
- **Support-surface diversity proxy:** unique normalized linked-customer-message ratio.

These do not measure genuine resolution quality, current brand policy, or production safety.

## Candidate Comparison

The generated evidence block below is updated only after profiling real data. It contains aggregate values, never raw customer text.

<!-- BEGIN GENERATED PROFILE EVIDENCE -->
## Generated profile evidence

- Source: Customer Support on Twitter (TWCS)
- Eligible outbound accounts: 101 (minimum 500 brand-authored messages)
- Reconstructed threads: 798197
- Selected brand by configured lexicographic priority: **AmazonHelp**

### Candidate comparison

| brand | brand_authored_messages | reconstructible_multi_turn_threads | public_containment_proxy_fraction | exact_normalized_duplicate_reply_rate | unique_normalized_customer_message_ratio |
|---|---|---|---|---|---|
| AmazonHelp | 169840 | 51260 | 0.77740815 | 0.09089143 | 0.96758877 |
| AppleSupport | 106860 | 28144 | 0.85613887 | 0.22387236 | 0.96246716 |
| Uber_Support | 56270 | 15088 | 0.60275458 | 0.62942954 | 0.96430738 |
| SpotifyCares | 43265 | 10500 | 0.97376632 | 0.17783428 | 0.96724214 |
| Delta | 42253 | 11147 | 0.66045015 | 0.0784323 | 0.97300681 |
| Tesco | 38573 | 11629 | 0.82158505 | 0.05457185 | 0.97371482 |
| AmericanAir | 36764 | 11577 | 0.72304428 | 0.03215102 | 0.98230128 |
| TMobileHelp | 34317 | 8627 | 0.79383396 | 0.02998514 | 0.96591202 |
| comcastcares | 33031 | 8794 | 0.7191729 | 0.27474191 | 0.96514996 |
| British_Airways | 29361 | 8830 | 0.73355812 | 0.01018358 | 0.98697659 |
| SouthwestAir | 28977 | 7231 | 0.77154295 | 0.0231563 | 0.97931408 |
| VirginTrains | 27817 | 9186 | 0.74655786 | 0.06460078 | 0.97084281 |
| Ask_Spectrum | 25860 | 6561 | 0.61392111 | 0.4491106 | 0.9756924 |
| XboxSupport | 24557 | 8396 | 0.95426966 | 0.28199699 | 0.9578206 |
| sprintcare | 22381 | 6383 | 0.6586837 | 0.13614226 | 0.97110491 |
| hulu_support | 21872 | 5897 | 0.76170446 | 0.00566935 | 0.98175599 |
| sainsburys | 19466 | 6231 | 0.87496147 | 0.06781054 | 0.97458858 |
| GWRHelp | 19364 | 6951 | 0.66546168 | 0.01833299 | 0.97984003 |
| AskPlayStation | 19098 | 5727 | 0.79935072 | 0.46104304 | 0.9527158 |
| ChipotleTweets | 18749 | 4870 | 0.59277828 | 0.19521041 | 0.97564764 |
| VerizonSupport | 17966 | 5616 | 0.89519092 | 0.21668708 | 0.93886086 |
| UPSHelp | 17817 | 5350 | 0.51551889 | 0.2468429 | 0.97724989 |
| ATVIAssist | 17650 | 5465 | 0.80107649 | 0.22203966 | 0.95597583 |
| O2 | 16212 | 4448 | 0.87663459 | 0.05014804 | 0.98729849 |
| Safaricom_Care | 16077 | 4960 | 0.70093923 | 0.13796106 | 0.93072666 |
| idea_cares | 15724 | 4891 | 0.60499873 | 0.35805139 | 0.977433 |
| AskTarget | 13218 | 3783 | 0.67188682 | 0.04448479 | 0.98407407 |
| AirAsiaSupport | 12829 | 3268 | 0.83334632 | 0.11045288 | 0.95109365 |
| BofA_Help | 12683 | 3897 | 0.84364898 | 0.25987542 | 0.97846295 |
| SW_Help | 12231 | 4253 | 0.72299894 | 0.02248385 | 0.97794843 |
| ArgosHelpers | 12174 | 4137 | 0.72966979 | 0.0382783 | 0.95253818 |
| AskLyft | 11809 | 3027 | 0.71597934 | 0.39334406 | 0.97447796 |
| marksandspencer | 11504 | 3500 | 0.75964882 | 0.04250695 | 0.98454764 |
| AskAmex | 11358 | 3385 | 0.79934848 | 0.29089628 | 0.93628961 |
| MicrosoftHelps | 11304 | 3618 | 0.93630573 | 0.09686837 | 0.98061522 |
| AskPayPal | 11298 | 3043 | 0.56160382 | 0.22455302 | 0.96775191 |
| Morrisons | 10126 | 3199 | 0.65376259 | 0.03851471 | 0.98218753 |
| AdobeCare | 9917 | 2693 | 0.91449027 | 0.23021075 | 0.98077701 |
| airtel_care | 9881 | 2129 | 0.8363526 | 0.47495193 | 0.95598958 |
| AskeBay | 9686 | 2812 | 0.86382408 | 0.00743341 | 0.98029126 |
| AirbnbHelp | 8875 | 2324 | 0.67797183 | 0.02174648 | 0.97647059 |
| ChaseSupport | 8811 | 1997 | 0.71319941 | 0.17273862 | 0.98716088 |
| McDonalds | 8478 | 1385 | 0.92321302 | 0.34512857 | 0.93963509 |
| AldiUK | 8114 | 2141 | 0.53450826 | 0.13704708 | 0.98861702 |
| JetBlue | 8020 | 2669 | 0.69613466 | 0.05386534 | 0.9801861 |
| CoxHelp | 7861 | 2275 | 0.74099987 | 0.13573337 | 0.9723859 |
| Ask_WellsFargo | 7578 | 1726 | 0.77777778 | 0.05542359 | 0.96548311 |
| AzureSupport | 7565 | 2069 | 0.93192333 | 0.23370787 | 0.92521558 |
| AlaskaAir | 7478 | 2021 | 0.66368013 | 0.05910671 | 0.98698157 |
| HPSupport | 7200 | 2358 | 0.85027778 | 0.40458333 | 0.93548387 |
| LondonMidland | 6822 | 2401 | 0.61081794 | 0.03474055 | 0.9706235 |
| GloCare | 6308 | 1838 | 0.71433101 | 0.21845276 | 0.97388756 |
| DropboxSupport | 5954 | 1710 | 0.9279476 | 0.05374538 | 0.9845514 |
| DellCares | 5336 | 1526 | 0.76874063 | 0.04722639 | 0.98013245 |
| GreggsOfficial | 4522 | 1574 | 0.3945157 | 0.11543565 | 0.98586572 |
| nationalrailenq | 4444 | 1582 | 0.84158416 | 0.05423042 | 0.9654816 |
| VirginAtlantic | 4318 | 1592 | 0.79527559 | 0.00694766 | 0.98278674 |
| TacoBellTeam | 4082 | 1171 | 0.77339539 | 0.65654091 | 0.9799274 |
| AskCiti | 4081 | 1250 | 0.87037491 | 0.10242588 | 0.98988439 |
| AskPapaJohns | 3908 | 1052 | 0.41018424 | 0.16120778 | 0.97810219 |
| CenturyLinkHelp | 3801 | 1225 | 0.72533544 | 0.34069982 | 0.98751734 |
| NikeSupport | 3468 | 986 | 0.97231834 | 0.16493656 | 0.95650061 |
| Postmates_Help | 3346 | 841 | 0.6867902 | 0.3341303 | 0.97092597 |
| VirginAmerica | 2815 | 814 | 0.60568384 | 0.04511545 | 0.98923123 |
| ATT | 2790 | 910 | 0.76164875 | 0.03870968 | 0.99441687 |
| IHGService | 2643 | 870 | 0.57434733 | 0.02837684 | 0.99188249 |
| Walmart | 2643 | 511 | 0.84373818 | 0.00416194 | 0.98946999 |
| TfL | 2243 | 761 | 0.72313865 | 0.05572893 | 0.99027073 |
| askpanera | 2153 | 550 | 0.89735253 | 0.10032513 | 0.9786739 |
| KFC_UKI_Help | 2103 | 602 | 0.61150737 | 0.52116025 | 0.98661212 |
| NortonSupport | 2011 | 480 | 0.75733466 | 0.06762805 | 0.9841998 |
| GoDaddyHelp | 1965 | 611 | 0.82391858 | 0.05445293 | 0.98939461 |
| ArbysCares | 1904 | 524 | 0.57247899 | 0.45115546 | 0.98501171 |
| AsurionCares | 1898 | 553 | 0.80084299 | 0.17123288 | 0.98510242 |
| DoorDash_Help | 1581 | 460 | 0.19544592 | 0.39089184 | 0.95951417 |
| sizehelpteam | 1482 | 482 | 0.72604588 | 0.3488529 | 0.96373057 |
| VMUcare | 1381 | 384 | 0.69007965 | 0.04706734 | 0.98029243 |
| Kimpton | 1339 | 332 | 0.93876027 | 0.0 | 0.99387755 |
| SCsupport | 1329 | 398 | 0.91422122 | 0.40933032 | 0.97156085 |
| DunkinDonuts | 1290 | 226 | 0.4496124 | 0.58682171 | 0.99865138 |
| TwitterSupport | 1290 | 430 | 0.99689922 | 0.96744186 | 0.86695279 |
| USCellularCares | 1177 | 319 | 0.92523364 | 0.0144435 | 0.97979042 |
| NeweggService | 1079 | 406 | 0.65801668 | 0.09823911 | 0.97295013 |
| PandoraSupport | 1043 | 263 | 0.77948226 | 0.18983701 | 0.98680956 |
| AWSSupport | 1035 | 416 | 0.89951691 | 0.00386473 | 0.99155146 |
| AskRBC | 1011 | 359 | 0.89910979 | 0.00197824 | 0.99064692 |
| AskVirginMoney | 914 | 259 | 0.99343545 | 0.00875274 | 0.98055271 |
| BoostCare | 907 | 247 | 0.70562293 | 0.01764057 | 0.99140401 |
| YahooCare | 906 | 339 | 0.75165563 | 0.06843267 | 0.97953737 |
| OPPOCareIN | 879 | 292 | 0.86803185 | 0.04778157 | 0.97839506 |
| PearsonSupport | 841 | 229 | 0.66706302 | 0.26397146 | 0.98796499 |
| HiltonHelp | 833 | 236 | 0.34093637 | 0.28211285 | 0.97257384 |
| GooglePlayMusic | 804 | 303 | 0.97263682 | 0.0659204 | 0.98951382 |
| MTNC_Care | 784 | 282 | 0.88010204 | 0.01020408 | 0.99176955 |
| AskTigogh | 715 | 201 | 0.82377622 | 0.05594406 | 0.96753247 |
| asksalesforce | 710 | 242 | 0.82394366 | 0.0056338 | 0.99507995 |
| askvisa | 709 | 225 | 0.77997179 | 0.02820874 | 0.99228395 |
| AskSeagate | 639 | 187 | 0.885759 | 0.02816901 | 1.0 |
| MOO | 630 | 183 | 0.64920635 | 0.04761905 | 0.99122807 |
| ask_progressive | 612 | 151 | 0.7124183 | 0.03431373 | 0.99858757 |
| KeyBank_Help | 555 | 187 | 0.84864865 | 0.0 | 0.99050633 |

All values are raw counts or explicitly named heuristics. They are not resolution rates or present-day policy claims.
<!-- END GENERATED PROFILE EVIDENCE -->

## Post-Audit Frozen Brand

**Initial Phase 1 selection: `AmazonHelp`. Final post-audit selection: `SpotifyCares`.**

Phase 1 correctly applied its predeclared lexicographic, volume-first rule. Phase
1.5 then re-evaluated the strongest measured accounts with a 10,000 multi-turn
thread saturation threshold, public-grounding proxies, deterministic ID-only
diagnostic samples, and five weighting sensitivities. SpotifyCares meets the
threshold with 10,500 multi-turn threads and has 97.3766% public containment and
2.4662% generic/redirect proxies, versus AmazonHelp's 77.7408% and 18.0847%.
SpotifyCares won every declared sensitivity configuration. The complete evidence,
including the selection's main template-collapse limitation, is in
[Phase 1.5 Brand Selection Audit](BRAND_SELECTION_AUDIT.md).

The initial selection remains below as an auditable historical record; it is not
the brand frozen for any later phase.

## Initial Phase 1 Selection (historical record)

**INTERPRETATION: select `AmazonHelp`.** The predeclared lexicographic selection order prioritizes reconstructible multi-turn threads, then public-containment proxy, normalized-reply variety, and brand-authored message volume. It selected AmazonHelp without a weighted composite or test-set information.

**FACT:** AmazonHelp has 169,840 brand-authored messages, 189,132 unique directly linked inbound messages, 269,317 linked customer-brand pairs, 82,556 brand-related threads, and 51,260 reconstructible multi-turn threads. Its outbound parent-link completeness is 99.4012% and its orphan-parent rate is 0.2732%.

**PROXY:** AmazonHelp has a median outbound length of 21 words, a 95.8019% substantive-reply proxy, a 18.0847% generic/redirect proxy, a 77.7408% public-containment proxy, a 9.0891% exact normalized duplicate-reply rate, and a 90.9109% unique normalized-reply ratio. These are not resolution or current-policy measurements.

The resulting corpus is large enough to support later thread-level splits, a 150–250-case hand-labelled evaluation set, and meaningful safety/error slices while retaining substantially non-identical public reply evidence.

## Why Not the Alternatives?

| Account | Key measured strengths | Measured trade-off relative to AmazonHelp |
| --- | --- | --- |
| AppleSupport | 106,860 outbound messages; 28,144 multi-turn threads; 85.6139% public-containment proxy; 99.8016% parent-link completeness | Higher exact duplicate rate (22.3872% vs. 9.0891%), lower reply variety (77.6128% vs. 90.9109%), and fewer multi-turn threads. |
| SpotifyCares | 97.3766% public-containment proxy; 2.4662% generic/redirect proxy; 99.8428% substantive-reply proxy | 43,265 outbound messages and 10,500 multi-turn threads—roughly one-fifth of AmazonHelp’s multi-turn corpus—and a 17.7834% duplicate-reply rate. |
| XboxSupport | 95.4270% public-containment proxy; 8,396 multi-turn threads | Much smaller multi-turn corpus; 28.1997% duplicate replies and 71.8003% unique normalized-reply ratio. |
| hulu_support | 99.4321% unique normalized-reply ratio and 0.5669% exact duplicate-reply rate | 5,897 multi-turn threads, 76.1704% public-containment proxy, and 23.8021% generic/redirect proxy. |
| Uber_Support | 56,270 outbound messages and 15,088 multi-turn threads | Strong template collapse (62.9429% exact normalized duplicates), 37.6097% generic/redirect proxy, and only 60.2755% public-containment proxy. |

These are engineering trade-offs from historical public replies, not evidence that AmazonHelp resolves more customer issues.

## Limitations

- TWCS is historical Twitter support data.
- Public support behaviour can differ from private support.
- A public reply does not prove the customer’s issue was resolved.
- Automated proxy metrics are imperfect and can reflect differing support practices.
- Large-volume accounts may use different public/private channel strategies.
- These statistics do not establish current policy or factual correctness.
- The selected account has a materially lower public-containment proxy than SpotifyCares and AppleSupport; later safety work must treat redirects, account-specific requests, and weak evidence conservatively.
- Brand selection used only data structure and heuristic proxies, not human labels, model performance, retrieval quality, or final evaluation outcomes.
