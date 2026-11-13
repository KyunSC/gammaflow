/**
 * Prop-firm account presets.
 *
 * Plain data, one array entry per account size, so a rule change is an edit
 * here rather than in the simulator. Every value can also be overridden from
 * the strategy panel: firms reprice often and run promotions, and the
 * published summaries disagree with each other.
 *
 * Lucid Trading, rules as of Sep 2026. lucidtrading.com blocks automated reads, so
 * the rules come from third-party summaries — verify before trusting a number.
 * Prices (25K-100K) are list prices from Lucid's own pricing page, 4 Nov 2026
 * (user screenshots): one-time payments, with a ~30% coupon usually running. The
 * 150K prices were not visible there and are the older third-party figures:
 *   https://propfirm.compare/propfirm/lucid-trading
 *   https://tradetanto.com/learn/lucid-trading-rules-explained-every-plan-rule-and-limit
 *   https://proptradingvibes.com/blog/lucid-trading-payout-rules
 *
 * Topstep, as of Nov 2026, from Topstep's own help centre (help.topstep.com).
 * Where its pages disagree the newest help article wins: the Payout Policy's
 * per-size caps over the June 2025 rules page, the pricing article's table over
 * marketing pages. Labs drops (static-drawdown and $250K Combines, Challenges)
 * are limited runs and are left out.
 *
 * Alpha Futures, as of Nov 2026, from its help centre (help.alpha-futures.com)
 * and the fee PDF attached there. Its pages disagree on two figures; both use the
 * newer or better-corroborated help article: Zero 50K at $169 (the how-it-works page
 * says $139), Direct 50K's cap at $2,000 (one article says $1,500). "MLL unchanged by
 * a withdrawal" is stated for Standard and Zero. It is applied to Advanced and
 * Direct on the strength of the MLL article's one rule for all accounts.
 *
 * MyFundedFutures, as of Nov 2026, from its help centre, payout policy and plan
 * pages. Prices are list prices from the plan pages' structured offers: promotions
 * run about 40% below them. The current line is Rapid, Rapid EOD, Builder and the
 * redesigned Pro. Flex and the old Pro are in its Legacy collection, Studio is a
 * capped limited release, and the Pro One Day and Builder lower-MLL add-ons are
 * left out. The payout policy says Pro can withdraw 60% before clearing the buffer;
 * the Pro guide and plan page both require it cleared, and they are followed here.
 *
 * Conventions used by `account.js`:
 *   - drawdown 'eod'      threshold = peak end-of-day balance − maxLoss
 *     drawdown 'intraday' threshold = peak intraday equity − maxLoss
 *     Either stops trailing at start + lockOffset, and locks there after the
 *     first payout.
 *   - eval.drawdown applies the same choice to the evaluation (default 'eod').
 *     eval.lockOffset (number, per-size array, or null for "never stops")
 *     overrides where the evaluation's threshold stops; default lockOffset.
 *   - dailyLossLimit is soft: hitting it flattens you for the rest of the day.
 *   - consistency c: the best day may be at most c × the profit it is judged
 *     against (total profit in an evaluation, cycle profit when funded).
 *   - payoutFraction f: request f × profit above the starting balance.
 *     null: request everything above `buffer`.
 *   - arrays indexed by payout number repeat their last value.
 *   - per-size arrays are indexed by SIZES; `sizes` on a firm or a plan lists the
 *     ids it sells, and sizes it doesn't sell are null (or whatever a shared
 *     constant holds there: unsold sizes are never read).
 *   - priceNoDll is the price without the daily loss limit, where it differs.
 *   - price is the list price. promo (on a firm) is the discount that usually runs:
 *     promo.pct off `price` (not off activation fees). A plan's per-size promoPct, where
 *     set, overrides the firm's for that size. The Python studies price every
 *     result at both, from this file only (functions/ml/prop_prices.py).
 *   - rebillDays n: `price` recurs every n trading days of the evaluation.
 *     null: `price` is paid once. A failed account is assumed cancelled at once.
 *   - activationOnPass: activationFee is owed only by accounts that pass.
 *   - dllOptional: the limit is the trader's choice, so both variants are real.
 *     dllFundedOnly: it applies once funded, not in the evaluation.
 *   - funded.consistencyStrict: the best day must be below c × profit, not at it.
 *   - funded.payoutKeepsMll: a payout leaves the threshold where it was and it
 *     keeps trailing from the old high. Otherwise a payout locks it.
 *   - funded.minPayout overrides the firm's, and may be per size.
 *   - funded.split overrides the firm's.
 *   - fundedScaling: per size, the funded account's max minis at each SCALING_PROFIT
 *     tier. The session's cap comes from the profit the account opened it with
 *     (limits never rise mid-session), so it falls back after a payout.
 */

