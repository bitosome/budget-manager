# Changelog

## 0.16.2 — 2026-11-03

- Refresh date-dependent sensors at midnight on the Home Assistant event loop. The day-change listener was a plain function, so Home Assistant ran it in a worker thread and logged "calls async_write_ha_state from a thread other than the event loop" at each day change. Entity update listeners are now marked as event-loop callbacks.

Budget calculations, records and the panel are unchanged.

## 0.16.1 — 2026-11-03

- Bundle shared UI 1.5.0. Past months and Edit values keep their label centred when they are off instead of reserving an invisible check mark on the right; they keep the same width when switched on.
- Leave out the Savings group heading in the plan table when the only savings row is Savings itself, so there is no empty row above it. A second savings item brings the heading back.

Budget calculations, records and backend actions are unchanged.

## 0.16.0 — 2026-11-03

- Adopt shared UI 1.4.0. Buttons, notices, chips and selected pills now use the shared family styles, so the panel no longer mixes three destructive button looks or differently tinted warnings. Past months and Edit values in the plan table are now pressed toggles with a check mark instead of labels that switch text.
- Show what each daily-allowance colour means: plan-table cells and the per-day tile now read On track, Tight or Over. Tight uses the shared amber caution colour.
- Show saving progress on the button that started it, with one pending message instead of two. Paid/received checkboxes show a spinner while their change is saved and keep keyboard focus; a second tap while a change is saving is ignored instead of showing an error.
- Put single delete and reset confirmations in an equal two-button footer with Cancel focused first. Delete month uses the same layout.
- Keep error messages on screen until dismissed, with a Refresh action, instead of a red toast that disappears after five seconds. Loading failures offer Try again.
- Format money with the Home Assistant profile language, matching dates.
- Use the shared 44px icon buttons for Refresh, year arrows, edit and drag handles, with the accent focus ring. Plan month headers are 44px tall, input focus uses the accent colour and hover lifts no longer stick on touch screens. Reduced-motion users get instant scrolling in the care-leave editor.

Budget calculations, thresholds, records and backend actions are unchanged.

## 0.15.3

- Keep status glows behind the full month view, including the adjacent income and expense panels, while preserving the halo between tiles.
- Adopt shared UI 1.0.1, which keeps notice surfaces above neighboring activation glows.
- Add synthetic glow-on/off and simultaneous-glow preview variants for visual regression checks.

Budget calculations, records, and payment controls are unchanged.

## 0.15.2

- Use the shared settings, history and edit icons, including a compact pencil for the editable balance.
- Announce settings and record editors as dialog launchers while preserving the shared Back/X flow and retained drafts.
- Keep the compact month tiles and normal-sized payment checkboxes from 0.15.1. Financial calculations and records are unchanged.

## 0.15.1

- Show paid/received checkboxes at a regular 22px visual size while retaining a 44px touch target and keyboard focus feedback.
- Make month-summary tiles fit their labels and values instead of enforcing 100px height; preserve equal row heights, wrapping and shared status glows.

Budget calculations, payment state actions and stored records are unchanged.

## 0.15.0

- Use the shared `@bitosome/ha-card-ui` 1.0.0 package for native dialogs, navigation, accessibility, theme tokens and calm status glows.
- Keep parent form drafts when opening nested electricity settings and history. Back returns one level; the X closes the complete flow with an unsaved-changes check.
- Keep long forms inside a safe-area-aware scrolling dialog with fixed reachable header and footer actions.
- Serialize budget writes, show pending/error feedback, prevent duplicate submissions and prevent late responses from closing newer editors.
- Require an explicit choice for recurring-item deletion and saving. Canceling either flow makes no change.
- Preserve dated electricity fees while controls are disabled during Save, and capture the original month for editors.
- Align compact metric tiles, buttons, field sizes, focus rings and light/dark colors with the other Home Assistant cards. Settings remain available on small screens.
- Add synthetic preview fixtures, modal lifecycle regression checks and reproducible release CI.

Financial calculations, storage/export formats, existing records and backend actions are unchanged. Reload Budget Manager after installing this frontend-only update, then reopen its sidebar panel. A Home Assistant restart remains a fallback if the panel registration does not refresh.
