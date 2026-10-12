"""Purged walk-forward readouts. Frozen fold schedules survive prefix probes."""
from bisect import insort
from collections import deque
import hashlib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from build_dataset import compute_target, TARGET_COL
from eval import session_folds
from . import config


def fold_schedule(df, horizon):
    target = compute_target(df, horizon)
    folds = session_folds(target, n_splits=config.WF_SPLITS, embargo_sessions=config.EMBARGO_SESSIONS)
    return [{'train_end': df.date.iloc[tr[-1]].isoformat(), 'start': df.date.iloc[te[0]].isoformat(),
             'end': df.date.iloc[te[-1]].isoformat()} for tr, te in folds]


def fold_indices(df, params):
    target = compute_target(df, params['horizon_bars'])
    schedule = df.attrs.get('fold_schedule') or fold_schedule(df, params['horizon_bars'])
    folds = []
    for f in schedule:
        train = np.flatnonzero(((df.date <= pd.Timestamp(f['train_end'])) &
            (target.target_time < pd.Timestamp(f['start'])) & target[TARGET_COL].notna()).to_numpy())
        test = np.flatnonzero(((df.date >= pd.Timestamp(f['start'])) & (df.date <= pd.Timestamp(f['end']))).to_numpy())
        if len(test):
            folds.append((train, test))
    return target, folds


def fit_ridge(X, y, params):
    model = Ridge(alpha=params['ridge_lambda'], solver='lsqr', tol=1e-6).fit(X, y)
    threshold = float(np.quantile(np.abs(model.predict(X)), params['threshold_q']))
    return model, threshold


def signals_from_predictions(pred, threshold):
    return np.where(pred > threshold, 1, np.where(pred < -threshold, -1, 0)).astype(np.int8)


def dan_path(df, X, params, initial=None, frozen=None, stats=None):
    """Reward arrives only at an actual next-open trade's closing bar.

    Seeded small initial weights break the zero-weight/no-trade fixed point.
    The reward is signed ETF points divided by entry ATR. No future target is used.
    Reinforcement strengthens the association between the entry pattern and the action
    taken, so the update is lr * side * pattern * reward: a winning short pushes w.s
    further negative and a losing long weakens w.s, with no side-dependent asymmetry.

    Optional loss-averse behaviour, all off by default (the defaults reproduce the neutral path exactly):
    `loss_aversion` multiplies negative rewards in the weight update; `caution` scales the entry threshold by
    1 + caution * (drawdown over the last RISK_WINDOW closed trades, in ATR units per trade); `cooldown_bars` blocks entries for that many bars after two
    consecutive losing trades. Only realised, already-closed trades feed the risk state, so it is causal.
    `frozen=(w, threshold)` replays the gate with fixed weights and threshold and no learning.

    Optional learning-signal options, also off by default:
    `shadow=True` places a costless paper bet on every non-closing bar i. It enters at bar i+1's open and is graded
    with the real-trade hold rule (H bars or session close) before that bar's prediction, so the fly gets feedback on
    every bar instead of only on trades it takes. Real trades then feed only the risk state, not the weights.
    `dan_rule='delta'` learns from prediction error (normalized LMS / Rescorla-Wagner):
    w += lr * pattern * (outcome - pattern.w) / |pattern|^2, where outcome is the side-free move in ATR units.
    The hebbian rule's side * reward is the same side-free move, so it cannot tell a wrong bet from a right one.
    Pass a dict as `stats` to receive paper-bet hit rate and error, overall and per half of the path.
    """
    aversion = params.get('loss_aversion', 1.0)
    caution = params.get('caution', 0.0)
    cooldown = params.get('cooldown_bars', 0)
    shadow = bool(params.get('shadow', False))
    rule = params.get('dan_rule', 'hebbian')
    if rule not in ('hebbian', 'delta'):
        raise ValueError(f'Unknown dan_rule: {rule}')
    if aversion != 1.0 and (shadow or rule == 'delta'):
        raise ValueError('loss_aversion needs a signed trade reward; it is undefined for paper bets and the delta rule')

    def learn(w, pattern, outcome):
        if rule == 'delta':
            err = outcome - pattern @ w
            return (1 - config.DAN_DECAY) * w + params['dan_lr'] * pattern * err / (1e-8 + pattern @ pattern)
        return (1 - config.DAN_DECAY) * w + params['dan_lr'] * pattern * outcome

    if frozen is not None:
        w = np.asarray(frozen[0], dtype=float).copy()
    else:
        w = np.random.default_rng(params['seed']).normal(0, 1e-4, X.shape[1]) if initial is None else initial.copy()
    recent = deque(maxlen=config.RISK_WINDOW)
    drawdown = 0.
    losing_streak = 0
    blocked_until = -1
    predictions = np.zeros(len(df)); signal = np.zeros(len(df), dtype=np.int8)
    position = None
    pending = 0
    close = df.close.to_numpy(); op = df.open.to_numpy(); sid = df.session.to_numpy()
    atr = df.atr_14.to_numpy() if 'atr_14' in df else np.ones(len(df))
    history = []
    ends = df.session_end.to_numpy(bool) if 'session_end' in df else np.r_[sid[:-1] != sid[1:], True]
    paper = deque()  # (signal bar, pattern, scale, prediction at signal time), oldest first
    graded = []  # (prediction at signal time, outcome)
    for i in range(len(df)):
        end = bool(ends[i])
        if pending and i and sid[i] == sid[i - 1]:
            position = (i, op[i], pending, X[i - 1].copy(), max(float(atr[i - 1]), 1e-8))
        pending = 0
        # Paper bets queued within this session; each entered at its signal bar + 1, so i > signal bar.
        while paper and (i - paper[0][0] >= params['horizon_bars'] or end):
            bar, pattern, scale, guess = paper.popleft()
            outcome = (close[i] - op[bar + 1]) / scale
            w = learn(w, pattern, outcome)
            graded.append((guess, outcome))
        if position is not None:
            entry, price, side, pattern, scale = position
            if i - entry + 1 >= params['horizon_bars'] or end:
                reward = side * (close[i] - price) / scale
                if frozen is None and not shadow:
                    felt = reward * aversion if reward < 0 else reward
                    w = learn(w, pattern, side * felt)
                recent.append(reward)
                curve = np.cumsum(recent)
                drawdown = float(max(0., curve.max()) - curve[-1])
                losing_streak = losing_streak + 1 if reward < 0 else 0
                if cooldown and losing_streak >= 2:
                    blocked_until = i + cooldown
                position = None
        predictions[i] = X[i] @ w
        if shadow and frozen is None and not end:
            paper.append((i, X[i], max(float(atr[i]), 1e-8), predictions[i]))
        if frozen is not None:
            thr = frozen[1]
        elif history:
            q = (len(history) - 1) * params['threshold_q']
            lo = int(q); hi = min(lo + 1, len(history) - 1)
            thr = history[lo] + (q - lo) * (history[hi] - history[lo])
        else:
            thr = 0.
        action = int(signals_from_predictions(predictions[i], thr * (1 + caution * drawdown / config.RISK_WINDOW)))
        if i < blocked_until:
            action = 0
        signal[i] = action
        if position is None and not end:
            pending = action
        if frozen is None:
            insort(history, abs(predictions[i]))
    if stats is not None:
        stats.update(paper_bet_stats(graded))
    return predictions, signal, w


