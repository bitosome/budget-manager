// Invented example values only. Never copy household records into test fixtures.
export const exampleState = () => ({
  current_month:'2026-09', selected_year:2026, available_years:[2026], available_months:['2026-09'],
  settings:{currency:'EUR',locale:'en-GB',cycle_end_day:2,categories:['Home'],automatic_savings_enabled:false,plan_item_order:{income:[],expense:[],savings:[]},electricity:{fees:[{name:'Grid fee',amount:5,from_month:'2026-01',to_month:'2026-12'}]}},
  electricity:{history:{},training:{},refresh:{}},
  months:{'2026-09':{month:'2026-09',account_balance:1200,
    summary:{expected_income:2500,unpaid_expenses:600,planned_savings:100,remaining:500,days_divisor:20,daily_allowance:25,rag:'yellow'},
    items:[{id:'example-item',name:'Example expense',kind:'expense',amount:60,status:'pending',recurrence:'monthly',recurrence_end:'2027-09-01'}]
  }}
});
