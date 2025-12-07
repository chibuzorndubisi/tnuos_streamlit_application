import pandas as pd
import numpy as np
import copy
# Import the engine we built in Phase 2
from tnuos_engine import calculate_portfolio_impact, determine_tcr_band

class ScenarioModeler:
    def __init__(self, sites_df, year):
        self.baseline_sites = sites_df.copy()
        self.year = year

    def identify_band_drop_opportunities(self):
        """
        Identifies sites that are within 20% of a lower band threshold.
        """
        opportunities = []

        # TCR thresholds:
        # The value represents the UPPER LIMIT of the lower band.
        # Example: To drop from Band 4 to Band 3, you must get below the Band 3 limit.

        tcr_thresholds = {
            # LARGE USAGE HH (Uses Agreed Capacity kVA)
            'HH': {
                'LV': {'Band 4': 231, 'Band 3': 150, 'Band 2': 80},
                'HV': {'Band 4': 1800, 'Band 3': 1000, 'Band 2': 422},
                'EHV': {'Band 4': 21500, 'Band 3': 12000, 'Band 2': 5000}
            },
            # NHH & SMALL HH (Uses Annual Consumption kWh)
            'NHH': {
                'ALL': {'Band 4': 25279, 'Band 3': 12553, 'Band 2': 3571}
            }
        }

        # Run calculation on baseline to establish Current Band
        df_res = calculate_portfolio_impact(self.baseline_sites, target_year=self.year)

        for index, row in df_res.iterrows():
            # Extract Site Context
            volt = row.get('voltage_level', 'LV')
            meter = row.get('meter_type', 'HH')
            current_band = row.get('tcr_band')

            # Initialize analysis variables
            metric_value = 0
            metric_unit = ""
            threshold_map = None

            # 2. Determine Strategy (Capacity vs Consumption)
            if meter == 'HH':
                metric_value = row['agreed_capacity_kva']
                metric_unit = "kVA"
                if volt in tcr_thresholds['HH']:
                    threshold_map = tcr_thresholds['HH'][volt]

            elif meter == 'NHH':
                metric_value = row['annual_consumption_kwh']
                metric_unit = "kWh"
                threshold_map = tcr_thresholds['NHH']['ALL']

            # 3. Analyze for Band Drop
            # We only analyze if we found a valid map and the band is droppable (i.e., not already Band 1)
            if threshold_map and current_band in threshold_map:
                target_val = threshold_map[current_band]

                # Logic:
                # If current value is ABOVE target, but within 20% (1.2x) of it,
                # it is an "Opportunity".
                upper_limit_check = target_val * 1.2

                if target_val < metric_value <= upper_limit_check:
                    reduction_needed = metric_value - target_val

                    # Calculate % reduction for context
                    pct_reduction = (reduction_needed / metric_value) * 100

                    opportunities.append({
                        'Site ID': row['site_id'],
                        'Current Band': current_band,
                        'Current Level': f"{metric_value:,.0f} {metric_unit}",
                        'Target Level': f"{target_val:,.0f} {metric_unit}",
                        'Reduction Needed': f"{reduction_needed:,.1f} {metric_unit} ({pct_reduction:.1f}%)",
                    })

        return pd.DataFrame(opportunities)
