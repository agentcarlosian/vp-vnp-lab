/-
  Blueprint 1 — Human-Audited TCB Specification (`Statement.lean`)
  ERC-4626 Share Vault & Constant-Product AMM (Uniswap v2) Solvency + Floor-Rounding Safety
-/

namespace DeFi

/-- Constant-product AMM liquidity pool `(reserveX, reserveY)`. -/
structure PoolState where
  reserveX : Nat
  reserveY : Nat
  deriving Repr, DecidableEq

/-- Floor-rounded constant-product swap output: `dy = floor(y * dx / (x + dx))`. -/
def ammAmountOut (x y dx : Nat) : Nat :=
  (y * dx) / (x + dx)

/-- Execute a swap of `dx` tokens of X for `dy` tokens of Y. -/
def ammSwapXForY (p : PoolState) (dx : Nat) : PoolState × Nat :=
  let dy := ammAmountOut p.reserveX p.reserveY dx
  ({ reserveX := p.reserveX + dx, reserveY := p.reserveY - dy }, dy)

/-- Constant-product invariant `k = reserveX * reserveY`. -/
def poolK (p : PoolState) : Nat :=
  p.reserveX * p.reserveY

/-- ERC-4626 Vault state `(totalAssets, totalShares)`. -/
structure VaultState where
  totalAssets : Nat
  totalShares : Nat
  deriving Repr, DecidableEq

/-- ERC-4626 protocol-favorable floor-rounded deposit share minting. -/
def previewDeposit (v : VaultState) (assets : Nat) : Nat :=
  if v.totalAssets == 0 || v.totalShares == 0 then assets
  else (assets * v.totalShares) / v.totalAssets

/-- ERC-4626 protocol-favorable floor-rounded share redemption. -/
def previewRedeem (v : VaultState) (shares : Nat) : Nat :=
  if v.totalShares == 0 then 0
  else (shares * v.totalAssets) / v.totalShares

/-- Execute an ERC-4626 deposit returning `(nextVault, mintedShares)`. -/
def vaultDeposit (v : VaultState) (assets : Nat) : VaultState × Nat :=
  let minted := previewDeposit v assets
  ({ totalAssets := v.totalAssets + assets, totalShares := v.totalShares + minted }, minted)

/-- Execute an ERC-4626 redemption returning `(nextVault, assetsOut)`. -/
def vaultRedeem (v : VaultState) (shares : Nat) : VaultState × Nat :=
  let out := previewRedeem v shares
  ({ totalAssets := v.totalAssets - out, totalShares := v.totalShares - shares }, out)

end DeFi