export const PROP_ASOF = 'Sep 2026'

export const SIZES = [
  { id: '25k', label: '25K', balance: 25000 },
  { id: '50k', label: '50K', balance: 50000 },
  { id: '100k', label: '100K', balance: 100000 },
  { id: '150k', label: '150K', balance: 150000 },
]

// Funded scaling plans: profit floors, and the minis allowed from each one up.
// STD_SCALING is Alpha's Standard Qualified table (help.alpha-futures.com
// "Scaling Plan", read 12 Nov 2026). Topstep's XFA table is published only as
// an image; third-party copies of it match this one tier for tier.
const SCALING_PROFIT = [0, 1500, 2000, 3000, 4500]
const STD_SCALING = [null, [2, 3, 5, 5, 5], [3, 4, 5, 10, 10], [3, 4, 5, 10, 15]]

const STD_MAX_LOSS = [1000, 2000, 3000, 4500]
const STD_MAX_MINIS = [2, 4, 6, 10]
const STD_TARGET = [1250, 3000, 6000, 9000]
const STD_DLL = [600, 1200, 1800, 2700]
const STD_BUFFER = [26100, 52100, 103100, 154600]
const ZERO = [0, 0, 0, 0]
const NO_DLL = [null, null, null, null]

// Shared by all four Topstep plans: the Combine is the same, and what differs
// is how it is billed and which payout path the funded account takes.
const TOPSTEP_COMBINE = {
  rebillDays: 21, // "rebills every 30 days" ≈ 21 trading days; stops on a pass
  activationOnPass: true,
  dllOptional: true,
  maxLoss: [null, 2000, 3000, 4500],
  maxMinis: [null, 5, 10, 15],
  fundedScaling: STD_SCALING, // XFA Scaling Plan, by balance (an XFA starts at $0)
  dailyLossLimit: [null, 1000, 2000, 3000], // optional; a session break, not a violation
  // Exceeding 55% raises the target rather than failing the account, which is
  // what "best day ≤ c × profit" already means. Two days follows from it.
  eval: { profitTarget: [null, 3000, 6000, 9000], consistency: 0.55, minDays: 2 },
}
const TOPSTEP_FUNDED = {
  drawdown: 'eod',
  profitGoal: ZERO,
  buffer: ZERO,
  payoutFraction: 0.5,
  // No payout count ends an XFA: Live is a Risk Team call-up, not a threshold,
  // and it isn't simulated. 99 only stands in for "no limit".
  maxPayouts: 99,
}
const TOPSTEP_STANDARD_PATH = {
  ...TOPSTEP_FUNDED,
  consistency: 0,
  minDays: 5,
  minProfitDays: 5,
  minDayProfit: [null, 150, 150, 150],
  payoutCap: [null, [2000], [3000], [5000]],
  payoutCapDll: [null, [4000], [6000], [10000]], // limited-time offer for adding a DLL
}
const TOPSTEP_CONSISTENCY_PATH = {
  ...TOPSTEP_FUNDED,
  consistency: 0.4,
  minDays: 3,
  minProfitDays: 0,
  minDayProfit: ZERO,
  payoutCap: [null, [3000], [4000], [6000]],
  payoutCapDll: [null, [6000], [8000], [12000]],
}
const TOPSTEP_STANDARD_BILLING = {
  price: [null, 49, 99, 199],
  activationFee: [null, 149, 149, 149],
}
const TOPSTEP_NO_FEE_BILLING = {
  price: [null, 85, 129, 199], // Responsible Trading Discount for adding a DLL
  priceNoDll: [null, 95, 149, 229],
  activationFee: ZERO,
}

