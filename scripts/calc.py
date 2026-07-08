"""
Veda — arithmetic helpers.

LLMs must NOT perform arithmetic on Veda outputs (see SKILL.md Hard Rule #8).
All numeric fields in the decision block — expected value, p_loss, p_loss_pct,
PEG, Kelly sizing, FX conversion, probability-sum validation — must be produced
by this script. Paste the output verbatim into the decision block.

This module is pure stdlib, deterministic, and dependency-free.

Examples (from a terminal in the Veda-advisor folder):

    python scripts/calc.py ev --probs 0.35 0.40 0.25 --returns 60 15 -35
    python scripts/calc.py p_loss --probs 0.35 0.40 0.25 --returns 60 15 -35
    python scripts/calc.py kelly --p-win 0.6 --odds 1
    python scripts/calc.py peg --pe 32.1 --growth 78
    python scripts/calc.py margin-of-safety --intrinsic-low 200 --price 165
    python scripts/calc.py fx --amount 5000 --rate 83.2
    python scripts/calc.py weights-sum --weights 0.15 0.18 0.05 0.08 0.02 0.05 0.08 0.03 0.10 0.18 0.08

Or import the functions directly:

    from scripts.calc import expected_value, p_loss_pct, margin_of_safety
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import Sequence


PROB_SUM_TOLERANCE = 1e-6


def validate_probabilities(probs: Sequence[float]) -> None:
    """Raise ValueError if probabilities are out of range or do not sum to 1.0."""
    if not probs:
        raise ValueError("probabilities list is empty")
    for p in probs:
        if p < 0.0 or p > 1.0:
            raise ValueError(f"probability {p} is not in [0, 1]")
    total = math.fsum(probs)
    if abs(total - 1.0) > PROB_SUM_TOLERANCE:
        raise ValueError(
            f"probabilities sum to {total:.6f}; they must sum to 1.0 "
            f"(tolerance {PROB_SUM_TOLERANCE})"
        )


def expected_value(probs: Sequence[float], returns_pct: Sequence[float]) -> float:
    """Expected value in percent units.

    Each element of ``returns_pct`` is a percent return (e.g. +60 for +60%).
    Probabilities must sum to 1.0 on the 0.0-1.0 scale.
    """
    if len(probs) != len(returns_pct):
        raise ValueError("probs and returns_pct must be the same length")
    validate_probabilities(probs)
    return math.fsum(p * r for p, r in zip(probs, returns_pct))


def p_loss(probs: Sequence[float], returns_pct: Sequence[float]) -> float:
    """Sum of probabilities over scenarios with negative return, 0.0-1.0 scale."""
    if len(probs) != len(returns_pct):
        raise ValueError("probs and returns_pct must be the same length")
    validate_probabilities(probs)
    return math.fsum(p for p, r in zip(probs, returns_pct) if r < 0)


def p_loss_pct(probs: Sequence[float], returns_pct: Sequence[float]) -> float:
    """p_loss on a 0-100 scale, for comparison with profile.max_loss_probability."""
    return p_loss(probs, returns_pct) * 100.0


def kelly_fraction(p_win: float, odds: float) -> float:
    """Kelly-optimal fraction of bankroll to stake.

    Plain-English version
    ---------------------
    "How much of my money should I put on this bet?"

    Kelly answers that by balancing two forces:
      1. Your **edge** — how much you expect to win on average.
            edge = (payoff-if-win * probability-of-win) - probability-of-loss
            That is the ``b*p - q`` in the numerator.
            If edge is zero, don't bet. If edge is negative, definitely don't bet.
      2. The **size of each win** — bigger payoffs mean you can reach the
         optimum by staking less, because one win recovers more ground.
            Dividing by ``b`` shrinks the bet when payoffs are big.

    Two intuitive examples:
      * Coin flip paying 1:1, you win 60% of the time.
            edge = 1*0.6 - 0.4 = 0.2.  Divide by b=1.  Bet 20% of bankroll.
      * Lottery paying 2:1, you win only 40% of the time.
            edge = 2*0.4 - 0.6 = 0.2.  Same edge, but divide by b=2.  Bet 10%.
            Fewer wins but bigger ones, so Kelly says stake less.

    Why Veda uses half-Kelly by default:
      Full Kelly is only optimal if your probabilities are exactly right.
      In the real world they never are. Half-Kelly keeps ~75% of the growth
      with a fraction of the drawdowns. See ``half_kelly`` below.

    Formal formula
    --------------
        f* = (b * p - q) / b,  where
            p = probability of winning (``p_win``)
            q = probability of losing  (= 1 - p_win)
            b = net odds (payoff per unit staked on a win; ``odds``)

    Returns a **signed** fraction. Negative values mean the bet has no positive-EV
    Kelly stake; in practice this is an instruction NOT to take the bet, not to
    short it. Veda's decision pipeline should treat negative Kelly as ``wait``.
    """
    if not 0.0 <= p_win <= 1.0:
        raise ValueError(f"p_win {p_win} is not in [0, 1]")
    if odds <= 0:
        raise ValueError("odds must be positive")
    q = 1.0 - p_win
    return (odds * p_win - q) / odds


def half_kelly(p_win: float, odds: float) -> float:
    """Half-Kelly fraction. Recommended default for real-world sizing."""
    return kelly_fraction(p_win, odds) / 2.0


def peg(pe: float, growth_pct: float) -> float:
    """PEG ratio. ``growth_pct`` is the earnings growth rate in percent."""
    if growth_pct == 0:
        raise ValueError("growth_pct cannot be zero")
    return pe / growth_pct


def margin_of_safety(intrinsic_low: float, price: float) -> float:
    """Buffett / Graham margin of safety, in percent.

    Plain-English version
    ---------------------
    "How much cheaper than my conservative estimate of fair value am I
    buying this?"

    The discount is computed against the **low end** of the intrinsic-value
    range, not the midpoint. That is the Buffett / Graham discipline: size
    the cushion against the conservative case so that ordinary error and
    bad luck still leave an acceptable outcome. Using the midpoint or high
    end would let optimism creep back into the cushion itself.

    Formal formula
    --------------
        MoS (%) = (intrinsic_low - price) / intrinsic_low * 100

    Sign convention
    ---------------
    - Positive value: the price is below the conservative intrinsic
      estimate; MoS exists at the reported level.
    - Zero: price equals intrinsic_low; no cushion.
    - Negative: the price is **above** intrinsic_low, so there is no
      margin of safety at all. The function returns the negative number
      verbatim so the decision block records it honestly; Veda's
      orchestrator decides what to do with it (typically: `wait`).

    Buffett's quality-adjusted thresholds (applied by the orchestrator, not
    by this function): 10-20% MoS for wonderful businesses, 25-35% for
    good businesses, 40%+ for average businesses. See frameworks/buffett.md.

    Parameters
    ----------
    intrinsic_low : float
        Low end of the intrinsic-value range, same currency as ``price``.
        Must be strictly positive (a zero or negative intrinsic value has
        no economic meaning for MoS; division by zero is also undefined).
    price : float
        Current market price, same currency as ``intrinsic_low``. Must be
        strictly positive (a zero or negative price is a data error, not
        an opportunity; fail loudly rather than emit a wrong MoS).

    Both inputs must be user- or source-supplied per SKILL.md Hard Rule #5;
    this function does not sanity-check their magnitudes, only their signs.
    """
    if intrinsic_low <= 0:
        raise ValueError(
            f"intrinsic_low {intrinsic_low} must be > 0 (MoS is undefined otherwise)"
        )
    if price <= 0:
        raise ValueError(f"price {price} must be > 0")
    return (intrinsic_low - price) / intrinsic_low * 100.0


def fx_convert(amount: float, rate: float) -> float:
    """Currency conversion: amount * rate. Rate must be user- or source-supplied."""
    return amount * rate


def sum_weights(weights: Sequence[float]) -> float:
    """Sum of framework_weights. Informational; profile allows approximately 1.0."""
    return math.fsum(weights)


def sum_values(values: Sequence[float]) -> float:
    """Sum an arbitrary list of values (e.g. portfolio position values)."""
    return math.fsum(values)


def pct_of(part: float, whole: float) -> float:
    """Return (part / whole) * 100. Used for position weights, drawdowns, etc."""
    if whole == 0:
        raise ValueError("whole cannot be zero")
    return (part / whole) * 100.0


def iron_condor(
    short_put: float,
    long_put: float,
    short_call: float,
    long_call: float,
    put_credit: float,
    put_debit: float,
    call_credit: float,
    call_debit: float,
    lot_size: int,
    num_lots: int = 1,
) -> dict[str, float]:
    """Defined-risk iron-condor economics (per-unit points in, rupees out).

    Plain-English version
    ---------------------
    An iron condor SELLS one out-of-the-money put and one OTM call to collect
    premium, and BUYS a further-OTM put and call as "wings" that cap the loss.
    You keep the whole net premium if the underlying finishes between the two
    strikes you sold. Your loss is capped no matter how far it gaps, because the
    wings you bought pay you back beyond them:

        loss if it crashes = (put_wing  - net_credit) x lot   (capped)
        loss if it moons   = (call_wing - net_credit) x lot   (capped)
        keep the credit     if short_put < settlement < short_call

    All premium and strike inputs are index POINTS (per unit); rupee figures are
    points x lot_size x num_lots. Premiums must be user- or source-supplied from
    a live option chain per SKILL.md Hard Rule #5/#9 -- this function fetches
    nothing and invents no premium.

    Sign convention: credits are amounts RECEIVED (positive), debits are amounts
    PAID (positive); net_credit = (credits) - (debits).

    Raises ValueError on malformed structures (bad strike order, or a net credit
    that meets or exceeds the wider wing, which implies a risk-free arbitrage and
    is almost always a misread chain).
    """
    if not (long_put < short_put < short_call < long_call):
        raise ValueError(
            "strikes must satisfy long_put < short_put < short_call < long_call "
            f"(got {long_put}, {short_put}, {short_call}, {long_call})"
        )
    for name, v in (
        ("put_credit", put_credit),
        ("put_debit", put_debit),
        ("call_credit", call_credit),
        ("call_debit", call_debit),
    ):
        if v < 0:
            raise ValueError(f"{name} must be >= 0 (got {v})")
    if lot_size <= 0 or num_lots <= 0:
        raise ValueError("lot_size and num_lots must be positive integers")

    net_credit = (put_credit + call_credit) - (put_debit + call_debit)
    put_wing = short_put - long_put
    call_wing = long_call - short_call
    max_wing = max(put_wing, call_wing)
    if net_credit >= max_wing:
        raise ValueError(
            f"net_credit {net_credit} >= wider wing {max_wing}: implies a risk-free "
            "position, almost certainly a misread option chain -- re-check premiums"
        )

    contracts = lot_size * num_lots
    max_loss_per_unit = max_wing - net_credit
    return {
        "net_credit_per_unit": net_credit,
        "put_wing": put_wing,
        "call_wing": call_wing,
        "profit_zone_width": short_call - short_put,
        "lower_breakeven": short_put - net_credit,
        "upper_breakeven": short_call + net_credit,
        "max_profit_total": net_credit * contracts,
        "max_loss_total": max_loss_per_unit * contracts,
        "return_on_risk_pct": net_credit / max_loss_per_unit * 100.0,
    }


def credit_spread(
    width: float,
    credit: float,
    lot_size: int,
    num_lots: int = 1,
) -> dict[str, float]:
    """Defined-risk single vertical credit spread (2 legs) economics.

    Plain-English version
    ---------------------
    A credit spread SELLS one option and BUYS a cheaper, further-out option of
    the same type as a wing. You keep the net credit if the underlying stays on
    the safe side of the strike you sold; your loss is capped at the strike
    width minus the credit. This is the simplest defined-risk income structure
    (a bull put spread or a bear call spread) -- half the legs of an iron condor.

        max profit = credit               (kept if it expires safe)
        max loss   = width - credit       (capped by the bought wing)
        return on risk = max profit / max loss

    ``width`` and ``credit`` are index POINTS; rupees are points x lot_size x
    num_lots. ``credit`` must be user- or source-supplied from a live chain per
    SKILL.md Hard Rule #5/#9.

    Also returns ``breakeven_winrate_pct``: the share of trades you must win --
    if every loss were a FULL loss -- just to break even. Selling closer to the
    money RAISES return-on-risk AND LOWERS this breakeven, but the ACTUAL win
    rate falls too, because the strike is nearer the money. The market prices
    that trade-off; return-on-risk alone is not edge (frameworks/thorp.md,
    principle 4).
    """
    if width <= 0:
        raise ValueError(f"width {width} must be > 0")
    if credit <= 0:
        raise ValueError(
            f"credit {credit} must be > 0 (this is a net-credit strategy)"
        )
    if credit >= width:
        raise ValueError(
            f"credit {credit} >= width {width}: implies a risk-free position, "
            "almost certainly a misread chain -- re-check premiums"
        )
    if lot_size <= 0 or num_lots <= 0:
        raise ValueError("lot_size and num_lots must be positive integers")

    contracts = lot_size * num_lots
    max_loss_per_unit = width - credit
    return {
        "max_profit_total": credit * contracts,
        "max_loss_total": max_loss_per_unit * contracts,
        "return_on_risk_pct": credit / max_loss_per_unit * 100.0,
        "breakeven_winrate_pct": max_loss_per_unit / width * 100.0,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_ev(args: argparse.Namespace) -> int:
    ev = expected_value(args.probs, args.returns)
    pl = p_loss(args.probs, args.returns)
    print(f"expected_value_pct: {ev:+.4f}")
    print(f"p_loss:             {pl:.4f}")
    print(f"p_loss_pct:         {pl * 100:.2f}")
    return 0


def _cmd_p_loss(args: argparse.Namespace) -> int:
    pl = p_loss(args.probs, args.returns)
    print(f"p_loss:     {pl:.4f}")
    print(f"p_loss_pct: {pl * 100:.2f}")
    return 0


def _cmd_kelly(args: argparse.Namespace) -> int:
    full = kelly_fraction(args.p_win, args.odds)
    print(f"kelly_full: {full:.4f}")
    print(f"kelly_half: {full / 2:.4f}")
    return 0


def _cmd_peg(args: argparse.Namespace) -> int:
    print(f"peg: {peg(args.pe, args.growth):.4f}")
    return 0


def _cmd_margin_of_safety(args: argparse.Namespace) -> int:
    mos = margin_of_safety(args.intrinsic_low, args.price)
    print(f"margin_of_safety_pct: {mos:+.4f}")
    return 0


def _cmd_fx(args: argparse.Namespace) -> int:
    print(f"converted: {fx_convert(args.amount, args.rate):.4f}")
    return 0


def _cmd_weights_sum(args: argparse.Namespace) -> int:
    print(f"sum: {sum_weights(args.weights):.4f}")
    return 0


def _cmd_sum(args: argparse.Namespace) -> int:
    total = sum_values(args.values)
    print(f"sum: {total:.4f}")
    return 0


def _cmd_pct(args: argparse.Namespace) -> int:
    print(f"pct: {pct_of(args.part, args.whole):.4f}")
    return 0


def _cmd_iron_condor(args: argparse.Namespace) -> int:
    r = iron_condor(
        short_put=args.short_put,
        long_put=args.long_put,
        short_call=args.short_call,
        long_call=args.long_call,
        put_credit=args.put_credit,
        put_debit=args.put_debit,
        call_credit=args.call_credit,
        call_debit=args.call_debit,
        lot_size=args.lot_size,
        num_lots=args.num_lots,
    )
    print(f"net_credit_per_unit: {r['net_credit_per_unit']:.2f}")
    print(f"profit_zone:         {args.short_put:.0f} - {args.short_call:.0f} (width {r['profit_zone_width']:.0f})")
    print(f"lower_breakeven:     {r['lower_breakeven']:.2f}")
    print(f"upper_breakeven:     {r['upper_breakeven']:.2f}")
    print(f"max_profit_total:    {r['max_profit_total']:.2f}")
    print(f"max_loss_total:      {r['max_loss_total']:.2f}")
    print(f"return_on_risk_pct:  {r['return_on_risk_pct']:.2f}")
    return 0


def _cmd_credit_spread(args: argparse.Namespace) -> int:
    r = credit_spread(
        width=args.width,
        credit=args.credit,
        lot_size=args.lot_size,
        num_lots=args.num_lots,
    )
    print(f"max_profit_total:      {r['max_profit_total']:.2f}")
    print(f"max_loss_total:        {r['max_loss_total']:.2f}")
    print(f"return_on_risk_pct:    {r['return_on_risk_pct']:.2f}")
    print(f"breakeven_winrate_pct: {r['breakeven_winrate_pct']:.2f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Veda arithmetic helpers.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ev = sub.add_parser("ev", help="expected value and p_loss for a scenario set")
    p_ev.add_argument("--probs", type=float, nargs="+", required=True)
    p_ev.add_argument(
        "--returns", type=float, nargs="+", required=True, help="returns in percent"
    )
    p_ev.set_defaults(func=_cmd_ev)

    p_pl = sub.add_parser("p_loss", help="p_loss for a scenario set")
    p_pl.add_argument("--probs", type=float, nargs="+", required=True)
    p_pl.add_argument("--returns", type=float, nargs="+", required=True)
    p_pl.set_defaults(func=_cmd_p_loss)

    p_k = sub.add_parser("kelly", help="Kelly and half-Kelly fractions")
    p_k.add_argument(
        "--p-win",
        dest="p_win",
        type=float,
        required=True,
        help="probability of winning (0.0 - 1.0)",
    )
    p_k.add_argument(
        "--odds",
        type=float,
        required=True,
        help="net odds b (payoff per unit staked on a win)",
    )
    p_k.set_defaults(func=_cmd_kelly)

    p_peg = sub.add_parser("peg", help="PEG ratio")
    p_peg.add_argument("--pe", type=float, required=True)
    p_peg.add_argument(
        "--growth", type=float, required=True, help="growth rate in percent"
    )
    p_peg.set_defaults(func=_cmd_peg)

    p_mos = sub.add_parser(
        "margin-of-safety",
        help="Buffett/Graham margin of safety (percent) vs. conservative intrinsic-value low",
    )
    p_mos.add_argument(
        "--intrinsic-low",
        dest="intrinsic_low",
        type=float,
        required=True,
        help="low end of the intrinsic-value range (same currency as --price)",
    )
    p_mos.add_argument(
        "--price",
        type=float,
        required=True,
        help="current market price (same currency as --intrinsic-low)",
    )
    p_mos.set_defaults(func=_cmd_margin_of_safety)

    p_fx = sub.add_parser("fx", help="currency conversion")
    p_fx.add_argument("--amount", type=float, required=True)
    p_fx.add_argument("--rate", type=float, required=True)
    p_fx.set_defaults(func=_cmd_fx)

    p_ws = sub.add_parser("weights-sum", help="sum of framework_weights")
    p_ws.add_argument("--weights", type=float, nargs="+", required=True)
    p_ws.set_defaults(func=_cmd_weights_sum)

    p_s = sub.add_parser("sum", help="sum a list of values (e.g. portfolio position values)")
    p_s.add_argument("--values", type=float, nargs="+", required=True)
    p_s.set_defaults(func=_cmd_sum)

    p_pct = sub.add_parser("pct", help="(part / whole) * 100 for position weights")
    p_pct.add_argument("--part", type=float, required=True)
    p_pct.add_argument("--whole", type=float, required=True)
    p_pct.set_defaults(func=_cmd_pct)

    p_ic = sub.add_parser(
        "iron-condor",
        help="defined-risk iron condor economics (index points in, rupees out)",
    )
    p_ic.add_argument("--short-put", dest="short_put", type=float, required=True)
    p_ic.add_argument("--long-put", dest="long_put", type=float, required=True)
    p_ic.add_argument("--short-call", dest="short_call", type=float, required=True)
    p_ic.add_argument("--long-call", dest="long_call", type=float, required=True)
    p_ic.add_argument("--put-credit", dest="put_credit", type=float, required=True,
                      help="premium RECEIVED for the short put (points)")
    p_ic.add_argument("--put-debit", dest="put_debit", type=float, required=True,
                      help="premium PAID for the long put wing (points)")
    p_ic.add_argument("--call-credit", dest="call_credit", type=float, required=True,
                      help="premium RECEIVED for the short call (points)")
    p_ic.add_argument("--call-debit", dest="call_debit", type=float, required=True,
                      help="premium PAID for the long call wing (points)")
    p_ic.add_argument("--lot-size", dest="lot_size", type=int, required=True,
                      help="index-option lot size (verify current NSE spec)")
    p_ic.add_argument("--num-lots", dest="num_lots", type=int, default=1)
    p_ic.set_defaults(func=_cmd_iron_condor)

    p_cs = sub.add_parser(
        "credit-spread",
        help="defined-risk single vertical credit spread (2 legs)",
    )
    p_cs.add_argument("--width", type=float, required=True,
                      help="strike width in points (short strike to long wing)")
    p_cs.add_argument("--credit", type=float, required=True,
                      help="net premium received in points (sell leg - buy leg)")
    p_cs.add_argument("--lot-size", dest="lot_size", type=int, required=True,
                      help="index-option lot size (verify current NSE spec)")
    p_cs.add_argument("--num-lots", dest="num_lots", type=int, default=1)
    p_cs.set_defaults(func=_cmd_credit_spread)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
