import pandas as pd

# SITE CLASSIFICATION LOGIC

def determine_tcr_band(row):
    """
    Classifies a site into TCR Bands 1-4 based on current UK regulations.
    """
    # Extract row variables for readability
    voltage = str(row['voltage_level']).strip().upper()
    meter_type = str(row['meter_type']).strip().upper()

    # Handle NaN values safely
    capacity = row.get('agreed_capacity_kva', 0)
    if pd.isna(capacity): capacity = 0

    consumption = row.get('annual_consumption_kwh', 0)
    if pd.isna(consumption): consumption = 0

    # A: NON-HALF-HOURLY (NHH) & SMALL-USAGE HALF-HOURLY: This uses annual consumption in kWh
    # Assume this if the meter is NHH, or if it's HH but explicitly flagged as 'Small Usage'
    # Trigger this if Capacity is 0/Null but Consumption exists

    if meter_type == 'NHH' or (meter_type == 'HH' and capacity == 0):
        if consumption <= 3571:
            return 'Band 1'
        elif consumption <= 12553:
            return 'Band 2'
        elif consumption <= 25279:
            return 'Band 3'
        else:
            return 'Band 4'

    # B: LARGE USAGE HALF-HOURLY (HH): This uses capacity in kVA
    # Low Voltage (LV)
    if voltage == 'LV':
        if capacity <= 80:
            return 'Band 1'
        elif capacity <= 150:
            return 'Band 2'
        elif capacity <= 231:
            return 'Band 3'
        else:
            return 'Band 4' # 232 kVA and above

    # High Voltage (HV)
    elif voltage == 'HV':
        if capacity <= 422:
            return 'Band 1'
        elif capacity <= 1000:
            return 'Band 2'
        elif capacity <= 1800:
            return 'Band 3'
        else:
            return 'Band 4' # 1801 kVA and above

    # Extra High Voltage (EHV)
    elif voltage == 'EHV':
        if capacity <= 5000:
            return 'Band 1'
        elif capacity <= 12000:
            return 'Band 2'
        elif capacity <= 21500:
            return 'Band 3'
        else:
            return 'Band 4' # 21501 kVA and above

    return 'Unclassified'

def generate_tdr_lookup_key(row):
    """
    Translates the calculated Band + Voltage into the specific Key string
    found in the NESO TDR CSV (e.g., 'LV1', 'LV_NoMIC_2').
    """
    band = row['tcr_band'] # e.g. "Band 1"
    voltage = str(row['voltage_level']).upper()
    meter = str(row['meter_type']).upper()
    capacity = row.get('agreed_capacity_kva', 0)

    if band == 'Unclassified':
        return None

    band_num = band.split(' ')[-1] # Get '1' from 'Band 1'

    # 1. NHH and small HH usage (consumption) path
    # Matches CSV keys: 'LV_NoMIC_1', 'LV_NoMIC_2'...
    if meter == 'NHH' or (meter == 'HH' and (pd.isna(capacity) or capacity == 0)):
        return f"LV_NoMIC_{band_num}"

    # 2. Large HH usage (capacity) path
    # Matches CSV keys: 'LV1', 'HV3', 'EHV4'
    return f"{voltage}{band_num}"

# Testing the logic
data = {
    'site_id': ['Shop_Small', 'Warehouse_LV', 'Factory_HV', 'Heavy_Ind_EHV'],
    'meter_type': ['NHH', 'HH', 'HH', 'HH'],
    'voltage_level': ['LV', 'LV', 'HV', 'EHV'],
    'agreed_capacity_kva': [0, 140, 900, 25000], # Note: Shop_Small has 0 capacity
    'annual_consumption_kwh': [12000, 0, 0, 0]   # Only relevant for the NHH site
}

df_sites = pd.DataFrame(data)
df_sites['tcr_band'] = df_sites.apply(determine_tcr_band, axis=1)
print(df_sites[['site_id', 'voltage_level', 'agreed_capacity_kva', 'tcr_band']])

# DATA INGESTION & CLEANING

def get_latest_forecast(df, group_cols):
    """
    Sorts by Published_Date and keeps only the most recent forecast
    for each unique combination of Year and Zone/Band.
    """
    # Ensure date is datetime object
    df['Published_Date'] = pd.to_datetime(df['Published_Date'], dayfirst=True)

    # Sort by grouping columns + descending date
    df = df.sort_values(by=group_cols + ['Published_Date'], ascending=[True] * len(group_cols) + [False])

    # Drop duplicates, keeping the first (latest) one
    return df.drop_duplicates(subset=group_cols, keep='first').copy()