// LucidDaily's news rule and funded account, shared with its intraday-evaluation variant.
const LUCID_DAILY_NEWS = { impact: 'high', beforeMin: 1, afterMin: 1, maxBarMin: 5 }
const LUCID_DAILY_FUNDED = {
  drawdown: 'intraday',
  consistency: 0,
  minDays: 1,
  minProfitDays: 0,
  minDayProfit: ZERO,
  profitGoal: ZERO,
  buffer: STD_BUFFER,
  payoutFraction: null,
  payoutCap: [[null], [null], [null], [null]],
  maxPayouts: 1,
}

// The target every MFF plan shares. The buffer is the max loss + $100.
const MFF_TARGET = [1500, 3000, 6000, 9000]
const MFF_FUNDED = {
  consistency: 0,
  minProfitDays: 0,
  minDayProfit: ZERO,
  buffer: STD_BUFFER,
  payoutFraction: null, // everything above the buffer, up to the cap
}

// Shared by Alpha's three Qualified paths that follow an evaluation.
const ALPHA_FUNDED = {
  drawdown: 'eod',
  minDays: 5,
  minProfitDays: 5,
  minDayProfit: [200, 200, 200, 200],
  profitGoal: ZERO,
  buffer: ZERO,
  payoutFraction: 0.5,
  payoutKeepsMll: true,
  // Five payouts on one account "may" prompt a Live review, but no count ends an
  // account. Live isn't simulated, and 99 only stands in for "no limit".
  maxPayouts: 99,
}

