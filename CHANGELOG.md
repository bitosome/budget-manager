# Changelog

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
