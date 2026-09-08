# Budget Manager for Home Assistant

Budget Manager is a local-first Home Assistant custom integration for planning income, expenditures, savings, and daily spending.

Repository: <https://github.com/bitosome/budget-manager>

It provides a full-screen sidebar application, Home Assistant entities, payment-calendar events, and automation actions. Budget data stays inside Home Assistant's versioned `.storage` area and is included in normal Home Assistant backups.

## Features

- Table-only plan view; select a month heading to open its budget (or create it if missing).
- Grouped 24-month planning matrix showing the selected year followed by the next year, with explicit year headers.
- A per-device **Hide past months** toggle shortens the plan table to the current month and future months without removing any budget data.
- A visible toggle in the plan table's `Item` header pins or unpins the first column per device; mobile defaults to unpinned for easier horizontal scrolling.
- Optional inline plan-table editing for shared names and monthly amounts. Renaming an income or expenditure updates that plan row across every stored month while preserving each month's amount and completion status. New amount cells create one-time items with default properties and are highlighted as requiring review in the month view until their details are saved.
- Detailed month view with expected income, expenditures, manual account balance, remaining forecast, and automatic EUR/day calculation.
- Dates, month names, date ranges, and future timestamp displays follow the Home Assistant user's language, date-order, time-format, and timezone preferences; ISO values remain internal to storage and APIs.
- The **Budget** sidebar opens the active budget cycle: with the default cycle end on the 2nd, the previous month remains active through the 2nd and the new month opens on the 3rd.
- Advanced Estonian hourly income converts hourly gross pay into estimated net income using either the budget month's or previous month's working-time fund, including configurable tax-free income, unemployment insurance, social-tax minimum, and 0/2/4/6% funded pension options.
- Estonian child-care sick leave can be linked to an automatic hourly salary. Calendar periods reduce only scheduled work hours, while each period creates a separate estimated Tervisekassa income in the salary-payment month.
- Care-benefit planning can approximate the previous year's income from the linked hourly salary or use a user-entered previous-year social-taxable income total.
- Smart **Electricity** expenditures use the previous consumption month's measured costs plus fixed fees, with a local adaptive model and configurable buffer for months that still need forecasting.
- Electricity settings include editable/importable bill history, learning controls, actual training status and historical forecast-error reporting. No household training data is bundled.
- Mobile includes a menu button that opens Home Assistant's native sidebar for switching panels.
- Add, edit, and delete income, expenditures, and manual savings when automatic savings is disabled.
- One-time, monthly, yearly, or **Custom** recurrence (every N months), ending **Never** or on a chosen date.
- Calendar-style save confirmation: change only this occurrence or this and following occurrences. Completed future payments are preserved; shared names still update across all months.
- Manage categories in **Budget → Settings**; choose a category from a dropdown when editing an item.
- Mark expenses paid and income received without automatically changing the manual account balance.
- Completed income and expenditures move to the end of their month-view lists; paid amounts in the plan table are crossed out without an extra tick.
- Optional assignment to a Home Assistant user with an active Companion App notification device. Assigned items require a due day and send targeted reminders from the chosen time every hour until completion or the end of that day, while calendar entries remain all-day events.
- Concise signed calendar titles such as `Apple iCloud -€9.99` and `Валя +€1873.24`.
- Create a blank month or copy any specific month.
- Create a blank 12-month year or copy any specific year.
- Reorder income and expenditure rows using Home Assistant-style drag handles in plan edit mode; the custom order is stored with the budget and included in JSON exports.
- **Mark as renewal** highlighting, without a separate special-label field. Existing custom labels remain preserved.
- Configurable budget-cycle end day (the 2nd of the following month by default).
- Independently configurable per-day RAG colors (green from €45/day and yellow from €40/day by default).
- Optional global automatic savings creates one dedicated Savings transfer in every month and calculates it without manual amounts. Savings remains separate from regular expenditures.
- Native Home Assistant summary sensors, account-balance number entity, calendar, and actions.
- Empty, zero-input installation with no bundled household or financial data.
- Versioned JSON import and export from the Budget panel for backups and moving data between installations.

