"""Broker factory: picks paper / ccxt / Alpaca from config."""

from __future__ import annotations

from ..config import Config
from .base import Broker, asset_class_of


def make_broker(cfg: Config) -> Broker:
    b = cfg["broker"]
    name = b["name"]
    if cfg.is_live:
        cfg.assert_live_allowed()
    if name == "ccxt":
        if cfg.is_live and b.get("sandbox", True):
            raise RuntimeError("mode: live with broker.sandbox: true is contradictory; set sandbox: false")
        if not cfg.is_live and not b.get("sandbox", True):
            raise RuntimeError(
                "mode: paper with a real (non-sandbox) exchange would place real orders. Use sandbox: true "
                "(exchange testnet), or broker: paper + data_source: ccxt for paper fills on real prices."
            )
        from .ccxt_broker import CCXTBroker

        return CCXTBroker(b["exchange"], sandbox=not cfg.is_live, state_path=cfg.home / "ccxt_basis.json")
    if name == "alpaca":
        from .alpaca_broker import AlpacaBroker

        return AlpacaBroker(paper=not cfg.is_live, stock_feed=b.get("stock_feed", "iex"), crypto_feed=b.get("crypto_feed", "us"))
    if name == "paper":
        if cfg.is_live:
            raise RuntimeError("mode: live needs a real broker (ccxt or alpaca), not paper")
        from .paper import PaperBroker

        data, tradable = make_data_source(cfg)
        return PaperBroker(data, cfg.home / "paper_state.json", b["starting_cash"], b["fee_bps"],
                           b["slippage_bps"], cfg["allow_short"], tradable=tradable)
    raise ValueError(f"unknown broker {name!r} (paper | ccxt | alpaca)")


def make_data_source(cfg: Config):
    """Data feed for the paper broker. Real feeds need no trading keys for ccxt (public endpoints)."""
    b = cfg["broker"]
    src = b.get("data_source", "synthetic")
    if src == "synthetic":
        from ..data import SyntheticData

        return SyntheticData(), None
    if src == "csv":
        from ..data import CSVData

        return CSVData(b["csv_dir"]), None
    if src == "ccxt":
        from .ccxt_broker import CCXTBroker

        return CCXTBroker(b["exchange"], sandbox=False), None
    if src == "alpaca":
        from .alpaca_broker import AlpacaBroker

        a = AlpacaBroker(paper=True, stock_feed=b.get("stock_feed", "iex"), crypto_feed=b.get("crypto_feed", "us"))
        return a, a
    raise ValueError(f"unknown data_source {src!r} (synthetic | csv | ccxt | alpaca)")


__all__ = ["Broker", "make_broker", "make_data_source", "asset_class_of"]
