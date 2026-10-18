/**
 * Prop-firm account presets.
 *
 * Plain data, one array entry per account size, so a rule change is an edit
 * here rather than in the simulator. Every value can also be overridden from
 * the strategy panel: firms reprice often and run promotions, and the
 * published summaries disagree with each other.
 *
 * Lucid Trading, as of Sep 2026. lucidtrading.com blocks automated reads, so
 * these come from third-party summaries — verify before trusting a number:
 *   https://propfirm.compare/propfirm/lucid-trading
 *   https://tradetanto.com/learn/lucid-trading-rules-explained-every-plan-rule-and-limit
 *   https://proptradingvibes.com/blog/lucid-trading-payout-rules
 *
 * Conventions used by `account.js`:
 *   - drawdown 'eod'      threshold = peak end-of-day balance − maxLoss
 *     drawdown 'intraday' threshold = peak intraday equity − maxLoss
 *     Either stops trailing at start + lockOffset, and locks there after the
 *     first payout.
 *   - dailyLossLimit is soft: hitting it flattens you for the rest of the day.
 *   - consistency c: the best day may be at most c × the profit it is judged
 *     against (total profit in an evaluation, cycle profit when funded).
 *   - payoutFraction f: request f × profit above the starting balance.
 *     null: request everything above `buffer`.
 *   - arrays indexed by payout number repeat their last value.
 *
 * MyFundedPerps, as of 2026-10-18, from its own docs (docs.myfundedperpetuals.com:
 * Challenges and Rules, Elite Accounts, Payouts, Commissions and Fees, Breaches)
 * except where marked third-party. Its rules differ in kind, not just in value,
 * so the plan carries extra modes that `account.js` reads:
 *   - drawdown 'static'   threshold = start − maxLoss and never trails;
 *     `lockOnPayout` moves it to start + lockOffset on the first payout
 *     (Select / Prime / Signature) or leaves it for life (Elite)
 *   - dllMode 'fail'      touching the daily floor fails the account (Lucid's
 *     'flatten' only ends the day)
 *   - dayBoundary 'ny'    the day resets at midnight America/New_York
 *   - passIntrabar        the evaluation passes the moment equity, open P&L
 *     included, touches the target
 *   - payoutFrom 'cycle'  profit is counted from the balance after the last
 *     payout; whatever a payout leaves behind can never be withdrawn
 *   - lifetimeCap         trader take (after split) across all payouts
 *   - inactivity          calendar days without a fill that close the account
 */

export const PROP_ASOF = 'Sep 2026'

export const SIZES = [
  { id: '25k', label: '25K', balance: 25000 },
  { id: '50k', label: '50K', balance: 50000 },
  { id: '100k', label: '100K', balance: 100000 },
  { id: '150k', label: '150K', balance: 150000 },
]

const MFP_SIZES = [
  { id: '5k', label: '5K', balance: 5000 },
  { id: '10k', label: '10K', balance: 10000 },
  { id: '25k', label: '25K', balance: 25000 },
  { id: '50k', label: '50K', balance: 50000 },
  { id: '100k', label: '100K', balance: 100000 },
]

/**
 * One MyFundedPerps plan in the shape `resolvePlan` reads. Rules are quoted as
 * fractions of the starting balance, so they are expanded per size here; sizes
 * a plan does not sell are null. Select / Prime / Signature sell 10K–100K and
 * Elite 5K–50K; their list prices for the first three come from
 * comparefuturesprop.com (rules reviewed 2026-09-29), not from MFP.
 */
function mfpPlan({ id, label, blurb, sizes = ['10k', '25k', '50k', '100k'], target, maxLoss, dllOptional = false, price, priceNoDll = null, minPayoutPct = 0, lockOnPayout = true, boosted = false }) {
  const pick = (list) => MFP_SIZES.map((s) => (sizes.includes(s.id) ? list[sizes.indexOf(s.id)] : null))
  const pct = (f) => MFP_SIZES.map((s) => (sizes.includes(s.id) ? Math.round(f * s.balance) : null))
  const zeros = MFP_SIZES.map(() => 0)
  return {
    id,
    label,
    blurb,
    sizes,
    dllOptional,
    boosted,
    price: pick(price),
    priceNoDll: priceNoDll ? pick(priceNoDll) : null,
    activationFee: zeros,
    maxLoss: pct(maxLoss),
    maxMinis: zeros,
    dailyLossLimit: pct(0.03),
    dllMode: 'fail',
    dayBoundary: 'ny',
    inactivity: { eval: 30, funded: 7 },
    lifetimeCap: 100000,
    eval: { profitTarget: pct(target), consistency: 0, minDays: 0, drawdown: 'static', passIntrabar: true },
    funded: {
      drawdown: 'static',
      lockOnPayout,
      consistency: 0,
      minDays: 0,
      minProfitDays: 0,
      minDayProfit: zeros,
      profitGoal: zeros,
      buffer: zeros,
      payoutFraction: null,
      payoutFrom: 'cycle',
      payoutCap: MFP_SIZES.map(() => null),
      minPayout: minPayoutPct ? pct(minPayoutPct) : null,
      maxPayouts: null,
    },
  }
}

