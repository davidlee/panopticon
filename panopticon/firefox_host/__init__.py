"""Firefox WebExtension native messaging host.

Reads length-prefixed JSON messages from stdin (the WebExtension
``runtime.connectNative`` protocol), validates and redacts each event,
and writes it through :class:`panopticon.store.RawStore` to
``raw/firefox-YYYY-MM-DD.jsonl``.

The extension is the producer; this host is the bridge. Source field is
always re-stamped to ``"firefox"`` so a misbehaving extension cannot lie
about provenance.
"""