## Calculation

For each month:

```text
remaining = manual account balance
                   + expected income not yet received
                   - expenditures not yet paid
                   - open fixed savings
                   - calculated automatic savings

EUR/day = remaining / relevant days

target funding gap = max(0, savings target × relevant days - remaining)
```

The day divisor is the smaller of the number of days in the budget month and the inclusive number of days until its cycle end. By default, a budget month runs through the 2nd of the following calendar month; this day is configurable in Settings.

Marking an item paid or received only changes its status. It does not change the account balance, which remains a deliberate manual input.

When automatic savings is enabled in Settings, Budget Manager also displays the target funding gap: the additional money required during the cycle to reach the configured ideal EUR/day target. It creates one system-managed Savings entry in every existing and newly created month. System-managed savings never require manual review. Its value starts from zero and takes only the money above the configured daily target:

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

## Smart Electricity expenditure

Choose **Electricity (smart)** when adding an expenditure, with monthly recurrence and the desired due day. Add one such expenditure per month for the configured household electricity supply. Its amount is calculated automatically; it cannot be overwritten in the plan table. Marking it paid freezes that amount, and reopening it resumes calculation.

### Setup and data sources

In **Budget → Settings → Electricity settings**:

1. Select the accumulated grid-cost statistic in **EUR** and grid-consumption statistic in **kWh** used by Home Assistant Energy. Both must have Recorder sum statistics. The current sensor state is not a monthly bill: Budget Manager reads reset-safe hourly changes from Recorder, using Home Assistant's timezone and handling daylight-saving transitions.
2. Ensure the cost source includes variable network charges, taxes and VAT. For example, Energy can calculate cost from a consumption meter and a `real-electricity-price` all-inclusive price sensor. Budget Manager uses the resulting cost statistic; it does not integrate a price sensor by itself. The optional price-reference field is diagnostic only, not an instantaneous-price forecast input.
3. Add each missing **fixed monthly fee including VAT** separately. Optional start/end months refer to consumption months. Do not add charges already included in the cost source.
4. Import or enter completed monthly bills in **Review / import history**. Enter consumption, the total bill minus fixed fees, and the billed fixed fees separately. Combine partial supplier bills for the same consumption month before importing. Confirmed bills override measured Recorder data. Uncheck a month to exclude it from learning while retaining its bill; removing a Recorder month also suppresses it on later refreshes until it is added again.
5. **Save settings**, then use **Refresh statistics** to read the configured history window. Check the result under Model status. With automatic learning enabled, usable completed months train the model automatically; **Retrain now** forces a new fit using saved settings and the history already loaded.

There is one electricity configuration per budget, not separate models for multiple meters or properties. Selecting an Electricity item alone does not configure its sources. Source fields start empty, and fixed fees alone are not enough to estimate consumption or variable cost. Electricity calculations currently use EUR and kWh; there is no currency or energy-unit conversion.

### When measurement replaces prediction

The payment month always follows the consumption month: October uses September. During September, October shows measured cost so far plus a projection of the remainder and fixed fees. Later payments use a local forecast. **Billed**, **Measured**, and **Estimated** labels distinguish invoice totals, complete Recorder measurements, and forecasts. Recorder measurements can differ from supplier invoices; importing the invoice reconciles that month. Incomplete measured months are not treated as complete bills.

| Consumption-month data | Amount in the following payment month |
| --- | --- |
| Confirmed/imported completed bill | Billed variable cost + billed fixed fees; no prediction or buffer |
| Complete measurements for a closed month | Measured monthly cost + applicable fixed fees; no prediction or buffer |
| Current month with usable measurements | Measured cost so far + forecast remainder + buffer on that remainder + fixed fees |
| Future month, or a past month missing complete data | Forecast variable cost + buffer + fixed fees, explicitly marked Estimated |

