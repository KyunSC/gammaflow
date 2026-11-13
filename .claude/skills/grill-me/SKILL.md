---
name: grill-me
description: Interview the user hard about a plan — a trading study, a strategy change, or a feature — before any code runs or any test window is spent. Only when the user asks to be grilled.
disable-model-invocation: true
---

# Grill me

The user wants their plan stress-tested before they commit to it. Your job is to find the decision they haven't made, the assumption they haven't checked, and the result they couldn't act on. Do not write or run code while grilling, other than read-only lookups.

## How to run it

- Ask **one question at a time** (two at most if they are tightly linked). Wait for the answer.
- With each question, give **your recommended answer** and why, so the user can just say "yes" when you are right.
- **Answer it yourself when the repo can.** Before asking, check the code, `functions/ml/*.md`, the memory notes, and the lock/prereg files. Ask only what needs the user's judgement, and say what you found.
- Walk the decision tree in dependency order: settle a branch before the decisions that hang off it. If an answer reopens an earlier decision, say so and go back.
- Push back on vague answers ("we'll see", "probably fine", "tune it later"). A decision is resolved only when it is specific enough to fail.
- Skip branches that don't apply, and say you skipped them. Don't pad.
- Stop when every branch is resolved or explicitly deferred by the user.

## Branches for a research study

Use these for anything that will be judged on data (backtests, ML runs, flybrain searches, prop-firm sims). For a plain feature, use only the last branch.

1. **Hypothesis and mechanism.** What exactly is the claim, and why should the edge exist (who is on the other side)? What result would refute it? Has a close variant already failed? Check the memory notes before the user answers.
2. **Data and windows.** Which instruments and dates for discovery, and which for the holdout?
   - Check every window against the consumed and reserved windows in the memory notes, and look for existing locks: `find functions/ml/data -name '*.lock' -o -name 'preregistered*.json'`. Overlap with a spent window means that window is in-sample, so say so plainly.
   - A window that is unspent for one kind of hypothesis may already be spent for another (e.g. used as an overnight-fade holdout). Flag it.
   - Proxy risks: ETF→futures scaling, roll days, yfinance phantom ticks, RTH-only tick data, Binance zero-volume padding.
3. **Look-ahead and timing.** Is every input known at decision time? Check bar-start vs bar-end timestamps, UTC epochs, GEX snapshot times (the yfinance chain lags ~10 min), and session boundaries (09:25 / 16:00 ET).
4. **The gate, written now.** Define PASS / FAIL / STRUCTURE-ONLY before any run, with numbers: minimum trades, mean net R threshold, which instruments must agree, CI or DSR requirement. Count the cells being tried and ask how the gate accounts for them.
5. **Power.** With the expected trade count, what is the smallest mean R the holdout can detect? If the selected cell will produce too few trades to ever PASS, the holdout is wasted: say so before it is spent.
6. **Controls.** Which null must it beat? Random-direction, constant-direction session-open baseline, coin-flip twins, push control, or the same trade with the filter removed. A filter study needs the unfiltered version as a control.
7. **Costs and fills.** Commission per side, cost in R at this stop width, target fill rule (tick-through vs touch), stop slippage model (empirical PMF vs assumed), news-time tails. Pull current figures from the fill-study and commission notes rather than asking.
8. **Account layer (prop-firm studies).** Which plan, what risk per trade, and is it sized by the `lucid_structure.py` sawtooth rule? What is the EV at zero edge? Make sure a positive result can't come only from payout asymmetry.
9. **One look and afterwards.** Who approves opening the holdout, and how is a second look blocked (lock file)? If it passes, what happens next? If it fails, what have we learned and what will be recorded?

## Branches for any plan

- What does done look like, and how will we know?
- What is out of scope?
- What is the cheapest version that tests the riskiest assumption first?
- What alternative did the user reject, and why?
- What breaks in production or local-only modes (e.g. real prints vs simulated, Render vs local)?

## When it ends

Give a short record of the result:

- **Decided:** each resolved decision, one line each.
- **Deferred:** what the user chose to leave open, and what would force the decision.
- **Risks still open:** anything you still think is wrong, stated plainly.

For a study, offer to turn this into a pre-registration file in the style of `functions/ml/ORDERFLOW_GEX_PREREG.md` (why this test, test data, the frozen rule, controls, pass criteria, one look). Write it only if the user says yes.
