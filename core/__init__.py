"""Framework-agnostic core for AI Data Worlds.

Nothing in this package may import streamlit. Every module takes plain inputs
(DataFrames, dicts, scalars) and returns plain outputs (dicts, DataFrames,
plotly Figures, strings) so the same code can be served from FastAPI later
without modification.
"""