**Once September has ended and its complete statistics have been read, October uses September's measured cost plus fixed fees—not a prediction.** This follows calendar-month boundaries in Home Assistant's timezone, independently of the budget's payday-cycle setting. The switch occurs on a statistics refresh after the final hourly data becomes available, not necessarily exactly at midnight. Already-paid occurrences remain frozen.

```text
Open consumption month:
  bill = measured cost so far
       + estimated remaining kWh × predicted variable price per kWh
       + buffer percentage × estimated remaining variable cost
       + fixed monthly fees

Closed consumption month with complete measurements:
  bill = measured monthly cost + fixed monthly fees
```

Fixed fees are added once per consumption month, not per day, and never receive the buffer. For example, a closed month with €180 measured variable cost and €20 fixed fees produces a €200 expenditure, regardless of the configured buffer percentage. These numbers are illustrative, not installation defaults.

### Recording an actual invoice

After the consumption month ends, open the following month's budget and choose **Record actual bill** on the unpaid Electricity item (or **Edit actual bill** to correct it). Enter the full invoice total including VAT, billed kWh, and the fixed fees already included in that total. Consumption and fees may be prefilled from measurements/settings; check them against the invoice. For separate supplier and network invoices, combine the costs and fees but count their shared consumption only once.

Saving replaces only that consumption month's confirmed history. Variable training cost is `invoice total − billed fixed fees`; the expenditure becomes the exact invoice total with no extra fees or prediction buffer. Confirmed bills override Recorder measurements even after later refreshes. Future fixed-fee settings, other history months, and the manual account balance are unchanged. Saving does **not** mark the bill paid; check it after transferring the money. Reopen a paid item before correcting its bill.

The **Use this month for model training** checkbox can exclude an unusual invoice from training without losing its actual payable amount. Automatic learning refits eligible history after saving; if learning is paused, the invoice is retained for the next manual retraining or resumed learning. Zero-consumption and out-of-window months are stored but do not train the model.

Electricity settings use Home Assistant's native sum-statistics pickers for accumulated cost and consumption, and its native sensor selector for the optional price reference. Optional fee bounds display **No start limit** / **No end limit** until you choose a month.

### Prediction model: what is trained

The adaptive model is **recency-weighted, regularized seasonal regression**, implemented with Python's standard library. It is a small statistical machine-learning model, not an LLM, neural network or externally downloaded pretrained model.

Each usable completed month supplies:

- the consumption month;
- total consumption in kWh; and
- variable grid cost including VAT, excluding separately recorded fixed fees.

It fits two patterns independently: **daily consumption** (`monthly kWh / days in month`) and **variable unit price** (`variable cost / kWh`). Each pattern uses an intercept and a sine/cosine pair for the month of the year, giving six fitted coefficients in total. Fitting is performed in logarithmic space, with regularization that dampens seasonal effects when history is sparse. Predictions are also bounded relative to the weighted historical averages to reduce extreme extrapolation. Fixed fees are not learned; they remain explicit settings or billed amounts.

Training uses only enabled, completed months with positive consumption inside the selected history window. It never learns from its own forecasts or partial-month observations. Imported bills take priority over Recorder observations for the same month, avoiding duplicate samples. Monthly records with zero consumption can still represent a known bill but do not train the model.

Recent observations receive exponentially higher weight:

```text
sample weight = 2 ^ (-age in months / learning half-life in months)
```

With the default six-month half-life, an observation six months older than another has half its weight. Training recalculates the coefficients from eligible history; it is not a background neural-network training job with epochs. A small fit can legitimately complete in milliseconds.

With **six or more** usable months, the adaptive method applies its seasonal patterns. With **one to five**, predictions use recency-weighted averages instead. The **Recent weighted average** method uses those averages regardless of sample count. With no training samples, the model uses explicitly configured fallback consumption and price; without a usable estimate, it displays **Needs data**.