def load_and_clean_data():
    # Load CSV files
    df_hh = pd.read_csv('tnuos_demand_hh.csv')
    df_nhh = pd.read_csv('tnuos_demand_nhh.csv')
    df_tdr = pd.read_csv('tnuos_tdr-tariffs.csv')

    # Clean half-hourly (locational) data
    # We need the year, zone, and tariff rate.
    # Note that 'HHTariff(Floored)_£/kW' is usually the final billable rate.
    print("Processing HH Tariffs...")
    df_hh_clean = get_latest_forecast(df_hh, ['Year_FY', 'Zone_No'])
    df_hh_clean = df_hh_clean[['Year_FY', 'Zone_No', 'HHTariff(Floored)_£/kW']].rename(
        columns={'HHTariff(Floored)_£/kW': 'rate_locational_kw'}
    )

    # Clean non half-hourly (locational) data
    print("Processing NHH Tariffs...")
    df_nhh_clean = get_latest_forecast(df_nhh, ['Year_FY', 'Zone_No'])
    df_nhh_clean = df_nhh_clean[['Year_FY', 'Zone_No', 'NHHTariff(Floored)_p/kWh']].rename(
        columns={'NHHTariff(Floored)_p/kWh': 'rate_locational_p_kwh'}
    )

    # Clean TDR (residual) data
    # TDR has no zones (i.e. national rate), so we have to map the TDR Band to our logic.
    print("Processing TDR Tariffs...")

    # Fix encoding issues in column name if present
    rate_col = [c for c in df_tdr.columns if 'Tariff' in c][0]

    df_tdr_clean = get_latest_forecast(df_tdr, ['Year_FY', 'TDR Band'])
    df_tdr_clean = df_tdr_clean[['Year_FY', 'TDR Band', rate_col]].rename(
        columns={rate_col: 'rate_residual_p_day'}
    )

    # Create a 'lookup_key' to match the calculator logic
    # Our Logic: Voltage (LV/HV/EHV) + Band (1-4) + Meter (NoMIC/MIC)
    def map_tdr_band_to_key(raw_band):
        # Map CSV keys to a standardized format: "{VOLTAGE}_Band{N}"
        # Large usage (capacity) mapping:
        if raw_band in ['LV1', 'LV2', 'LV3', 'LV4']:
            return f"LV_Band{raw_band[-1]}"
        elif raw_band in ['HV1', 'HV2', 'HV3', 'HV4']:
            return f"HV_Band{raw_band[-1]}"
        elif raw_band in ['EHV1', 'EHV2', 'EHV3', 'EHV4']:
            return f"EHV_Band{raw_band[-1]}"

        # Small usage (consumption) mapping:
        # "LV_NoMIC_1" -> "LV_NoMIC_Band1"
        elif 'LV_NoMIC' in raw_band:
            return f"LV_NoMIC_Band{raw_band.split('_')[-1]}"

        return 'Ignore'

    df_tdr_clean['lookup_key'] = df_tdr_clean['TDR Band'].apply(map_tdr_band_to_key)

    # Filter out 'Domestic', 'Unmetered', etc.
    df_tdr_clean = df_tdr_clean[df_tdr_clean['lookup_key'] != 'Ignore']

    return df_hh_clean, df_nhh_clean, df_tdr_clean

# Execution
df_hh_rates, df_nhh_rates, df_tdr_rates = load_and_clean_data()

print("Data Loaded Successfully!")
print(f"Residual Rates (2026 Example):\n{df_tdr_rates[df_tdr_rates['Year_FY']==2026].head()}")

# CALCULATION ENGINE

