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
- Dates, month names, date ranges, and future timestamp displays follow the Home Assistant user's language, date-order, time-format, and timezone preferences; ISO values remain internal to storage and APIs.
- The **Budget** sidebar opens the active budget cycle: with the default cycle end on the 2nd, the previous month remains active through the 2nd and the new month opens on the 3rd.
- Advanced Estonian hourly income converts hourly gross pay into estimated net income using either the budget month's or previous month's working-time fund, including configurable tax-free income, unemployment insurance, social-tax minimum, and 0/2/4/6% funded pension options.
- Estonian child-care sick leave can be linked to an automatic hourly salary. Calendar periods reduce only scheduled work hours, while each period creates a separate estimated Tervisekassa income in the salary-payment month.
- Care-benefit planning can approximate the previous year's income from the linked hourly salary or use a user-entered previous-year social-taxable income total.
- Mobile includes a menu button that opens Home Assistant's native sidebar for switching panels.
- Add, edit, and delete income, expenditures, and manual savings when automatic savings is disabled.
- One-time, monthly, and yearly items.
- Required end date for recurring items.
- Edit/delete one occurrence or the current-and-future unpaid series.
- Mark expenses paid and income received without automatically changing the manual account balance.
- Optional assignment to a Home Assistant user with an active Companion App notification device. Assigned items require a due day and send targeted reminders from the chosen time every hour until completion or the end of that day, while calendar entries remain all-day events.
- Concise signed calendar titles such as `Apple iCloud -€9.99` and `Валя +€1873.24`.
- Create a blank month or copy any specific month.
- Create a blank 12-month year or copy any specific year.
- Reorder income and expenditure rows using Home Assistant-style drag handles in plan edit mode; the custom order is stored with the budget and included in JSON exports.
- Renewal/special-month highlighting.
- Configurable budget-cycle end day (the 2nd of the following month by default).
- Independently configurable per-day RAG colors (green from €45/day and yellow from €40/day by default).
- Optional global automatic savings creates one dedicated Savings transfer in every month and calculates it without manual amounts. Savings remains separate from regular expenditures.
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

When automatic savings is enabled in Settings, Budget Manager creates one system-managed Savings entry in every existing and newly created month. System-managed savings never require manual review. Its value starts from zero and takes only the money above the configured daily target:

```text
automatic savings = max(0, money before savings - savings target × relevant days)
```

The target is separate from the RAG color thresholds. If insufficient money is available, automatic savings becomes zero rather than forcing the daily amount below its existing level. Automatic Savings cannot be edited in the month or plan-table editors. When marked paid/transferred, its calculated amount is frozen on that occurrence and it stops reducing the daily allowance. Update the account balance manually after the transfer, as with any other real account movement. Reopening the transfer returns it to automatic calculation.

### Estonian hourly income

For an income item, enable **Calculate monthly net income from an hourly gross rate**. Choose whether the working hours were earned in the same calendar month as the budget or in the previous month—for example, a salary received in September can use August's working-time fund. Automatic working hours use an eight-hour Monday–Friday schedule, remove Estonian public holidays, and apply the three-hour reductions before New Year's Day, Independence Day, Victory Day, and Christmas Eve. Recurring income is recalculated separately for every month; for example, August 2026 has 20 working days and 160 working hours. When funded-pension membership is unchecked, the contribution is always calculated at 0%.

Holiday dates are requested on demand from the public [Nager.Date API](https://date.nager.at/Api). Only the year and Estonia country code are sent. No item names, rates, balances, or other budget data leave Home Assistant. If the API is unavailable, Budget Manager calculates the statutory Estonian holidays locally.

The built-in payroll defaults follow the Estonian Tax and Customs Board's published 2026 rates: 22% income tax, €700 monthly basic exemption, 33% social tax with an €886 minimum base, 1.6% employee and 0.8% employer unemployment insurance, and optional 2/4/6% funded pension. Future months continue using the latest built-in rates until the integration is updated. The result is a planning estimate, not payroll or tax advice.

### Estonian child-care sick leave

Add an expenditure and choose **Child-care sick leave**. Link it to an income that uses automatic Estonian hourly calculation for the affected work month. For a salary paid afterward, that income belongs to the following budget month and uses **The previous month** as its work period. Open the care-leave row to add, edit, or remove separate calendar periods.

For each period Budget Manager:

- deducts salary hours only for Monday–Friday scheduled workdays, excluding Estonian public holidays and respecting shortened workdays;
- counts all calendar days in the estimated care benefit, so a weekend-only period adds an estimated Tervisekassa income without reducing salary;
- recalculates the linked net salary; and
- creates a separate, status-trackable estimated Tervisekassa income in the salary-payment month.

The benefit basis is configurable:

- **Estimate from the selected hourly income** approximates the previous calendar year's income as the current hourly gross rate multiplied by Estonia's standard working hours for that prior year.
- **Use actual previous-year social-taxable income** asks for the previous calendar year's total gross income on which social tax was paid, as reported to MTA. It is an annual amount—not net salary and not one month's income.

The built-in 2026 approximation follows Tervisekassa's published child-care rules: payment from the first calendar day, 80% of daily income, up to 60 days when caring for a child under 12, 22% income-tax withholding, and the 2026 daily cap of €126.87. Tervisekassa normally uses previous-calendar-year social-taxable income and official eligibility data. Budget Manager cannot see all of those details, so generated values are always labeled **Estimated** and are planning figures, not benefit decisions. See [Tervisekassa's care-benefit guidance](https://tervisekassa.ee/inimesele/huvitised/hooldushuvitis).

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

### Assigned reminders

The optional **Assignee** field lists active Home Assistant users that currently have at least one enabled Mobile App notification entity. Selecting an assignee requires a due day and enables a first-reminder time, which defaults to 09:00. Calendar occurrences remain all-day events; the reminder time is independent calendar-notification metadata interpreted in Home Assistant's configured timezone. Budget Manager sends a Companion App push at that time and hourly afterward through the end of the due day, stopping as soon as the item is marked paid or received. If a user has multiple registered notification devices, all of them receive the reminder.

Home Assistant persistent notifications are instance-wide rather than user-targeted, so assigned reminders intentionally use the user's Mobile App notification entities.

The cycle-end day, RAG colors, automatic-savings switch, and savings limits can be changed from the Budget panel or from **Settings → Devices & services → Budget Manager → Configure**. RAG status is communicated by the color of daily-money pills and cells rather than repeated threshold text in the month and plan views.

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

- Copies names, amounts, due days, assignees, reminder times, categories, item notes, and special/renewal markers.
- Recalculates copied Estonian hourly income using the target month's working hours.
- Resets account balances.
- Resets paid/received/skipped items to pending.
- Assigns fresh occurrence IDs.
- Uses the global cycle-end setting and shifts recurrence-end dates relative to the target period.
- Preserves series linkage inside a copied year without linking the copy to the source year's history.
- Does not copy child-care leave periods or their generated Tervisekassa income; these are event-specific and must be recorded in the affected work month.

When creating a year without **Overwrite**, existing target months are preserved and only missing months are filled. This makes it safe to complete a partially planned year. Enabling **Overwrite** replaces all 12 target months.

## Development verification

The pure calculation and period-copy model is covered by standard-library unit tests:

```bash
python3 -m unittest discover -s tests -v
node --check custom_components/budget_manager/frontend/budget-manager-panel.js
node tests/test_frontend_locale.mjs
python3 -m compileall -q custom_components tests
```

Integration runtime testing requires a current Home Assistant development or test instance.
