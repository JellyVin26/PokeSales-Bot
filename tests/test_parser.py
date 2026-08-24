#!/usr/bin/env python3
"""Quick test script for the pokebot parser."""

from src.pokebot.core.parser import parse_amount

def test_parse():
    """Test amount parsing with various formats."""
    tests = [
        # (input, expected_amount, expected_currency, expected_payment)
        ("13", 13.0, "MYR", "Unknown"),
        ("RM 13", 13.0, "MYR", "Unknown"),
        ("RM13", 13.0, "MYR", "Unknown"),
        ("13 RM", 13.0, "MYR", "Unknown"),
        ("13.00", 13.0, "MYR", "Unknown"),
        ("RM 13.00", 13.0, "MYR", "Unknown"),
        ("RM 13 cash", 13.0, "MYR", "Cash"),
        ("RM 13 qr", 13.0, "MYR", "QR"),
        ("RM 13 transfer", 13.0, "MYR", "Bank Transfer"),
        ("RM 13 card", 13.0, "MYR", "Card"),
    ]
    
    passed = 0
    failed = 0
    
    for inp, exp_amount, exp_currency, exp_payment in tests:
        result = parse_amount(inp)
        if result is None:
            print(f"FAIL: {inp!r} -> None (expected amount={exp_amount})")
            failed += 1
            continue
        
        ok = (result.amount == exp_amount and 
              result.currency == exp_currency and 
              result.payment_method == exp_payment)
        
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        
        print(f"{status}: {inp!r:15} -> amount={result.amount}, currency={result.currency}, payment={result.payment_method}")
        
        if ok:
            passed += 1
    
    print(f"\n{passed}/{len(tests)} tests passed")
    return failed == 0

if __name__ == "__main__":
    success = test_parse()
    exit(0 if success else 1)