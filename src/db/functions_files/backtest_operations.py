
def store_backtest_record(supabase, record):
    """Store a single backtest record"""
    try:
        response = supabase.table('backtest_records').upsert(record).execute()
        return True
    except Exception as e:
        print(f"Error storing backtest record: {e}")
        return False

def get_stored_data(supabase, ticker, start_date, end_date):
    """Retrieve stored backtest records and analyst signals for a date range"""
    backtest_data = supabase.table('backtest_records')\
        .select('*')\
        .gte('date', start_date)\
        .lte('date', end_date)\
        .eq('ticker', ticker)\
        .execute()
    
    analyst_signals = supabase.table('analyst_signals')\
        .select('*')\
        .gte('date', start_date)\
        .lte('date', end_date)\
        .eq('ticker', ticker)\
        .execute()
    
    return backtest_data.data, analyst_signals.data

def check_existing_data(supabase, date, ticker):
    """Check if data exists for given date and ticker"""
    response = supabase.table('backtest_records').select('*')\
        .eq('date', date)\
        .eq('ticker', ticker)\
        .execute()
    return len(response.data) > 0

def reconstruct_portfolio_state(stored_data, initial_capital):
    """Reconstruct portfolio state from stored data"""
    if not stored_data:
        return None
    
    latest_record = max(stored_data, key=lambda x: x['date'])
    return {
        "cash": latest_record['cash_balance'],
        "positions": {latest_record['ticker']: latest_record['shares_owned']},
        "realized_gains": {latest_record['ticker']: 0},
        "cost_basis": {latest_record['ticker']: latest_record['shares_owned'] * latest_record['price'] if latest_record['shares_owned'] > 0 else 0}
    }