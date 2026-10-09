# CSC Day 2 — Loop design worksheet

Oct 9, 2026 · @Fan Wu

## Where we are

The loop starts with design, not code. Tracing is in place, but classify still answers once per item and the belt moves on; no loop exists yet. The design steps don't need to wait for the first grouped 7am run in LangSmith.

1. Look at real evidence: is classify ever uncertain? (10 minutes)
2. Draw your own 8 boxes
3. Review: Claude pushes back, then we compare with the reference design in the loop spec and save the agreed version to the project
4. The two small fixes the loop sits on
5. Claude Code builds it

## Step 1: is there anything for a loop to fix?

Loops are for uncertainty, not bugs, so first check that classify is actually unsure sometimes. Open 5 classify rows in LangSmith (output starting `{"domain": ...`), mixing ASIC, Australian Broker and Google News items. If all 5 look right and well grounded, that tells us where a loop isn't needed.

| # | Source | Decision (domain, signal type) | Said how sure? | Pointed to evidence? | Input thin or full? | Would you agree? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | <https://kalkinemedia.com/education/guides/what-auto-financing-for-no-credit-reveals-about-the-changing-consumer-credit-market> | The article's title suggests a focus on auto financing for consumers with no credit, indicating a potential trend in the Australian consumer credit market that is highly relevant to an AU car and consumer finance business. | 0.4 | What Auto Financing for No Credit Reveals About the Changing Consumer Credit Market | The actual content of the article is not provided, so the classification is based solely on the title and keywords, leading to lower scores for impact, urgency, and novelty, and reduced confidence. | unsure to agree as the content is not pulled over |
| 2 | ASIC Media | ASIC has issued an interim stop order on mortgage schemes due to defective disclosure, indicating a heightened regulatory focus on private credit and investor protection that could influence broader financial services disclosures." | 0.9 | ASIC has made an interim stop order on the product disclosure statement (PDS) issued by Australian Secure Capital Fund Limited (ASCF) offering units in three registered managed investment schemes. The interim stop order stops ASCF from offering, issuing, selling or transferring interests in the ASCF Premium Capital Fund, ASCF Select Income Fund, and ASCF High Yield Fund (the Funds). | full body input from the article | agree |
| 3 | ASIC Media (regulator) | ASIC has initiated civil penalty proceedings against a former financial adviser for allegedly circumventing conflicted remuneration laws and failing best interest duties, which highlights ongoing regulatory scrutiny and enforcement in the financial advice sector | 0.9 | ASIC has commenced civil penalty proceedings against former financial adviser Osama Saad, alleging he carried out schemes to avoid conflicted remuneration laws and contravened his best interest obligations when providing financial advice to hundreds of clients to invest their superannuation into the First Guardian Master Fund (First Guardian), which later collapsed." | full body input from the article | agree |
| 4 | ASIC Media (regulator) | This news details a conviction and sentencing for insider trading by a former CEO, demonstrating ASIC's continued enforcement of corporate regulations. | 0.9 | Richard Evans... has today been convicted and sentenced in the District Court of New South Wales for communicating inside information to another person | full body input from the article | dont agree |
| 5 | Australian Broker (news) | CommBank's advanced AI capabilities and investment in engineer training present a competitor move, indicating a potential competitive advantage in fraud detection and customer innovation.", | 0.9\
 | Commonwealth Bank of Australia (CBA) has been named the top bank in Asia-Pacific and fourth worldwide for artificial intelligence (AI) maturity in the 2026 Evident AI Index. Days earlier, CBA confirmed that its engineers will join Anthropic’s Claude Frontier Academy. | full body input from the article | disagree |

- **Said how sure?** Is there a confidence number in the output?
- **Pointed to evidence?** A quote from the article, or just a verdict?
- **Input thin or full?** A full article, or a one-line snippet?

## Step 2: your 8 boxes

Answer in your own words, one or two rough lines each, without looking at the reference design in the loop spec. If you've seen it before, answer from your own judgement anyway, and where you agree with it, say why.

| Box | Your question | A hint from your own history | Your answer |
| --- | --- | --- | --- |
| 1. Goal | When classifying one item goes well, what's true? What should happen when it can't get there? | 28 Sep: "succeeded" wasn't "useful" | agree. some content could be classified but not necessarily useful for the intent / context |
| 2. State | What does the loop need to remember about an item between tries? | Your rule: evidence travels with the signal | every try sends signal where the evidence should be memorised |
| 3. Actions | Besides "ask Gemini again", what could it do? List 2–4 and what each costs. | The Australian Broker items once had empty bodies | could have integrated deterministic rules to filter out empty content |
| 4. Observation | After each action, what do you look at? | A fetch can fail, or bring back nothing new | output rationale, evidence quote, and latency |
| 5. Evaluator | What checks decide "good enough"? Which can be plain code, which need judgement? | Your rule: confidence is not truth | still need to evaluate the outcome against context, merely looking at confidence isnt enough. |
| 6. Retry | When a check fails, what changes before the next try? | The 34 calls for 17 items with a dead key | should update the log /journal first. then diagnose based on the possibility of files  / process that could cause issue / problem. |
| 7. Stop | List every reason to stop, including the ones that aren't success. | The 29 Sep run that hung for nearly two hours | agree |
| 8. Human gate | When does it hand an item to you, and where do you see it? | 6 Oct: an alarm that can't reach you isn't an alarm | for now, the human gate is review the generated content and insights every morning.&#32; |

## What happens next

Send Claude your Step 1 notes and your 8 boxes together, or the boxes alone. Claude goes through them one by one: where yours is stronger than the spec, where it's vague, and where it would break on a real morning.

- [x] Step 1 table filled from 5 real classify traces
- [x] All 8 boxes answered
- [ ] Review with Claude, then compare with the reference design
- [ ] Agreed design saved to the project
- [ ] Fix: record what was fetched and what was dropped (lesson 11)
- [ ] Fix: make "every fetch failed" a visible failure, not an empty brief
- [ ] Claude Code builds the loop
