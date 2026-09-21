"""Umbriel compositor adapter — a peer of the Sway/Niri adapters behind the
neutral ``CompositorSession`` contract (SL-005). Pure snapshot projection + thin
async shell. Lighter than niri: umbriel emits a full snapshot per event, so the
projection is a *replace*, not a delta accumulator."""