export const FIRMS = {
  lucid: {
    id: 'lucid',
    label: 'Lucid Trading',
    url: 'https://lucidtrading.com',
    promo: { pct: 0.3, label: 'coupon at checkout', asof: '4 Nov 2026' },
    commissionPerSide: 0.5,
    split: 0.9,
    minPayout: 500,
    lockOffset: 100,
    flatByEt: 16 * 60 + 45,
    plans: {
      flex: {
        id: 'flex',
        label: 'LucidFlex',
        blurb: 'EOD trailing, 50% eval consistency, no funded consistency. Payouts every 5 profitable days.',
        price: [65, 115, 215, 250],
        activationFee: ZERO,
        maxLoss: STD_MAX_LOSS,
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: STD_DLL,
        eval: { profitTarget: STD_TARGET, consistency: 0.5, minDays: 2 },
        funded: {
          drawdown: 'eod',
          consistency: 0,
          minDays: 5,
          minProfitDays: 5,
          minDayProfit: [100, 150, 200, 250],
          profitGoal: ZERO,
          buffer: ZERO,
          payoutFraction: 0.5,
          payoutCap: [[1000], [2000], [2500], [3000]],
          maxPayouts: 5,
        },
      },
      pro: {
        id: 'pro',
        label: 'LucidPro',
        blurb: 'EOD trailing, no eval consistency, 40% funded consistency, buffer before payouts.',
        price: [108, 172, 272, 245],
        activationFee: ZERO,
        maxLoss: STD_MAX_LOSS,
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: [null, 1200, 1800, 2700],
        eval: { profitTarget: STD_TARGET, consistency: 0, minDays: 1 },
        funded: {
          drawdown: 'eod',
          consistency: 0.4,
          minDays: 3,
          minProfitDays: 0,
          minDayProfit: ZERO,
          profitGoal: [250, 500, 750, 1000],
          buffer: STD_BUFFER,
          payoutFraction: null,
          payoutCap: [[1000, 1500], [2000, 2500], [2500, 3000], [3000, 3500]],
          maxPayouts: 5,
        },
      },
      daily: {
        id: 'daily',
        label: 'LucidDaily',
        blurb: 'Funded drawdown trails intraday. Payout any day above the buffer; flat from 1 min before to 1 min after high-impact USD news.',
        // Funded-account rule per proptradingvibes.com/blog/lucid-trading-news-trading-policy
        // (Oct 2026; the eval rule is unstated). The engine replays one path for eval
        // and funded, so it is applied to both — conservative for the eval. Bars
        // are blocked whole, so past 5m the two-minute window would become hours
        // flat: the rule is skipped there and the result says so.
        news: LUCID_DAILY_NEWS,
        price: [86, 122, 200, 260],
        activationFee: ZERO,
        maxLoss: STD_MAX_LOSS,
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: STD_DLL,
        eval: { profitTarget: STD_TARGET, consistency: 0.5, minDays: 2 },
        funded: LUCID_DAILY_FUNDED,
      },
      // One configuration of the Daily Eval picker on lucidtrading.com (user
      // screenshot, 11 Nov 2026): intraday drawdown in the evaluation, daily loss
      // limit on, on-demand payouts on, 40% consistency; $94 list at 50K, the only
      // size whose price was shown for it. Assumed, not shown: the 40% is the
      // evaluation's consistency, the funded account is LucidDaily's (the picker
      // hides the funded-drawdown choice once the evaluation is intraday), and the
      // evaluation's threshold stops at start + $100 like the funded one.
      dailyIntraday: {
        id: 'dailyIntraday',
        label: 'LucidDaily Intraday',
        blurb: 'LucidDaily with the drawdown trailing intraday in the evaluation too, and 40% eval consistency. Cheaper than LucidDaily.',
        sizes: ['50k'],
        news: LUCID_DAILY_NEWS,
        price: [null, 94, null, null],
        activationFee: ZERO,
        maxLoss: STD_MAX_LOSS,
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: STD_DLL,
        eval: { profitTarget: STD_TARGET, consistency: 0.4, minDays: 2, drawdown: 'intraday' },
        funded: LUCID_DAILY_FUNDED,
      },
      direct: {
        id: 'direct',
        label: 'LucidDirect',
        blurb: 'Straight to funded — no evaluation. 20% consistency, profit goal and buffer per payout.',
        price: [329, 515, 700, 836],
        activationFee: ZERO,
        maxLoss: [1000, 2000, 3500, 5000],
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: [null, 1200, 2100, 3000],
        eval: null,
        funded: {
          drawdown: 'eod',
          consistency: 0.2,
          minDays: 5,
          minProfitDays: 0,
          minDayProfit: ZERO,
          profitGoal: [[1500, 1500, 1500, 1250], [3000, 3000, 3000, 2500], [6000, 6000, 6000, 3500], [9000, 9000, 9000, 4500]],
          buffer: [26600, 52600, 103600, 155100],
          payoutFraction: null,
          payoutCap: [[1000, 1000, 1000, 1000], [2000, 2000, 2000, 2500], [2500, 2500, 2500, 3000], [3000, 3000, 3000, 3500]],
          maxPayouts: 5,
        },
      },
    },
  },
  topstep: {
    id: 'topstep',
    label: 'Topstep',
    url: 'https://help.topstep.com',
    asof: 'Nov 2026',
    sizes: ['50k', '100k', '150k'],
    commissionPerSide: 0.61, // MNQ/MES $1.22 round turn on TopstepX, all fees in
    split: 0.9,
    minPayout: 125,
    lockOffset: 0, // the MLL locks at the start balance, and at $0 after a payout
    flatByEt: 16 * 60 + 10, // 3:10 PM CT
    plans: {
      standard: {
        id: 'standard',
        label: 'Standard',
        blurb: 'Monthly Combine, $149 activation on a pass. EOD trailing, 55% Combine consistency. Payouts after 5 $150+ days.',
        ...TOPSTEP_COMBINE,
        ...TOPSTEP_STANDARD_BILLING,
        funded: TOPSTEP_STANDARD_PATH,
      },
      consistency: {
        id: 'consistency',
        label: 'Consistency',
        blurb: 'Monthly Combine, $149 activation on a pass. EOD trailing. Payouts after 3 days at 40% consistency, with higher caps.',
        ...TOPSTEP_COMBINE,
        ...TOPSTEP_STANDARD_BILLING,
        funded: TOPSTEP_CONSISTENCY_PATH,
      },
      standardNoFee: {
        id: 'standardNoFee',
        label: 'Std no-fee',
        blurb: 'No activation fee for a higher monthly price. Payouts after 5 $150+ days.',
        ...TOPSTEP_COMBINE,
        ...TOPSTEP_NO_FEE_BILLING,
        funded: TOPSTEP_STANDARD_PATH,
      },
      consistencyNoFee: {
        id: 'consistencyNoFee',
        label: 'Cons no-fee',
        blurb: 'No activation fee for a higher monthly price. Payouts after 3 days at 40% consistency.',
        ...TOPSTEP_COMBINE,
        ...TOPSTEP_NO_FEE_BILLING,
        funded: TOPSTEP_CONSISTENCY_PATH,
      },
    },
  },
  alpha: {
    id: 'alpha',
    label: 'Alpha Futures',
    url: 'https://help.alpha-futures.com',
    asof: 'Nov 2026',
    commissionPerSide: 0.66, // MNQ/MES $1.32 round trip, all fees in
    split: 0.9,
    minPayout: 500,
    lockOffset: 0, // stops trailing at the starting balance on all accounts
    flatByEt: 16 * 60 + 20,
    plans: {
      zero: {
        id: 'zero',
        label: 'Zero',
        blurb: 'Monthly evaluation with no consistency rule and a daily guard throughout. 40% Qualified consistency, smallest payouts.',
        sizes: ['25k', '50k', '100k'],
        rebillDays: 21, // rebills monthly from sign-up; ends on a pass
        price: [89, 169, 279, null],
        activationFee: ZERO,
        maxLoss: [1000, 2000, 3000, null],
        maxMinis: [1, 3, 6, null],
        fundedScaling: [null, [1, 2, 3, 3, 3], [2, 3, 4, 5, 6], null], // Zero Qualified table; 25K has none
        dailyLossLimit: [500, 1000, 2000, null],
        eval: { profitTarget: [1500, 3000, 6000, null], consistency: 0, minDays: 1 },
        funded: { ...ALPHA_FUNDED, consistency: 0.4, consistencyStrict: true, minPayout: 200, payoutCap: [[1000], [1500], [2500], [null]] },
      },
      standard: {
        id: 'standard',
        label: 'Standard',
        blurb: 'Monthly evaluation, 50% consistency, no daily guard until Qualified. Payouts after 5 $200+ days at 40% consistency.',
        sizes: ['50k', '100k', '150k'],
        rebillDays: 21,
        dllFundedOnly: true,
        price: [null, 129, 239, 349],
        activationFee: ZERO,
        maxLoss: [null, 2000, 3000, 4500],
        maxMinis: [null, 5, 10, 15],
        fundedScaling: STD_SCALING,
        dailyLossLimit: [null, 1000, 2000, 3000],
        eval: { profitTarget: [null, 3000, 6000, 9000], consistency: 0.5, minDays: 1 },
        funded: { ...ALPHA_FUNDED, consistency: 0.4, consistencyStrict: true, payoutCap: [null, [3000], [4000], [5000]] },
      },
      advanced: {
        id: 'advanced',
        label: 'Advanced',
        blurb: 'Dearest evaluation, 40% consistency, no daily guard or scaling. No Qualified consistency and a $15,000 cap.',
        sizes: ['50k', '100k', '150k'],
        rebillDays: 21,
        price: [null, 209, 349, 489],
        activationFee: ZERO,
        maxLoss: [null, 1750, 3500, 5250],
        maxMinis: [null, 5, 10, 15],
        dailyLossLimit: NO_DLL,
        eval: { profitTarget: [null, 4000, 8000, 12000], consistency: 0.4, minDays: 1 },
        funded: { ...ALPHA_FUNDED, consistency: 0, minPayout: 1000, payoutCap: [null, [15000], [15000], [15000]] },
      },
      direct: {
        id: 'direct',
        label: 'Direct',
        blurb: 'One-time fee, no evaluation. 20% consistency and a profit target before every withdrawal.',
        price: [349, 519, 689, 859],
        activationFee: ZERO,
        maxLoss: [1000, 2000, 3000, 4500],
        maxMinis: [2, 4, 8, 10],
        dailyLossLimit: [500, 1000, 2000, 3000],
        eval: null,
        funded: {
          ...ALPHA_FUNDED,
          consistency: 0.2,
          consistencyStrict: true,
          minDays: 1,
          minProfitDays: 0,
          minDayProfit: ZERO,
          profitGoal: [[1500, 1000], [3000, 2000], [6000, 4000], [9000, 6000]],
          payoutCap: [[1000], [2000], [2500], [3000]],
        },
      },
    },
  },
  mff: {
    id: 'mff',
    label: 'MyFundedFutures',
    url: 'https://help.myfundedfutures.com',
    asof: 'Nov 2026',
    promo: { pct: 0.4, label: 'coupon on all accounts', asof: '7 Nov 2026' },
    commissionPerSide: 0.95, // MNQ $1.90 "total cost round trip"
    split: 0.9,
    minPayout: 500,
    lockOffset: 100,
    flatByEt: 16 * 60 + 10,
    plans: {
      rapid: {
        id: 'rapid',
        label: 'Rapid',
        blurb: 'One-time fee. 50% eval consistency, intraday trailing once funded. Daily payouts above the buffer, 90/10.',
        price: [145, 209, 356, 463],
        activationFee: ZERO,
        maxLoss: STD_MAX_LOSS,
        maxMinis: [3, 5, 8, 10],
        dailyLossLimit: NO_DLL,
        eval: { profitTarget: MFF_TARGET, consistency: 0.5, minDays: 2 },
        funded: {
          ...MFF_FUNDED,
          drawdown: 'intraday',
          minDays: 1,
          profitGoal: ZERO,
          payoutCap: [[null], [null], [null], [null]],
          // Live comes from a $10,000 day or a Risk review, so no count ends the
          // account. 99 only stands in for "no limit".
          maxPayouts: 99,
        },
      },
      rapidEod: {
        id: 'rapidEod',
        label: 'Rapid EOD',
        blurb: 'One-time fee. 30% eval consistency over 4 days, EOD drawdown throughout. Daily payouts above the buffer, 90/10.',
        sizes: ['25k', '50k'],
        price: [145, 225, null, null],
        promoPct: [null, 0.45, null, null], // 7 Nov 2026: 45% off Rapid EOD 50K beats the 40% sitewide
        activationFee: ZERO,
        maxLoss: [1000, 2000, null, null],
        maxMinis: [2, 3, null, null],
        dailyLossLimit: NO_DLL,
        eval: { profitTarget: [1500, 3000, null, null], consistency: 0.3, minDays: 4 },
        funded: {
          ...MFF_FUNDED,
          drawdown: 'eod',
          minDays: 1,
          profitGoal: [[0, 250], [0, 500], null, null],
          payoutCap: [[null], [null], null, null],
          maxPayouts: 99,
        },
      },
      builder: {
        id: 'builder',
        label: 'Builder',
        blurb: 'One-time fee, no eval consistency, soft daily limit throughout. Capped payouts at 50% cycle consistency, 80/20. Five payouts, then Live.',
        price: [105, 153, 282, 398],
        activationFee: ZERO,
        maxLoss: STD_MAX_LOSS,
        maxMinis: [2, 4, 6, 9],
        dailyLossLimit: [600, 1000, 1750, 2500],
        eval: { profitTarget: MFF_TARGET, consistency: 0, minDays: 1 },
        funded: {
          ...MFF_FUNDED,
          drawdown: 'eod',
          consistency: 0.5,
          minDays: 2,
          profitGoal: [[0, 250], [0, 500], [0, 1000], [0, 1500]],
          payoutCap: [[1000], [2000], [3000], [3500]],
          minPayout: [250, 500, 1000, 1500],
          split: 0.8,
          maxPayouts: 5,
        },
      },
      pro: {
        id: 'pro',
        label: 'Pro',
        blurb: 'One-time fee, 50% eval consistency, no daily limit. Payouts above the buffer every 14 days, 80/20. Three payouts, then a Live review.',
        sizes: ['50k', '100k', '150k'],
        price: [null, 265, 401, 557],
        activationFee: ZERO,
        maxLoss: [null, 2000, 3000, 4500],
        maxMinis: [null, 3, 6, 9],
        dailyLossLimit: NO_DLL,
        eval: { profitTarget: [null, 3000, 6000, 9000], consistency: 0.5, minDays: 2 },
        funded: {
          ...MFF_FUNDED,
          drawdown: 'eod',
          minDays: 10, // 14 calendar days ≈ 10 trading days
          profitGoal: ZERO,
          payoutCap: [null, [100000], [100000], [100000]],
          minPayout: 1000,
          split: 0.8,
          maxPayouts: 3,
        },
      },
    },
  },
}

