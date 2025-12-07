import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from io import BytesIO

# Import our custom modules (Phase 2 & 3)
from tnuos_engine import calculate_portfolio_impact, determine_tcr_band
from scenario_manager import ScenarioModeler

# CONFIG & ASSETS

st.set_page_config(
    page_title="TNUoS Impact Calculator",
    page_icon="⚡",
    layout="wide"
)

# Hardcoded Centroids for DNO Zones (for the Heatmap)
ZONE_COORDS = {
    1:  {'lat': 57.1497, 'lon': -2.0943, 'name': 'Northern Scotland'},
    2:  {'lat': 55.8642, 'lon': -4.2518, 'name': 'Southern Scotland'},
    3:  {'lat': 54.9783, 'lon': -1.6178, 'name': 'Northern'},
    4:  {'lat': 53.4808, 'lon': -2.2426, 'name': 'North West'},
    5:  {'lat': 53.8008, 'lon': -1.5491, 'name': 'Yorkshire'},
    6:  {'lat': 53.1934, 'lon': -2.8931, 'name': 'N Wales & Mersey'},
    7:  {'lat': 52.9548, 'lon': -1.1581, 'name': 'East Midlands'},
    8:  {'lat': 52.4862, 'lon': -1.8904, 'name': 'Midlands'},
    9:  {'lat': 52.6309, 'lon': 1.2974,  'name': 'Eastern'},
    10: {'lat': 51.4816, 'lon': -3.1791, 'name': 'South Wales'},
    11: {'lat': 51.2787, 'lon': 0.5217,  'name': 'South East'},
    12: {'lat': 51.5074, 'lon': -0.1278, 'name': 'London'},
    13: {'lat': 51.4543, 'lon': -0.9781, 'name': 'Southern'},
    14: {'lat': 50.7184, 'lon': -3.5339, 'name': 'South Western'},
}

# HELPER FUNCTIONS

