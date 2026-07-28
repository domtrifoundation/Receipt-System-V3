## Summary
<!-- What's being added to the TUI, menu data or custom screen -->

## Full guide
See [`docs/templates/new_menu_item.md`](../../docs/templates/new_menu_item.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] Confirmed this reduces to "a list of labeled actions" and used menu data — or explicitly justified why not
- [ ] `MenuItemSpec`'s target API call is a real, currently-registered RPC
- [ ] Tooltip and `docs_ref` are real, not placeholders
- [ ] If a custom screen: built on Textual's widget system directly, justification stated for the exception-list addition
- [ ] If a custom screen introduces its own new state/contract: dict-typed fields use `FrozenDict`
