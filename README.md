# Budget Manager for Home Assistant

Budget Manager is a local-first Home Assistant custom integration for planning income, expenditures, savings, and daily spending.

Repository: <https://github.com/bitosome/budget-manager>

It provides a full-screen sidebar application, Home Assistant entities, payment-calendar events, and automation actions. Budget data stays inside Home Assistant's versioned `.storage` area and is included in normal Home Assistant backups.

## Features

- Full 12-month overview for any year.
- Grouped 24-month planning matrix showing the selected year followed by the next year, with explicit year headers.
- A per-device **Hide past months** toggle shortens the plan table to the current month and future months without removing any budget data.
- A visible toggle in the plan table's `Item` header pins or unpins the first column per device; mobile defaults to unpinned for easier horizontal scrolling.
- Optional inline plan-table editing for amounts. New cells create one-time items with default properties and are highlighted as requiring review in the month view until their details are saved.
- Detailed month view with expected income, expenditures, manual account balance, remaining forecast, and automatic EUR/day calculation.
- The **Budget** sidebar opens the active budget cycle: with the default cycle end on the 2nd, the previous month remains active through the 2nd and the new month opens on the 3rd.
- Advanced Estonian hourly income converts hourly gross pay and that month's working-time fund into estimated net income, including configurable tax-free income, unemployment insurance, social-tax minimum, and 0/2/4/6% funded pension options.
- Mobile includes a menu button that opens Home Assistant's native sidebar for switching panels.
- Add, edit, and delete income, expenditures, and savings.
- One-time, monthly, and yearly items.
- Required end date for recurring items.
- Edit/delete one occurrence or the current-and-future unpaid series.
- Mark expenses paid and income received without automatically changing the manual account balance.
- Create a blank month or copy any specific month.
- Create a blank 12-month year or copy any specific year.
- Renewal/special-month highlighting.
- Configurable budget-cycle end day (the 2nd of the following month by default).
- Independently configurable per-day RAG colors (green from €45/day and yellow from €40/day by default).
- Fixed or automatic savings with its own target and floor (default €45–€40/day). The planned savings amount is preserved inside that range, then adjusted only enough to return to it.
- Native Home Assistant summary sensors, account-balance number entity, calendar, and actions.
- Empty, zero-input installation with no bundled household or financial data.
- Versioned JSON import and export from the Budget panel for backups and moving data between installations.

## Calculation

For each month:

```text
forecast remaining = manual account balance
                   + expected income not yet received
                   - expenditures not yet paid
                   - open fixed savings
                   - calculated automatic savings

EUR/day = forecast remaining / relevant days
```

The day divisor is the smaller of the number of days in the budget month and the inclusive number of days until its cycle end. By default, a budget month runs through the 2nd of the following calendar month; this day is configurable in Settings.

Marking an item paid or received only changes its status. It does not change the account balance, which remains a deliberate manual input.

Automatic savings starts from the configured monthly amount. Its target and floor are separate from the RAG color thresholds. It stays unchanged inside its acceptable daily-money range and is clamped to the nearest boundary outside it:

```text
minimum savings = max(0, money before savings - savings target × relevant days)
maximum savings = max(0, money before savings - savings floor × relevant days)
automatic savings = clamp(planned savings, minimum savings, maximum savings)
```

When an automatic savings item is marked paid/transferred, its calculated amount is frozen on that occurrence and it stops reducing the daily allowance. Update the account balance manually after the transfer, as with any other real account movement.

### Estonian hourly income

For an income item, enable **Calculate monthly net income from an hourly gross rate**. Automatic working hours use an eight-hour Monday–Friday schedule, remove Estonian public holidays, and apply the three-hour reductions before New Year's Day, Independence Day, Victory Day, and Christmas Eve. Recurring income is recalculated separately for every month; for example, August 2026 has 20 working days and 160 working hours.

Holiday dates are requested on demand from the public [Nager.Date API](https://date.nager.at/Api). Only the year and Estonia country code are sent. No item names, rates, balances, or other budget data leave Home Assistant. If the API is unavailable, Budget Manager calculates the statutory Estonian holidays locally.

The built-in payroll defaults follow the Estonian Tax and Customs Board's published 2026 rates: 22% income tax, €700 monthly basic exemption, 33% social tax with an €886 minimum base, 1.6% employee and 0.8% employer unemployment insurance, and optional 2/4/6% funded pension. Future months continue using the latest built-in rates until the integration is updated. The result is a planning estimate, not payroll or tax advice.

## Installation

### Manual

1. Copy `custom_components/budget_manager` to `<home-assistant-config>/custom_components/budget_manager`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**.
4. Search for **Budget Manager** and add it. No setup values are required.
5. Open **Budget** in the sidebar. Create a month/year or import an existing Budget Manager JSON file from **Settings**.

### HACS custom repository

Add `https://github.com/bitosome/budget-manager` to HACS as an **Integration**, install it, restart Home Assistant, and add **Budget Manager** from Devices & services.

## Home Assistant entities

- `sensor.budget_manager_daily_allowance`
- `sensor.budget_manager_forecast_remaining`
- `sensor.budget_manager_unpaid_expenses`
- `sensor.budget_manager_expected_income`
- `sensor.budget_manager_planned_savings`
- `number.budget_manager_account_balance`
- `calendar.budget_manager_budget_payments`

Entity IDs may receive a numeric suffix when an entity with the same ID already exists.

The cycle-end day, RAG colors, and automatic-savings limits can be changed from the Budget panel or from **Settings → Devices & services → Budget Manager → Configure**. RAG status is communicated by the color of daily-money pills and cells rather than repeated threshold text in the month and plan views.

## Import and export

Open **Budget → Settings** to export or import a JSON file. An export contains all months, items, statuses, balances, cycle dates, and calculation settings. Import validates the file completely before replacing the current budget; an invalid file leaves existing data unchanged.

The portable format is identified by `"format": "budget-manager"` and a numeric `version`. Files should be treated as private because their contents may include household financial data.

## Actions

- `budget_manager.set_balance`
- `budget_manager.mark_item`
- `budget_manager.copy_month`
- `budget_manager.copy_year`

The sidebar panel is the primary CRUD interface. Actions are intended for automations, scripts, and voice-assistant workflows.

## Copy semantics

Copying a month or year:

- Copies names, amounts, due days, categories, item notes, and special/renewal markers.
- Recalculates copied Estonian hourly income using the target month's working hours.
- Resets account balances.
- Resets paid/received/skipped items to pending.
- Assigns fresh occurrence IDs.
- Uses the global cycle-end setting and shifts recurrence-end dates relative to the target period.
- Preserves series linkage inside a copied year without linking the copy to the source year's history.

When creating a year without **Overwrite**, existing target months are preserved and only missing months are filled. This makes it safe to complete a partially planned year. Enabling **Overwrite** replaces all 12 target months.

## Development verification

The pure calculation and period-copy model is covered by standard-library unit tests:

```bash
python3 -m unittest discover -s tests -v
node --check custom_components/budget_manager/frontend/budget-manager-panel.js
python3 -m compileall -q custom_components tests
```

Integration runtime testing requires a current Home Assistant development or test instance.