const STD_MAX_LOSS = [1000, 2000, 3000, 4500]
const STD_MAX_MINIS = [2, 4, 6, 10]
const STD_TARGET = [1250, 3000, 6000, 9000]
const STD_DLL = [600, 1200, 1800, 2700]
const STD_BUFFER = [26100, 52100, 103100, 154600]

export const FIRMS = {
  lucid: {
    id: 'lucid',
    label: 'Lucid Trading',
    url: 'https://lucidtrading.com',
    split: 0.9,
    minPayout: 500,
    lockOffset: 100,
    flatByEt: 16 * 60 + 45,
    plans: {
      flex: {
        id: 'flex',
        label: 'LucidFlex',
        blurb: 'EOD trailing, 50% eval consistency, no funded consistency. Payouts every 5 profitable days.',
        price: [50, 90, 170, 250],
        priceNoDll: [50, 90, 170, 250],
        activationFee: [0, 0, 0, 0],
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
          profitGoal: [0, 0, 0, 0],
          buffer: [0, 0, 0, 0],
          payoutFraction: 0.5,
          payoutCap: [[1000], [2000], [2500], [3000]],
          maxPayouts: 5,
        },
      },
      pro: {
        id: 'pro',
        label: 'LucidPro',
        blurb: 'EOD trailing, no eval consistency, 40% funded consistency, buffer before payouts.',
        price: [90, 115, 180, 245],
        priceNoDll: [90, 115, 180, 245],
        activationFee: [0, 0, 0, 0],
        maxLoss: STD_MAX_LOSS,
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: [null, 1200, 1800, 2700],
        eval: { profitTarget: STD_TARGET, consistency: 0, minDays: 1 },
        funded: {
          drawdown: 'eod',
          consistency: 0.4,
          minDays: 3,
          minProfitDays: 0,
          minDayProfit: [0, 0, 0, 0],
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
        blurb: 'Funded drawdown trails intraday. Payout any day above the buffer; news trading not allowed (not modelled).',
        price: [80, 110, 185, 260],
        priceNoDll: [80, 110, 185, 260],
        activationFee: [0, 0, 0, 0],
        maxLoss: STD_MAX_LOSS,
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: STD_DLL,
        eval: { profitTarget: STD_TARGET, consistency: 0.5, minDays: 2 },
        funded: {
          drawdown: 'intraday',
          consistency: 0,
          minDays: 1,
          minProfitDays: 0,
          minDayProfit: [0, 0, 0, 0],
          profitGoal: [0, 0, 0, 0],
          buffer: STD_BUFFER,
          payoutFraction: null,
          payoutCap: [[null], [null], [null], [null]],
          maxPayouts: 1,
        },
      },
      direct: {
        id: 'direct',
        label: 'LucidDirect',
        blurb: 'Straight to funded — no evaluation. 20% consistency, profit goal and buffer per payout.',
        price: [329, 575, 705, 836],
        priceNoDll: [329, 575, 705, 836],
        activationFee: [0, 0, 0, 0],
        maxLoss: [1000, 2000, 3500, 5000],
        maxMinis: STD_MAX_MINIS,
        dailyLossLimit: [null, 1200, 2100, 3000],
        eval: null,
        funded: {
          drawdown: 'eod',
          consistency: 0.2,
          minDays: 5,
          minProfitDays: 0,
          minDayProfit: [0, 0, 0, 0],
          profitGoal: [[1500, 1500, 1500, 1250], [3000, 3000, 3000, 2500], [6000, 6000, 6000, 3500], [9000, 9000, 9000, 4500]],
          buffer: [26600, 52600, 103600, 155100],
          payoutFraction: null,
          payoutCap: [[1000, 1000, 1000, 1000], [2000, 2000, 2000, 2500], [2500, 2500, 2500, 3000], [3000, 3000, 3000, 3500]],
          maxPayouts: 5,
        },
      },
    },
  },
  mfp: {
    id: 'mfp',
    label: 'MyFundedPerps',
    url: 'https://docs.myfundedperpetuals.com',
    asof: '2026-10-18',
    instrument: 'perp',
    split: 0.8,
    minPayout: 100,
    lockOffset: 0,
    flatByEt: 0,
    sizes: MFP_SIZES,
    plans: {
      elite: mfpPlan({
        id: 'elite',
        label: 'Elite',
        blurb: '10% target, 5% static floor that never moves, on-demand payouts, cheaper and boosted NAS100/SP500/gold/oil. 3% DLL or none.',
        sizes: ['5k', '10k', '25k', '50k'],
        target: 0.1,
        maxLoss: 0.05,
        dllOptional: true,
        price: [49, 95, 249, 495],
        priceNoDll: [89, 175, 449, 889],
        minPayoutPct: 0.01,
        lockOnPayout: false,
        boosted: true,
      }),
      select: mfpPlan({
        id: 'select',
        label: 'Select',
        blurb: '9% target, 3% static floor that locks at the start balance on the first payout. Prices are third-party.',
        target: 0.09,
        maxLoss: 0.03,
        price: [40, 100, 190, 360],
      }),
      prime: mfpPlan({
        id: 'prime',
        label: 'Prime',
        blurb: '12% target, 5% static floor that locks at the start balance on the first payout. Prices are third-party.',
        target: 0.12,
        maxLoss: 0.05,
        price: [60, 160, 300, 595],
      }),
      signature: mfpPlan({
        id: 'signature',
        label: 'Signature',
        blurb: '10% target, 6% static floor that locks at the start balance on the first payout. Prices are third-party.',
        target: 0.1,
        maxLoss: 0.06,
        price: [90, 225, 430, 870],
      }),
    },
  },
}