export const FIRM_LIST = Object.values(FIRMS)

/**
 * Apex Trader Funding prices only. Its rules are provisional and live in
 * functions/ml/data/prop_structure/apex/apex_study.py, so it is not a FIRMS entry
 * (not simulated in the UI). Per size [25K, 50K]: evaluation list price and the
 * activation fee owed on pass. Coupons run 90% off the evaluation price, never off
 * activation. Verified 4 Nov 2026 on Apex's own product picker and coupon page
 * (functions/ml/data/prop_realtape/apex_verified/rules.json; SAVENOW, to 10 Nov).
 * The 50K EOD '3rd-party' source label is now stale but kept, so stored results
 * keep their scheme names.
 */
export const APEX_PRICES = {
  asof: 'Nov 2026',
  provisional: true,
  promo: { pct: 0.9, label: 'coupon', asof: 'Nov 2026' },
  intraday: { price: [167, 249], activationFee: [89, 99] },
  intradayNoActivation: { price: [null, 799], activationFee: [null, 0] },
  eod: { price: [490, 590], activationFee: [109, 129], source: [null, '3rd-party'] },
}

const asList = (v) => (Array.isArray(v) ? v : [v])
const bySize = (v, si) => (Array.isArray(v) ? v[si] : v)

/** The account sizes a firm, or one of its plans, sells, in SIZES order. */
export function sizesFor(firm, plan) {
  const sold = plan?.sizes || firm.sizes
  return SIZES.filter((s) => !sold || sold.includes(s.id))
}