### Adapting during the month

Model fitting and live forecast updates are separate operations. Recent price adaptation uses `cost / kWh` from paired Recorder hours within the last seven days, requiring at least 72 usable hours and positive consumption. By default, that average has 50% weight when blended with the model's predicted price. It does not extrapolate a single instantaneous price reading from `real-electricity-price`.

For the current consumption month, measured accrual is used only when at least 95% of elapsed complete hours have paired cost and energy data. After approximately three days, observed consumption also starts influencing the full-month consumption projection, with increasing weight as the month progresses. A closed month requires complete hourly coverage to qualify as **Measured**. Gaps are not silently counted as free electricity.

The configurable buffer applies only to **unmeasured variable costs**, never to already measured costs or fixed fees. It is a planning margin, not a guarantee against future price spikes.

### Forecast settings and training status

| Setting | Default | Purpose |
| --- | --- | --- |
| Estimation method | Adaptive seasonal regression | Seasonal model or recent weighted average |
| Learn automatically | On | Refit when history, training settings or the current month changes |
| History window | 36 months | Limit eligible historical samples; configurable from 3 to 60 months |
| Learning half-life | 6 months | Control how quickly older samples lose influence |
| Recent-price weight | 50% | Blend recent measured variable prices with the model prediction |
| Buffer | 15% | Add a margin to unmeasured variable costs only |
| Fallback monthly consumption | 0 kWh | User-supplied starting estimate when no trained model is available |
| Fallback variable price | €0/kWh | User-supplied starting price when no trained price is available |
| Fixed fees | None | Separately configured monthly charges, with optional effective dates |

Settings expose the method, history window, learning half-life, recent-price weight, buffer, fallbacks, training sample count and walk-forward mean absolute error before the buffer. Pause automatic learning to freeze fitted weights, retrain manually, or reset the model while retaining history. Measured costs keep updating when learning is paused. Statistics refresh hourly and on startup; use the panel's refresh button to load updated values into an already-open view. No cloud AI service, GPU or large ML dependency is required. Training runs locally on completed months, never on forecast values or partial months.

The controls use **saved settings**:

- **Refresh statistics** reads source data and reports how many complete measured months were found, together with coverage warnings or errors. Automatic learning then refits if its inputs changed.
- **Retrain now** fits the loaded history immediately, even when automatic learning is paused. It does not fetch missing history or re-enable automatic learning.
- **Reset model** clears fitted weights and pauses automatic learning while retaining history. Retrain or enable automatic learning to fit it again.
- **Review / import history** lets you correct records, exclude outliers from learning, or remove months. Saving replaces the confirmed-history set shown in the editor; review imported rows before saving.

Model status reports the actual last training-attempt time, elapsed milliseconds, samples used, historical error and last statistics-refresh result. Missing sources, zero usable samples and Recorder failures are explained explicitly. Action results update in place without closing the dialog or jumping to the top. Unrelated budget edits do not retrain an unchanged model. Pausing learning freezes the fitted coefficients, but live-price blending, current-month accrual and the switch to completed measurements still operate.

### Accuracy and limitations

The displayed error is **walk-forward mean absolute error in EUR** for historical variable monthly costs, before buffer and fixed fees. Each evaluated month is predicted by a model trained only on earlier months, with at least six prior usable samples. This checks historical seasonal predictions without using future information. It does not recreate historical live-price blending or partial-month updates, and is not a confidence interval or a guarantee of future accuracy.

The model has no weather forecast, household occupancy, market-futures or grid-outage inputs. It can learn recurring seasonal patterns and adapt to measured changes, but cannot foresee an unexpected price spike or a new household consumption pattern. Six samples enable seasonality; they do not establish its reliability. Negative variable costs can be retained in history, but the seasonal price fit uses a small positive floor and is not designed to model negative-price regimes. A net bill credit is shown as a zero expense with a warning, not an automatically created income.