export const FIRM_LIST = Object.values(FIRMS)

const asList = (v) => (Array.isArray(v) ? v : [v])

/**
 * Flat, fully-resolved rules for one account — what the simulator and the UI
 * read. `overrides` uses the same flat keys, so an edited field simply wins.
 */
export function resolvePlan({ firm = 'lucid', plan = 'flex', size = '50k', dll = true, overrides = {} } = {}) {
  const f = FIRMS[firm] || FIRMS.lucid
  const p = f.plans[plan] || Object.values(f.plans)[0]
  const sizes = f.sizes || SIZES
  const offered = sizesFor(f.id, p.id)
  const pickSize = offered.find((s) => s.id === size) || offered.find((s) => s.id === '50k') || offered[0]
  const si = sizes.indexOf(pickSize)
  const start = pickSize.balance
  const fu = p.funded
  // A plan sold only with its daily limit (MFP Select / Prime / Signature) ignores the toggle.
  const withDll = p.dllOptional === false ? true : Boolean(dll)

  const base = {
    firm: f.id,
    firmLabel: f.label,
    instrument: f.instrument || 'futures',
    plan: p.id,
    planLabel: p.label,
    size: pickSize.id,
    sizeLabel: pickSize.label,
    dll: withDll,
    dllOptional: p.dllOptional !== false,
    startBalance: start,
    price: withDll ? p.price[si] : p.priceNoDll[si],
    activationFee: p.activationFee[si],
    maxLoss: p.maxLoss[si],
    lockOffset: f.lockOffset,
    maxMinis: p.maxMinis[si],
    dailyLossLimit: withDll ? p.dailyLossLimit[si] : null,
    dllMode: p.dllMode || 'flatten',
    dayBoundary: p.dayBoundary || 'globex',
    flatByEt: f.flatByEt,
    boosted: Boolean(p.boosted),
    hasEval: Boolean(p.eval),
    profitTarget: p.eval ? p.eval.profitTarget[si] : 0,
    evalConsistency: p.eval ? p.eval.consistency : 0,
    evalMinDays: p.eval ? p.eval.minDays : 0,
    evalDrawdown: p.eval?.drawdown || 'eod',
    passIntrabar: Boolean(p.eval?.passIntrabar),
    evalInactivityDays: p.inactivity?.eval || 0,
    fundedDrawdown: fu.drawdown,
    lockOnPayout: fu.lockOnPayout !== false,
    fundedConsistency: fu.consistency,
    fundedMinDays: fu.minDays,
    fundedInactivityDays: p.inactivity?.funded || 0,
    minProfitDays: fu.minProfitDays,
    minDayProfit: fu.minDayProfit[si],
    profitGoal: asList(fu.profitGoal[si]),
    buffer: fu.buffer[si],
    payoutFraction: fu.payoutFraction,
    payoutFrom: fu.payoutFrom || 'start',
    payoutCap: asList(fu.payoutCap[si]),
    minPayout: fu.minPayout?.[si] ?? f.minPayout,
    split: f.split,
    maxPayouts: fu.maxPayouts,
    lifetimeCap: p.lifetimeCap || null,
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

/** Account sizes a plan sells, in display order. */
export function sizesFor(firm = 'lucid', plan) {
  const f = FIRMS[firm] || FIRMS.lucid
  const p = f.plans[plan] || Object.values(f.plans)[0]
  const sizes = f.sizes || SIZES
  return p.sizes ? sizes.filter((s) => p.sizes.includes(s.id)) : sizes
}

/** Value for payout number `k` (0-based) from a per-payout list. */
export function nth(list, k) {
  if (!list || !list.length) return null
  return list[Math.min(k, list.length - 1)]
}