/** `$115`, or `$49/mo` (`long`: `$49/mo + $149 on pass`) for a plan billed monthly. */
export function priceLabel(p, long) {
  if (!p.rebillDays) return `$${(p.price + p.activationFee).toLocaleString()}`
  return `$${p.price}/mo${long && p.activationFee ? ` + $${p.activationFee} on pass` : ''}`
}

/** Minis a funded account may hold after opening a session `profit` above its start; null without a scaling plan. */
export function fundedMinis(plan, profit) {
  if (!plan.fundedScaling) return null
  let minis = plan.fundedScaling[0][1]
  for (const [floor, m] of plan.fundedScaling) if (profit >= floor) minis = m
  return minis
}

/**
 * Store patch for switching firm: another firm's plan, size, commission, edits and
 * daily-limit choice don't carry over (off means something different at each firm).
 */
export function firmPreset(id) {
  const firm = FIRMS[id] ? id : 'lucid'
  const r = resolvePlan({ firm, plan: Object.keys(FIRMS[firm].plans)[0] })
  return { firm: r.firm, plan: r.plan, size: r.size, dll: true, commissionPerSide: r.commissionPerSide, overrides: {} }
}

/**
 * Flat, fully-resolved rules for one account — what the simulator and the UI
 * read. `overrides` uses the same flat keys, so an edited field simply wins.
 */