def paper_bet_stats(graded):
    """Is the fly getting less wrong? Sign hit rate and |outcome - prediction|, overall and per half of the path."""
    def summary(rows):
        rows = np.asarray(rows, dtype=float).reshape(-1, 2)
        called = rows[(rows[:, 0] != 0) & (rows[:, 1] != 0)]
        return dict(n=len(rows), hit_rate=float(np.mean(np.sign(called[:, 0]) == np.sign(called[:, 1]))) if len(called) else None,
                    mean_abs_err=float(np.mean(np.abs(rows[:, 1] - rows[:, 0]))) if len(rows) else None)
    half = len(graded) // 2
    return dict(summary(graded), first_half=summary(graded[:half]), second_half=summary(graded[half:]))


def oos_signals(df, states, params, diagnostics=None, model_cache=None):
    X = np.asarray(states[params['readout_from']])
    target, folds = fold_indices(df, params)
    signal = np.zeros(len(df), dtype=np.int8)
    fold_id = np.full(len(df), -1, dtype=int)
    if params['readout'] == 'dan':
        learning = {} if diagnostics is not None and params.get('shadow') else None
        _, all_signals, _ = dan_path(df, X, params, stats=learning)
        if learning is not None:
            diagnostics.append(dict(learning=learning))
        for k, (_, te) in enumerate(folds):
            signal[te], fold_id[te] = all_signals[te], k
        return signal, fold_id
    for k, (tr, te) in enumerate(folds):
        if not len(tr):
            continue
        train_X = np.ascontiguousarray(X[tr], dtype=float)
        train_y = np.ascontiguousarray(target[TARGET_COL].to_numpy()[tr], dtype=float)
        digest = hashlib.sha256(train_X.tobytes() + train_y.tobytes()).hexdigest()
        key = (train_X.shape, digest, params['ridge_lambda'], params['threshold_q'])
        if model_cache is not None and key in model_cache:
            model, thr = model_cache[key]
        else:
            model, thr = fit_ridge(X[tr], target[TARGET_COL].to_numpy()[tr], params)
            if model_cache is not None:
                model_cache[key] = (model, thr)
        signal[te] = signals_from_predictions(model.predict(X[te]), thr)
        fold_id[te] = k
        if diagnostics is not None:
            diagnostics.append(dict(threshold=thr, train=tr, test=te))
    return signal, fold_id


def fit_frozen(df, states, params):
    X = np.asarray(states[params['readout_from']])
    if params['readout'] == 'dan':
        _, _, w = dan_path(df, X, params)
        return dict(coef=w, intercept=0., threshold=float(np.quantile(abs(X @ w), params['threshold_q'])))
    target = compute_target(df, params['horizon_bars'])
    valid = target[TARGET_COL].notna().to_numpy()
    model, thr = fit_ridge(X[valid], target[TARGET_COL].to_numpy()[valid], params)
    return dict(coef=model.coef_, intercept=float(model.intercept_), threshold=thr)


def frozen_signals(states, params, fitted, df=None):
    if params.get('readout') == 'dan' and (params.get('caution', 0) or params.get('cooldown_bars', 0)):
        if df is None:
            raise ValueError('A risk-gated DAN readout needs the bar frame to replay its drawdown state')
        return dan_path(df, np.asarray(states[params['readout_from']]), params,
                        frozen=(fitted['coef'], fitted['threshold']))[1]
    pred = np.asarray(states[params['readout_from']]) @ np.asarray(fitted['coef']) + fitted['intercept']
    return signals_from_predictions(pred, fitted['threshold'])
