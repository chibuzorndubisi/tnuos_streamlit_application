import pandas as pd
import numpy as np
import copy
# Import the engine we built in Phase 2
from tnuos_engine import calculate_portfolio_impact, determine_tcr_band

class ScenarioModeler:
    def __init__(self, df_baseline_sites):
        """
        Initializes with the baseline portfolio.
        """
        self.baseline_sites = copy.deepcopy(df_baseline_sites)
        self.current_scenario_sites = copy.deepcopy(df_baseline_sites)
        self.year = 2027

    def reset_scenario(self):
        """
        Reverts current scenario back to baseline.
        """
        self.current_scenario_sites = copy.deepcopy(self.baseline_sites)

    def run_capacity_optimization(self, reduction_percentage=0.10):
        """
        Scenario 1: What if we reduce Agreed Capacity by X%?
        Target: Try to drop sites into a lower TCR Band.
        """
        print(f"--- Running Scenario: Reduce Capacity by {reduction_percentage*100}% ---")

        # Reduce capacity
        self.current_scenario_sites['agreed_capacity_kva'] = (
            self.current_scenario_sites['agreed_capacity_kva'] * (1 - reduction_percentage)
        )

        # Round to nearest integer (kVA is usually integer)
        self.current_scenario_sites['agreed_capacity_kva'] = (
            self.current_scenario_sites['agreed_capacity_kva'].round(0).astype(int)
        )

        return self.calculate_delta("Capacity Optimization")

    def calculate_delta(self, scenario_name):
        # Placeholder implementation
        delta = self.current_scenario_sites.copy()
        delta['scenario'] = scenario_name
        return delta

    def run_demand_flexibility(self, flex_factor=0.20):
        """
        Scenario 2: Demand Flexibility
        This does not change the Fixed Residual Band (which is based on Agreed Capacity).
        It only reduces the 'Locational' charge by assuming we turn down equipment during peaks.

        We implement this by creating a 'simulated_peak_kw' column that is lower than capacity.
        """
        print(f"--- Running Scenario: Demand Flexibility ({flex_factor*100}% reduction at peak) ---")

        # Assumption: Without flex, Peak = Agreed Capacity (conservative).
        # With flex, Peak = Agreed Capacity * (1 - flex_factor)


        # Run Baseline to get Locational Cost
        df_base_res = calculate_portfolio_impact(self.baseline_sites, self.year)

        # Calculate Savings
        # Saving = Locational Cost * Flex Factor
        # (Only applies to HH sites)
        savings = df_base_res[df_base_res['meter_type'] == 'HH']['locational_cost_pound'] * flex_factor

        total_saving = savings.sum()
        return total_saving

# Testing
if __name__ == "__main__":
    # Create Dummy Data that includes a "Borderline" site
    data = {
        'site_id': ['Site_Optimized', 'Site_Static'],
        'meter_type': ['HH', 'HH'],
        'voltage_level': ['LV', 'LV'],
        'dno_zone': [12, 12],
        'agreed_capacity_kva': [160, 500], # 160 is Band 3. 150 is Band 2 limit.
        'annual_consumption_kwh': [0, 0]
    }
    df = pd.DataFrame(data)

    modeler = ScenarioModeler(df)

    # 1. Test Capacity Reduction
    result = modeler.run_capacity_optimization(reduction_percentage=0.10)
    print(f"\nScenario Result: {result}")