export function resolvePlan({ firm = 'lucid', plan = 'flex', size = '50k', dll = true, overrides = {} } = {}) {
  const f = FIRMS[firm] || FIRMS.lucid
  const p = f.plans[plan] || Object.values(f.plans)[0]
  const sizes = sizesFor(f, p)
  const si = SIZES.indexOf(sizes.find((s) => s.id === size) || sizes[0])
  const start = SIZES[si].balance
  const fu = p.funded

  const base = {
    firm: f.id,
    firmLabel: f.label,
    plan: p.id,
    planLabel: p.label,
    size: SIZES[si].id,
    sizeLabel: SIZES[si].label,
    dll: Boolean(dll),
    startBalance: start,
    price: (dll ? p.price : p.priceNoDll ?? p.price)[si],
    promoPct: p.promoPct?.[si] ?? f.promo?.pct ?? 0,
    rebillDays: p.rebillDays || null,
    activationFee: p.activationFee[si],
    activationOnPass: Boolean(p.activationOnPass),
    commissionPerSide: f.commissionPerSide,
    maxLoss: p.maxLoss[si],
    lockOffset: f.lockOffset,
    maxMinis: p.maxMinis[si],
    fundedScaling: p.fundedScaling?.[si] ? SCALING_PROFIT.map((floor, t) => [floor, p.fundedScaling[si][t]]) : null,
    dailyLossLimit: dll ? p.dailyLossLimit[si] : null,
    dllOptional: Boolean(p.dllOptional),
    dllFundedOnly: Boolean(p.dllFundedOnly),
    flatByEt: f.flatByEt,
    news: p.news || null,
    hasEval: Boolean(p.eval),
    profitTarget: p.eval ? p.eval.profitTarget[si] : 0,
    evalConsistency: p.eval ? p.eval.consistency : 0,
    evalMinDays: p.eval ? p.eval.minDays : 0,
    evalDrawdown: p.eval?.drawdown || 'eod',
    evalLockOffset: p.eval && 'lockOffset' in p.eval ? bySize(p.eval.lockOffset, si) : f.lockOffset,
    fundedDrawdown: fu.drawdown,
    fundedConsistency: fu.consistency,
    fundedConsistencyStrict: Boolean(fu.consistencyStrict),
    payoutKeepsMll: Boolean(fu.payoutKeepsMll),
    fundedMinDays: fu.minDays,
    minProfitDays: fu.minProfitDays,
    minDayProfit: fu.minDayProfit[si],
    profitGoal: asList(fu.profitGoal[si]),
    buffer: fu.buffer[si],
    payoutFraction: fu.payoutFraction,
    payoutCap: asList((dll && fu.payoutCapDll ? fu.payoutCapDll : fu.payoutCap)[si]),
    minPayout: bySize(fu.minPayout, si) ?? f.minPayout,
    split: fu.split ?? f.split,
    maxPayouts: fu.maxPayouts,
  }
  const out = { ...base }
  for (const [k, v] of Object.entries(overrides || {})) {
    if (!(k in base) || v === undefined || v === '') continue
    if (Array.isArray(base[k])) out[k] = asList(v)
    else out[k] = v
  }
  out.overridden = Object.keys(overrides || {}).filter((k) => k in base && JSON.stringify(out[k]) !== JSON.stringify(base[k]))
  return out
}

/** Value for payout number `k` (0-based) from a per-payout list. */
export function nth(list, k) {
  if (!list || !list.length) return null
  return list[Math.min(k, list.length - 1)]
}