def create_pdf_report(summary_stats, opportunities_df):
    """Generates a PDF summary of the risk analysis."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Title
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="TNUoS Risk Assessment", ln=1, align='C')
    pdf.ln(10)

    # Executive Summary
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Portfolio Analytics: Executive Summary", ln=1)
    pdf.set_font("Arial", size=11)

    baseline = summary_stats['baseline_cost']
    forecast = summary_stats['forecast_cost']
    increase = forecast - baseline
    # Avoid division by zero error if baseline is 0
    pct = (increase / baseline * 100) if baseline > 0 else 0

    pdf.cell(200, 8, txt=f"Baseline Portfolio Cost, 2025/26: GBP {baseline:,.2f}", ln=1)
    pdf.cell(200, 8, txt=f"Forecast Portfolio Cost, 2026/27: GBP {forecast:,.2f}", ln=1)
    pdf.cell(200, 8, txt=f"Net Increase: GBP {increase:,.2f} (+{pct:.1f}%)", ln=1)
    pdf.cell(200, 8, txt=f"Sites Flagged 'Critical Risk' (>100% Rise): {summary_stats['high_risk_count']}", ln=1)

    pdf.ln(10)

    # Opportunities
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Optimisation Opportunities (Band Drops)", ln=1)
    pdf.set_font("Arial", size=10)

    if not opportunities_df.empty:
        # We iterate through the standardized columns we created in ScenarioModeler
        for index, row in opportunities_df.iterrows():
            # MATCHING THE NEW COLUMN NAMES:
            # 'Site ID' instead of 'site_id'
            # 'Reduction Needed' instead of 'reduction_kVA'

            line = f"Site: {row['Site ID']} | Reduce by {row['Reduction Needed']} to drop Band."
            pdf.cell(200, 8, txt=line, ln=1)
    else:
        pdf.cell(200, 8, txt="No TCR band drop opportunity found within a 20% reduction threshold for this portfolio.", ln=1)

    return pdf.output(dest='S').encode('latin-1')

# UI LAYOUT

st.title("TNUoS Impact Calculator")
st.markdown("### A strategic non-commodity pricing & forecasting tool")

# Sidebar for global controls
with st.sidebar:
    st.header("Project Controls")
    analysis_mode = st.radio("Select Module:", ["Single Site Analytics", "Portfolio Analytics"])

    st.info("""
    **Context:**
    The April 2026 RIIO-T3 Price Control will significantly increase TNUoS costs.
    Use this tool to quantify exposure.
    """)

# MODULE 1: SINGLE SITE CALCULATOR

# Quick quote calculation
if analysis_mode == "Single Site Analytics":
    st.subheader("Quick Quote: Single Site Impact")

    # Inputs
    col1, col2, col3 = st.columns(3)

    with col1:
        s_volt = st.selectbox("Voltage Level", ["LV", "HV", "EHV"])
        s_zone = st.selectbox("DNO Zone", list(range(1, 15)), format_func=lambda x: f"{x} - {ZONE_COORDS[x]['name']}")

    with col2:
        s_type = st.selectbox("Meter Type", ["HH", "NHH"])
        s_cap = st.number_input("Agreed Capacity (kVA)", min_value=0, value=250)

    with col3:
        s_cons = st.number_input("Annual Consumption (kWh)", min_value=0, value=0)
        year_options = {
            "2026/27": 2027,
            "2027/28": 2028,
            "2028/29": 2029,
            "2029/30": 2030,
            "2030/31": 2031
        }
        s_target_label = st.selectbox("Target Forecast Year", list(year_options.keys()))
        s_target_year = year_options[s_target_label]

    # Calculation
    # Handle Session State to keep results visible
    if "calc_triggered" not in st.session_state:
        st.session_state.calc_triggered = False

    # If button is clicked, set the state to True
    if st.button("Calculate Impact"):
        st.session_state.calc_triggered = True

    # Check the STATE, not just the button
    if st.session_state.calc_triggered:

        # Create 1-row DataFrame
        single_site = pd.DataFrame([{
            'site_id': 'Quick_Quote_Site',
            'voltage_level': s_volt,
            'dno_zone': s_zone,
            'meter_type': s_type,
            'agreed_capacity_kva': s_cap,
            'annual_consumption_kwh': s_cons
        }])

        # Initialize storage for the trend graph
        trend_data = {}

        # Loop from Baseline (2025/26) to the max available forecast (2030/31)
        # using a spinner because multiple calculations might take a moment
        with st.spinner("Running pricing engines..."):
            for yr in range(2026, 2032):
                res = calculate_portfolio_impact(single_site, target_year=yr)
                cost = res['total_tnuos_cost'].values[0]

                # Format year label (e.g., 2026 -> "2025/26")
                label = f"{yr - 1}/{str(yr)[-2:]}"
                trend_data[label] = cost

                # Capture specific values for the Metrics
                if yr == 2026:
                    baseline_cost = cost
                if yr == s_target_year:
                    target_cost = cost
                    target_band = res['tcr_band'].values[0]

        # Output metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("TCR Band", target_band)
        m2.metric("2025/26 Baseline Cost", f"£{baseline_cost:,.2f}")
        m3.metric(f"{s_target_label} Forecast Cost", f"£{target_cost:,.2f}",
                  delta=f"{(target_cost - baseline_cost):,.2f}",
                  delta_color="inverse")

        # Output chart
        st.markdown("### Cost Trajectory (2025/26–2030/31)")

        # Convert dict to DataFrame for Streamlit charting
        chart_df = pd.DataFrame.from_dict(trend_data, orient='index', columns=['TNUoS Cost (£)'])

        # Plot the line chart
        st.line_chart(chart_df, color="#FF4B4B")  # Streamlit Red matches the 'inverse' delta

        # Optimisation & Sensitivity

        st.markdown("---")
        st.subheader("Optimisation & Scenario Modelling")

        # Optimization Engine (Static Check)

        st.write("**Optimization Opportunities: Band Management**")

        calculation_year = s_target_year

        # Initialize Modeler with the Single Site data and the correct calculation year
        modeler = ScenarioModeler(single_site, year=calculation_year)
        opportunities = modeler.identify_band_drop_opportunities()

        if not opportunities.empty:
            st.success(f"Opportunity to to drop a lower TCR Band with <20% capacity reduction.")
            st.dataframe(opportunities, use_container_width=True)
        else:
            st.caption(
                "No TCR band drop opportunity found within a 20% reduction threshold for this site.")

        st.divider()

        # Sensitivity Analysis
        st.write(f"**Sensitivity Analysis: Demand Variation ({s_target_label})**")
        st.caption("Adjust capacity or consumption to see cost and band implications.")

        sens_slider = st.slider("Adjust capacity/consumption by (%)", -100, 100, 0)

        if sens_slider != 0:
            # Modify DataFrame for 'What-If'
            input_cols = ['site_id', 'voltage_level', 'dno_zone', 'meter_type', 'agreed_capacity_kva',
                          'annual_consumption_kwh']

            # Create a clean copy containing ONLY inputs
            df_sens = single_site[input_cols].copy()

            factor = 1 + (sens_slider / 100)

            # Apply factor
            df_sens['annual_consumption_kwh'] = df_sens['annual_consumption_kwh'] * factor
            df_sens['agreed_capacity_kva'] = df_sens['agreed_capacity_kva'] * factor

            # Run Engine with the adjusted year
            res_sens = calculate_portfolio_impact(df_sens, target_year=calculation_year)

            # Extract Results
            sens_total = res_sens['total_tnuos_cost'].values[0]
            new_band = res_sens['tcr_band'].values[0]

            # Calculate baseline for this specific year (if not already stored)
            # We re-run baseline for safety to ensure apples-to-apples comparison
            res_base_check = calculate_portfolio_impact(single_site, target_year=calculation_year)
            base_total_check = res_base_check['total_tnuos_cost'].values[0]
            original_band = res_base_check['tcr_band'].values[0]

            diff = sens_total - base_total_check

            # metrics output
            c1, c2 = st.columns(2)
            c1.metric(f"Forecast ({s_target_label})", f"£{sens_total:,.0f}", delta=f"£{diff:,.0f}", delta_color="inverse")
            c2.metric("Projected TCR Band", new_band)

            # smart notifications

            # Band Change Alert
            if new_band != original_band:
                # Determine direction of change (Band 1 is better than Band 2, etc.)
                if new_band < original_band:
                    st.success(
                        f"🎉 **Band Drop Achieved!** Reducing by {abs(sens_slider)}% moves this site from **{original_band}** to **{new_band}**, significantly reducing fixed charges.")
                else:
                    st.error(
                        f"⚠️ **Band Penalty Warning:** Increasing by {abs(sens_slider)}% has moved this site from **{original_band}** to **{new_band}**, triggering higher fixed charges.")

            # 2. Volume Sensitivity Insight
            if abs(diff) < (base_total_check * 0.01) and abs(sens_slider) > 10:
                st.warning(
                    f" **Insight:** Changing by {abs(sens_slider)}% has minimal impact on total cost.")

        else:
            st.info("Adjust the slider above to simulate changes in agreed capacity (kVA) or annual consumption (kWh).")

    else:
        pass

# MODULE 2: PORTFOLIO CALCULATOR

elif analysis_mode == "Portfolio Analytics":
    st.subheader("Portfolio Risk Dashboard")

    # Generate dummy data
    dummy = pd.DataFrame({
        'site_id': ['London_HQ_01', 'Manch_Factory_02', 'Leeds_Warehouse_03', 'Birm_DataCenter_04',
                    'Glasgow_Hub_05', 'Bristol_Office_06', 'Cardiff_Depot_07',
                    'Newcastle_Ind_08', 'Retail_Store_09', 'Retail_Store_10'],
        'voltage_level': ['LV', 'HV', 'HV', 'EHV', 'LV', 'LV', 'LV', 'HV', 'LV', 'LV'],
        'agreed_capacity_kva': [140, 500, 1200, 6500, 240, 90, 75, 2500, 0, 0],
        'dno_zone': [12, 3, 4, 13, 1, 11, 8, 5, 2, 10],
        'meter_type': ['HH', 'HH', 'HH', 'HH', 'HH', 'HH', 'HH', 'HH', 'NHH', 'NHH'],
        'annual_consumption_kwh': [0, 0, 0, 0, 0, 0, 0, 0, 15000, 35000]
    })
    csv = dummy.to_csv(index=False).encode('utf-8')

    # File uploader & controls
    # We use columns to keep the UI clean: Uploader on left, Actions on right
    col_up, col_act = st.columns([2, 1])

    with col_up:
        uploaded_file = st.file_uploader("Upload Portfolio CSV", type=["csv"],
                                         help="Required columns: site_id, voltage_level, agreed_capacity_kva, dno_zone, meter_type, annual_consumption_kwh")

    with col_act:
        st.write("Use sample data instead")
        # Button 1: Download
        st.download_button("⬇️ Download sample", csv, "portfolio_template.csv", "text/csv", use_container_width=True)

        # Button 2: Load Example (The Feature you asked for)
        if st.button("⚡ Load sample directly", use_container_width=True):
            st.session_state['portfolio_data'] = dummy
            st.session_state['data_source'] = 'example'

    # Determine active data
    # Priority: 1. User Upload, 2. Loaded Example, 3. None
    df_sites = None

    if uploaded_file is not None:
        df_sites = pd.read_csv(uploaded_file)
        # Clear example state to avoid confusion if user switches back and forth
        if 'data_source' in st.session_state:
            del st.session_state['data_source']

    elif st.session_state.get('data_source') == 'example':
        df_sites = st.session_state['portfolio_data']

    # Main analysis block
    if df_sites is not None:
        st.success(f"Successfully loaded {len(df_sites)} sites.")

        # Scenario Toggle: Fixed vs Pass-Through
        st.divider()
        col_t1, col_t2 = st.columns([1, 2])
        with col_t1:
            contract_type = st.radio("Contract Structure", ["Pass-Through (Exposure)", "Fixed (Shielded)"])

        # Calculation
        with st.spinner('Running Calculation Engine...'):
            df_2026 = calculate_portfolio_impact(df_sites, target_year=2026)
            df_2027 = calculate_portfolio_impact(df_sites, target_year=2027)


        # Calculate Deltas
        total_2026 = df_2026['total_tnuos_cost'].sum()
        total_2027 = df_2027['total_tnuos_cost'].sum()

        # Apply Fixed Contract Logic
        if contract_type == "Fixed (Shielded)":
            # If fixed, the 'Cost to Customer' in 2026/27 remains at 2025/26 levels (simplified)
            # The 'Exposure' is hidden.
            # Apply a 15% markup from the pass-through (marked to market) cost
            display_total_2026 = total_2026 * 1.15
            display_total_2027 = total_2026 * 1.15
            delta_msg = "Shielded (No Change)"
            delta_val = 0
        else:
            display_total_2026 = total_2026
            display_total_2027 = total_2027
            delta_msg = "Direct Exposure"
            delta_val = total_2027 - total_2026

        # KPI row
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Sites Analyzed", len(df_sites))
        kpi2.metric("2025/26 Baseline cost", f"£{display_total_2026:,.0f}")
        kpi3.metric("2026/27 Forecast cost", f"£{display_total_2027:,.0f}", delta=f"{((display_total_2027-display_total_2026)/display_total_2026)*100:.1f}%", delta_color="inverse")

        # Count >100% Increases (Risk Score)
        # We compare 2026/27 unshielded vs 2025/26 to find structural risk, regardless of contract
        risk_df = df_2027.copy()
        risk_df['cost_2026'] = df_2026['total_tnuos_cost']
        risk_df['pct_change'] = ((risk_df['total_tnuos_cost'] - risk_df['cost_2026']) / risk_df['cost_2026']) * 100
        high_risk_count = len(risk_df[risk_df['pct_change'] > 100])

        kpi4.metric("High Risk Sites (>100% Rise)", high_risk_count, delta_color="inverse")

        # Filter for the specific sites
        high_risk_sites = risk_df[risk_df['pct_change'] > 100].copy()

        if not high_risk_sites.empty:
            with st.expander("⚠️ View high risk sites"):
                st.dataframe(
                    high_risk_sites[['site_id', 'cost_2026', 'total_tnuos_cost', 'pct_change']],
                    use_container_width=True,
                    column_config={
                        "site_id": "Site ID",
                        "cost_2026": st.column_config.NumberColumn("2025/26 Baseline cost", format="£%.2f"),
                        "total_tnuos_cost": st.column_config.NumberColumn("2026/27 Forecast cost", format="£%.2f"),
                        "pct_change": st.column_config.NumberColumn("% Increase", format="%.1f%%")
                    }
                )

        col1, col2 = st.columns(2)

        with col1:
            # Waterfall Chart
            st.subheader("Cost Waterfall (2025/26 - 2026/27)")

            # Prepare Data for Waterfall
            # Steps: 2025 Base -> Residual Price Rise -> Locational Change -> 2026 Total
            res_diff = df_2027['residual_cost_pound'].sum() - df_2026['residual_cost_pound'].sum()
            loc_diff = df_2027['locational_cost_pound'].sum() - df_2026['locational_cost_pound'].sum()

            fig_waterfall = go.Figure(go.Waterfall(
                name = "20", orientation = "v",
                measure = ["relative", "relative", "relative", "total"],
                x = ["2025/26 Baseline", "Fixed Residual Hike", "Locational Increase", "2026/27 Forecast"],
                textposition = "outside",
                text = [f"£{total_2026/1000:.1f}k", f" +£{res_diff/1000:.1f}k", f" +£{loc_diff/1000:.1f}k", f"£{total_2027/1000:.1f}k"],
                y = [total_2026, res_diff, loc_diff, total_2027],
                connector = {"line":{"color":"rgb(63, 63, 63)"}},
            ))
            st.plotly_chart(fig_waterfall, use_container_width=True)

        with col2:
            # Cost Trajectory Graph
            # Initialize storage for the trend graph
            trend_data_portfolio = {}

            # Loop from Baseline (2025/26) to the max available forecast (2030/31)
            with st.spinner("Running pricing engines..."):
                for yrs in range(2026, 2032):
                    res_portfolio = calculate_portfolio_impact(df_sites.copy(), target_year=yrs)
                    cost_portfolio = res_portfolio['total_tnuos_cost'].sum()

                    # Format year label (e.g., 2026 -> "2025/26")
                    label = f"{yrs - 1}/{str(yrs)[-2:]}"
                    trend_data_portfolio[label] = cost_portfolio

            # Output chart
            st.markdown("### Cost Trajectory (2025/26–2030/31)")

            # Convert dict to DataFrame for Streamlit charting
            chart_portfolio_df = pd.DataFrame.from_dict(trend_data_portfolio, orient='index',
                                                        columns=['Total TNUoS Cost (£)'])

            st.line_chart(chart_portfolio_df, color="#FF4B4B")

        st.divider()

        # --- TABS FOR DEEP DIVE ---
        tab1, tab2, tab3 = st.tabs(["🌍 Geographic Map", "📉 Band Optimization", "📑 Reports"])

        with tab1:
            st.markdown("### Regional Exposure Heatmap")
            # Map Data Preparation
            map_data = df_2027.groupby('dno_zone').agg({
                'total_tnuos_cost': 'sum',
                'site_id': 'count'
            }).reset_index()

            # Add Lat/Lon
            map_data['lat'] = map_data['dno_zone'].map(lambda x: ZONE_COORDS.get(x, {}).get('lat', 54.0))
            map_data['lon'] = map_data['dno_zone'].map(lambda x: ZONE_COORDS.get(x, {}).get('lon', -2.0))
            map_data['zone_name'] = map_data['dno_zone'].map(lambda x: ZONE_COORDS.get(x, {}).get('name', 'Unknown'))

            # Map Visual
            fig_map = px.scatter_mapbox(
                map_data, lat="lat", lon="lon", size="total_tnuos_cost", color="total_tnuos_cost",
                hover_name="zone_name", zoom=4.5, mapbox_style="carto-positron",
                title="TNUoS Cost Exposure by Region (Bubble Size = Cost)",
                color_continuous_scale=px.colors.sequential.Bluered
            )
            st.plotly_chart(fig_map, use_container_width=True)

        with tab2:
            st.markdown("### Optimisation Opportunities")
            modeler = ScenarioModeler(df_sites, year=2026)
            opportunities = modeler.identify_band_drop_opportunities()

            if not opportunities.empty:
                st.success(f"Found {len(opportunities)} opportunities to to drop a lower TCR Band with <20% capacity reduction.")
                st.dataframe(opportunities)
            else:
                st.info("No TCR band drop opportunity found within a 20% reduction threshold for this portfolio.")

        with tab3:
            st.markdown("### Export Reports")

            # Generate PDF
            if st.button("Generate Executive Summary PDF"):
                # Prepare summary stats
                stats = {
                    'baseline_cost': display_total_2026,
                    'forecast_cost': display_total_2027,
                    'high_risk_count': high_risk_count
                }
                # Use modeler to get opps for the report
                mod = ScenarioModeler(df_sites, year=2026)
                opps = mod.identify_band_drop_opportunities()

                pdf_bytes = create_pdf_report(stats, opps)

                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="TNUoS_Risk_Report.pdf">Download PDF Report</a>'
                st.markdown(href, unsafe_allow_html=True)