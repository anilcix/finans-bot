"""Black-Scholes greeks - Deribit sadece mark IV veriyor, gamma'yı biz hesaplıyoruz."""

import math


def bs_gamma(spot, strike, time_to_expiry_years, iv, rate=0.0):
    """Black-Scholes gamma (call ve put için matematiksel olarak aynıdır)."""
    if time_to_expiry_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv ** 2) * time_to_expiry_years) / (
        iv * math.sqrt(time_to_expiry_years)
    )
    return math.exp(-d1 ** 2 / 2) / math.sqrt(2 * math.pi) / (spot * iv * math.sqrt(time_to_expiry_years))