### Missing data and troubleshooting

Without usable history or fallbacks, Electricity displays **Needs data**, budget totals are explicitly incomplete, and automatic savings transfers are paused. It cannot be marked paid until a value can be calculated. No zero-value payment events are created for missing electricity data.

If this appears after creating an Electricity expenditure:

1. Check that **both** source-statistic fields are populated and saved; entering fees or selecting a price-reference sensor is not enough.
2. Refresh statistics and read the result. Verify the selected sources have accumulated EUR/kWh sum statistics and overlapping hourly history, not just current sensor states.
3. If complete months are unavailable, import completed bills or supply deliberate fallback values. Do not interpret missing data as a €0 bill.
4. If training reports zero samples despite loaded history, check enabled flags, positive kWh values and the history window.

After installing an update, restart Home Assistant and reopen Budget so the backend and frontend use the same version. These controls do not configure Home Assistant Energy or repair missing Recorder data themselves.

### History format, backup and privacy

Electricity history, settings and model inputs are included in the full budget export. Import rebuilds the model from validated history rather than trusting a supplied model payload. A dedicated electricity-history JSON import/export is also available (synthetic example):

```json
{
  "format": "budget-manager-electricity-history",
  "version": 1,
  "records": [
    {"month": "2026-01", "kwh": 1000, "grid_cost": 200, "fixed_fees": 15, "enabled": true, "source": "bill"}
  ]
}
```

Invoice history is private household data. No personal invoices, pretrained household model or Gmail credentials are distributed with the integration. Reviewing bills in Gmail is a separate data-preparation step; the installed integration does not access Gmail.

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

Open **Budget → Settings** to export or import a JSON file. An export contains all months, items, statuses, balances, cycle dates, categories, recurrence rules, and calculation settings. Import validates the file completely before replacing the current budget; an invalid file leaves existing data unchanged.

Recurrence with **Never** creates a rolling plan through the following year and extends automatically as later years are opened or the year changes. Occurrence-only edits and deletions remain exceptions, including after export/import. **Custom** repeats every 1–120 months, anchored to the starting month. When saving **This and following occurrences**, changed fields apply from the selected month onward; earlier amounts and completed payments are retained. Changing the recurrence schedule replaces only unpaid future occurrences.

In **Budget → Settings → Categories**, add, rename, or remove categories. Renaming updates existing items and future recurrence templates. Removing a category leaves its items uncategorized; it does not delete expenditures.

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
- Recalculates copied smart Electricity items for the target payment month's previous consumption month, rather than keeping the source month's bill amount.
- Resets account balances.
- Resets paid/received/skipped items to pending.
- Assigns fresh occurrence IDs.
- Uses the global cycle-end setting and shifts recurrence-end dates relative to the target period.
- Preserves series linkage inside a copied year without linking the copy to the source year's history.
- Does not copy child-care leave periods or their generated Tervisekassa income; these are event-specific and must be recorded in the affected work month.

When creating a year without **Overwrite**, existing target months are preserved and only missing months are filled. This makes it safe to complete a partially planned year. Enabling **Overwrite** replaces all 12 target months.

## Development verification

The editable panel source is `custom_components/budget_manager/frontend/budget-manager-panel.src.js`. Install the pinned frontend dependencies and regenerate the production bundle before testing or committing frontend changes:

```bash
npm ci
npm run build
```

The pure calculation and period-copy model is covered by standard-library unit tests:

```bash
python3 -m unittest discover -s tests -v
node --check custom_components/budget_manager/frontend/budget-manager-panel.src.js
node --check custom_components/budget_manager/frontend/budget-manager-panel.js
node tests/test_frontend_locale.mjs
python3 -m compileall -q custom_components tests
```

Integration runtime testing requires a current Home Assistant development or test instance.
