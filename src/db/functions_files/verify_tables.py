import random

def verify_tables(supabase):
    """Verify database tables exist and are accessible"""
    random_number_string = str(random.randint(1, 9000))
    test_record = {
        'date': '2025-01-01',
        'ticker': random_number_string,
        'action': random_number_string,
        'quantity': 0,
        'price': 0,
        'shares_owned': 0,
        'position_value': 0,
        'bullish_count': 0,
        'bearish_count': 0,
        'neutral_count': 0,
        'total_value': 0,
        'return_pct': 0,
        'cash_balance': 0,
        'total_position_value': 0
    }
    try:
        response = supabase.table('backtest_records').upsert(test_record).execute()
        print("Database tables verified")
        return True
    except Exception as e:
        print(f"Database table verification failed: {e}")
        return False