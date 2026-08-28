"""GTK3 window for viewing and managing dictionary entries (MCC-57).

Modeled on the "Hotkeys..." tray window (`hotkey_editor.py`): a lazily
constructed GTK window opened from the tray menu, backed directly by the
MCC-54 `DictionaryStore` for persistence.

Auto-learned entries are marked visually, but there is no review queue for
pending candidates here — nothing produces "pending" candidates yet (that's
MCC-56, deliberately deferred; see its own recommendation to wait for usage
data first). Every entry surfaced by this window is already active.
Renaming a term isn't supported (the term is the store's identity/key);
editing changes variants and the enabled flag.
"""

import contextlib
import logging
from typing import Any

from verbal_code.dictionary import DictionaryEntry, DictionaryStore

logger = logging.getLogger("verbal_code")

_AUTO_LEARNED_MARKER = "✨"  # matches Wispr Flow's indicator


def _source_label(entry: DictionaryEntry) -> str:
    if entry.source == "auto-learned":
        return f"{_AUTO_LEARNED_MARKER} auto-learned"
    return entry.source


def _format_variants(variants: list[str]) -> str:
    return ", ".join(variants)


def _parse_variants(text: str) -> list[str]:
    return [v.strip() for v in text.split(",") if v.strip()]


def _filter_entries(
    entries: list[DictionaryEntry], query: str
) -> list[DictionaryEntry]:
    """Case-insensitive substring match against a term or any of its variants."""
    query = query.strip().lower()
    if not query:
        return entries
    return [
        e
        for e in entries
        if query in e.term.lower() or any(query in v.lower() for v in e.variants)
    ]


