"""World builders.

Each world module exposes build(df, routing, **params) -> dict with the keys
'figures', 'stats' and 'code'. Keeping the contract identical across worlds
lets the presentation layer render any archetype through one code path.
"""