def calculate_portfolio_impact(df_sites, target_year=2026):
    """
    This function does the following:
    1. Loads data
    2. Maps sites -> bands -> keys
    3. Merges rates
    4. Calculates £ cost
    """

    # a. Load data
    df_hh_rates, df_nhh_rates, df_tdr_rates = load_and_clean_data()
    if df_hh_rates is None:
        return df_tdr_rates # Error message

    # Filter rates for target year
    hh_rates = df_hh_rates[df_hh_rates['Year_FY'] == target_year].copy()
    nhh_rates = df_nhh_rates[df_nhh_rates['Year_FY'] == target_year].copy()
    tdr_rates = df_tdr_rates[df_tdr_rates['Year_FY'] == target_year].copy()

    # b. Run classification logic on sites
    df_calc = df_sites.copy()
    df_calc['tcr_band'] = df_calc.apply(determine_tcr_band, axis=1)
    df_calc['tdr_key'] = df_calc.apply(generate_tdr_lookup_key, axis=1)

    # c. Merge residual rates (fixed charge)
    # Join on 'tdr_key' -> 'TDR Band'
    df_calc = pd.merge(df_calc, tdr_rates, left_on='tdr_key', right_on='TDR Band', how='left')

    # d. Merge locational rates (zonal)
    # Split the merge because HH and NHH have different logic

    # Init columns
    df_calc['locational_rate'] = 0.0
    df_calc['locational_cost_pound'] = 0.0

    # HH Merge
    # HH Cost = Rate (£/kW) * Capacity (Using Capacity as a proxy for Triad)
    hh_mask = df_calc['meter_type'] == 'HH'
    if hh_mask.any():
        temp_hh = pd.merge(df_calc[hh_mask], hh_rates, left_on='dno_zone', right_on='Zone_No', how='left')
        # Update original dataframe using the index
        df_calc.loc[hh_mask, 'locational_rate'] = temp_hh['rate_locational_kw'].values
        # Calculation: Rate * Capacity
        df_calc.loc[hh_mask, 'locational_cost_pound'] = (
            df_calc.loc[hh_mask, 'locational_rate'] * df_calc.loc[hh_mask, 'agreed_capacity_kva']
        )

    # NHH Merge
    # NHH Cost = Rate (p/kWh) * Consumption / 100
    nhh_mask = df_calc['meter_type'] == 'NHH'
    if nhh_mask.any():
        temp_nhh = pd.merge(df_calc[nhh_mask], nhh_rates, left_on='dno_zone', right_on='Zone_No', how='left')
        df_calc.loc[nhh_mask, 'locational_rate'] = temp_nhh['rate_locational_p_kwh'].values
        # Calculation: (Rate * Consumption) / 100
        df_calc.loc[nhh_mask, 'locational_cost_pound'] = (
            df_calc.loc[nhh_mask, 'locational_rate'] * df_calc.loc[nhh_mask, 'annual_consumption_kwh'] / 100
        )

    # e. Final residual calculation
    # Cost = daily rate * 365
    df_calc['residual_cost_pound'] = df_calc['rate_residual_p_day'] * 365

    # f. Total Cost
    df_calc['total_tnuos_cost'] = df_calc['residual_cost_pound'] + df_calc['locational_cost_pound']

    # Cleanup formatting
    df_calc['residual_cost_pound'] = df_calc['residual_cost_pound'].fillna(0).round(2)
    df_calc['locational_cost_pound'] = df_calc['locational_cost_pound'].fillna(0).round(2)
    df_calc['total_tnuos_cost'] = df_calc['total_tnuos_cost'].fillna(0).round(2)

    return df_calc

# TEST RUN
if __name__ == "__main__":
    # Create Dummy Portfolio
    data = {
        'site_id': ['Factory_London_HH', 'Shop_North_NHH', 'Depot_Midlands_HH', 'Big_Ind_Scot_EHV'],
        'meter_type': ['HH', 'NHH', 'HH', 'HH'],
        'voltage_level': ['HV', 'LV', 'LV', 'EHV'],
        'dno_zone': [12, 3, 8, 2], # 12=London, 3=Northern, 8=Midlands, 2=S.Scotland
        'agreed_capacity_kva': [1500, 0, 200, 25000],
        'annual_consumption_kwh': [0, 15000, 0, 0] # 15000 is Band 3 for NHH
    }

    df_test_sites = pd.DataFrame(data)

    print("\n--- Running Calculation for 2026 ---")
    try:
        results = calculate_portfolio_impact(df_test_sites, target_year=2026)
        if isinstance(results, str):
            print(results)
        else:
            cols = ['site_id', 'tcr_band', 'tdr_key', 'rate_residual_p_day', 'residual_cost_pound', 'locational_cost_pound', 'total_tnuos_cost']
            print(results[cols].to_string())

            total_impact = results['total_tnuos_cost'].sum()
            print(f"\nTotal Portfolio TNUoS Cost (2026): £{total_impact:,.2f}")
    except Exception as e:
        print(f"Execution failed: {e}")