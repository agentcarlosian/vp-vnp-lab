"""Production Python ERC-4626 Vault + Constant-Product AMM (reference target for Blueprint 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class AmmPool:
    reserve_x: int
    reserve_y: int

    def pool_k(self) -> int:
        return self.reserve_x * self.reserve_y

    def swap_x_for_y(self, dx: int) -> int:
        dy = (self.reserve_y * dx) // (self.reserve_x + dx) if (self.reserve_x + dx) > 0 else 0
        self.reserve_x += dx
        self.reserve_y -= dy
        return dy


@dataclass
class Erc4626Vault:
    total_assets: int
    total_shares: int

    def preview_deposit(self, assets: int) -> int:
        if self.total_assets == 0 or self.total_shares == 0:
            return assets
        return (assets * self.total_shares) // self.total_assets

    def preview_redeem(self, shares: int) -> int:
        if self.total_shares == 0:
            return 0
        return (shares * self.total_assets) // self.total_shares

    def deposit(self, assets: int) -> int:
        minted = self.preview_deposit(assets)
        self.total_assets += assets
        self.total_shares += minted
        return minted

    def redeem(self, shares: int) -> int:
        out = self.preview_redeem(shares)
        self.total_assets -= out
        self.total_shares -= shares
        return out