class DictionaryEditorWindow:
    """GTK3 window listing dictionary entries with add/edit/delete/enable
    controls and a search box."""

    def __init__(self, gtk: Any, store: DictionaryStore):
        self._gtk = gtk
        self._store = store
        self._query = ""

        self._window = gtk.Window(title="Verbal Code — Dictionary")
        self._window.set_default_size(560, 420)
        self._window.set_position(gtk.WindowPosition.CENTER)

        vbox = gtk.Box(orientation=gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self._window.add(vbox)

        self._search_entry = gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search terms and variants...")
        self._search_entry.connect("search-changed", self._on_search_changed)
        vbox.pack_start(self._search_entry, False, False, 0)

        self._list_store = gtk.ListStore(str, str, str, bool)
        self._tree = gtk.TreeView(model=self._list_store)
        self._tree.set_headers_clickable(True)

        term_col = gtk.TreeViewColumn("Term", gtk.CellRendererText(), text=0)
        term_col.set_sort_column_id(0)
        self._tree.append_column(term_col)

        variants_col = gtk.TreeViewColumn("Variants", gtk.CellRendererText(), text=1)
        variants_col.set_sort_column_id(1)
        self._tree.append_column(variants_col)

        source_col = gtk.TreeViewColumn("Source", gtk.CellRendererText(), text=2)
        source_col.set_sort_column_id(2)
        self._tree.append_column(source_col)

        enabled_renderer = gtk.CellRendererToggle()
        enabled_renderer.connect("toggled", self._on_enabled_toggled)
        enabled_col = gtk.TreeViewColumn("Enabled", enabled_renderer, active=3)
        enabled_col.set_sort_column_id(3)
        self._tree.append_column(enabled_col)

        scroller = gtk.ScrolledWindow()
        scroller.set_policy(gtk.PolicyType.NEVER, gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add(self._tree)
        vbox.pack_start(scroller, True, True, 0)

        button_box = gtk.ButtonBox(orientation=gtk.Orientation.HORIZONTAL)
        button_box.set_layout(gtk.ButtonBoxStyle.END)
        button_box.set_spacing(8)

        add_btn = gtk.Button(label="Add...")
        add_btn.connect("clicked", self._on_add_clicked)
        button_box.pack_start(add_btn, False, False, 0)

        edit_btn = gtk.Button(label="Edit...")
        edit_btn.connect("clicked", self._on_edit_clicked)
        button_box.pack_start(edit_btn, False, False, 0)

        delete_btn = gtk.Button(label="Delete")
        delete_btn.connect("clicked", self._on_delete_clicked)
        button_box.pack_start(delete_btn, False, False, 0)

        close_btn = gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _w: self._window.destroy())
        button_box.pack_start(close_btn, False, False, 0)

        vbox.pack_start(button_box, False, False, 0)

        self._refresh()

    def show(self) -> None:
        self._window.show_all()

    def _refresh(self) -> None:
        self._list_store.clear()
        for entry in _filter_entries(self._store.entries, self._query):
            self._list_store.append(
                [
                    entry.term,
                    _format_variants(entry.variants),
                    _source_label(entry),
                    entry.enabled,
                ]
            )

    def _selected_term(self) -> str | None:
        model, tree_iter = self._tree.get_selection().get_selected()
        if tree_iter is None:
            return None
        return model[tree_iter][0]

    def _on_search_changed(self, widget: Any) -> None:
        self._query = widget.get_text()
        self._refresh()

    def _on_enabled_toggled(self, _renderer: Any, path: str) -> None:
        term = self._list_store[path][0]
        entry = self._store.lookup(term)
        if entry is None:
            return
        try:
            self._store.update(term, enabled=not entry.enabled)
        except KeyError:
            logger.warning("Dictionary entry %r vanished before toggle", term)
        self._refresh()

    def _on_add_clicked(self, _widget: Any) -> None:
        self._open_entry_dialog(title="Add Term")

    def _on_edit_clicked(self, _widget: Any) -> None:
        term = self._selected_term()
        if term is None:
            return
        entry = self._store.lookup(term)
        if entry is None:
            return
        self._open_entry_dialog(title="Edit Term", entry=entry)

    def _on_delete_clicked(self, _widget: Any) -> None:
        term = self._selected_term()
        if term is None:
            return
        confirm = self._gtk.MessageDialog(
            transient_for=self._window,
            flags=0,
            message_type=self._gtk.MessageType.QUESTION,
            buttons=self._gtk.ButtonsType.YES_NO,
            text=f"Delete '{term}' from the dictionary?",
        )
        response = confirm.run()
        confirm.destroy()
        if response != self._gtk.ResponseType.YES:
            return
        with contextlib.suppress(KeyError):
            self._store.delete(term)
        self._refresh()

    def _open_entry_dialog(
        self, title: str, entry: DictionaryEntry | None = None
    ) -> None:
        gtk = self._gtk
        dialog = gtk.Dialog(title=title, transient_for=self._window, flags=0)
        dialog.add_buttons(
            "Cancel", gtk.ResponseType.CANCEL, "Save", gtk.ResponseType.OK
        )

        grid = gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_margin_top(12)
        grid.set_margin_bottom(12)
        grid.set_margin_start(12)
        grid.set_margin_end(12)
        dialog.get_content_area().add(grid)

        term_entry = gtk.Entry()
        if entry is not None:
            term_entry.set_text(entry.term)
            term_entry.set_sensitive(False)  # renaming isn't supported
        grid.attach(gtk.Label(label="Term:"), 0, 0, 1, 1)
        grid.attach(term_entry, 1, 0, 1, 1)

        variants_entry = gtk.Entry()
        if entry is not None:
            variants_entry.set_text(_format_variants(entry.variants))
        grid.attach(gtk.Label(label="Variants (comma-separated):"), 0, 1, 1, 1)
        grid.attach(variants_entry, 1, 1, 1, 1)

        enabled_check = gtk.CheckButton(label="Enabled")
        enabled_check.set_active(entry.enabled if entry is not None else True)
        grid.attach(enabled_check, 1, 2, 1, 1)

        dialog.show_all()
        response = dialog.run()
        if response == gtk.ResponseType.OK:
            self._save_entry(
                entry,
                term_entry.get_text().strip(),
                _parse_variants(variants_entry.get_text()),
                enabled_check.get_active(),
            )
        dialog.destroy()
        self._refresh()

    def _save_entry(
        self,
        existing: DictionaryEntry | None,
        term: str,
        variants: list[str],
        enabled: bool,
    ) -> None:
        if not term:
            return
        try:
            if existing is None:
                self._store.add(term, variants=variants, enabled=enabled)
            else:
                self._store.update(existing.term, variants=variants, enabled=enabled)
        except (ValueError, KeyError) as exc:
            logger.error("Dictionary entry save failed: %s", exc)
