"""
Scientific and Ecological Fire Models for Kruger National Park.
Includes:
- Attorre et al. fuel load & fire intensity formulas
- Navashni fuel load, ranking & fire intensity formulas
- FDI (Fire Danger Index) multi-criteria classification
- Season determination (Southern Hemisphere)
"""

import math
from typing import Tuple, Optional


def calc_season(month: int) -> str:
    """
    Returns season for Kruger National Park (Southern Hemisphere):
    Summer: Dec, Jan, Feb, Mar (12, 1, 2, 3)
    Autumn: Apr, May (4, 5)
    Winter: Jun, Jul, Aug (6, 7, 8)
    Spring: Sep, Oct, Nov (9, 10, 11)
    """
    if month in (12, 1, 2, 3):
        return "summer"
    elif month in (4, 5):
        return "autumn"
    elif month in (6, 7, 8):
        return "winter"
    elif month in (9, 10, 11):
        return "spring"
    return "unknown"


def calc_frequency(current_year: int, max_prev_year: Optional[int]) -> int:
    """
    Fire frequency = current_year - max_prev_year.
    Default to 6 if no previous fire recorded.
    Capped at maximum 6.
    """
    if max_prev_year is None:
        return 6
    freq = current_year - int(max_prev_year)
    if freq > 6:
        return 6
    elif freq < 0:
        return 0
    return freq


def calc_simulated_fuel_load_att(rainfall: float, frequency: int) -> float:
    """
    Formula Attorre et al.:
    Simulated_fuel_load_Att = (928.81 + (1.4103 * RainFall)) + (805.2995 * Frequency)
                            - (148.1845 * Frequency^2) + (0.5333 * Frequency * RainFall)
    """
    f = float(frequency)
    r = float(rainfall)
    return (928.81 + (1.4103 * r)) + (805.2995 * f) - (148.1845 * f * f) + (0.5333 * f * r)


def calc_simulated_fuel_load_nav(rainfall: float, frequency: int) -> int:
    """
    Formula Navashni:
    Simulated_fuel_load_Nav = (382.9 + (3.3 * RainFall)) + (979.4 * Frequency)
                            - (0.001 * RainFall^2) + (0.37 * RainFall * Frequency)
                            - (161.8 * Frequency^2)
    """
    f = float(frequency)
    r = float(rainfall)
    val = (382.9 + (3.3 * r)) + (979.4 * f) - (0.001 * r * r) + (0.37 * r * f) - (161.8 * f * f)
    return round(val)


def calc_rank_fuel_loads_nav(fuel_load_nav: float) -> int:
    """
    Ranks fuel load into classes 1 to 5:
    1: 0 - 1000
    2: 1001 - 2000
    3: 2001 - 4000
    4: 4001 - 6000
    5: > 6000
    """
    if fuel_load_nav <= 1000:
        return 1
    elif fuel_load_nav <= 2000:
        return 2
    elif fuel_load_nav <= 4000:
        return 3
    elif fuel_load_nav <= 6000:
        return 4
    else:
        return 5


def calc_fire_intensity(season: str, fuel_load: float) -> int:
    """
    Calculates fire intensity:
    exp(a + b * fuel_load) - 1
    Coefficients vary by season.
    """
    s = season.lower()
    if s == "summer":
        val = math.exp(6.074 + (0.0001773 * fuel_load)) - 1
    elif s == "autumn":
        val = math.exp(6.495 + (0.0001412 * fuel_load)) - 1
    elif s == "winter":
        val = math.exp(6.318 + (0.0003328 * fuel_load)) - 1
    elif s == "spring":
        val = math.exp(6.168 + (0.0003414 * fuel_load)) - 1
    else:
        val = math.exp(6.074 + (0.0001773 * fuel_load)) - 1
    return round(val)


def calc_classed_intensity_att(fire_intensity_att: float, fdi: float) -> str:
    """
    Attorre et al. classification with FDI threshold at 70:
    < 1200:
      FDI >= 70 -> medium
      else -> low
    1200 - 1650:
      FDI >= 70 -> high
      else -> moderate
    >= 1650:
      FDI >= 70 -> very high
      else -> high
    """
    if fire_intensity_att < 1200:
        return "medium" if fdi >= 70 else "low"
    elif fire_intensity_att < 1650:
        return "high" if fdi >= 70 else "moderate"
    else:
        return "very high" if fdi >= 70 else "high"


def calc_classed_intensity_nav(rank_fuel: int, season: str, fdi: float) -> str:
    """
    Navashni classification combining rank fuel load, season and FDI.
    """
    s = season.lower()
    high_fdi = (fdi >= 70)

    if rank_fuel in (1, 2):
        return "moderate" if high_fdi else "low"

    elif rank_fuel == 3:
        if s == "winter":
            return "very high" if high_fdi else "high"
        else:
            return "high" if high_fdi else "moderate"

    elif rank_fuel == 4:
        if s in ("winter", "autumn", "spring"):
            return "very high" if high_fdi else "high"
        else:  # summer
            return "high" if high_fdi else "moderate"

    elif rank_fuel == 5:
        if s == "autumn":
            return "very high" if high_fdi else "high"
        elif s == "summer":
            return "high" if high_fdi else "moderate"
        else:  # winter or spring
            return "very high" if high_fdi else "high"

    return "moderate" if high_fdi else "low"
