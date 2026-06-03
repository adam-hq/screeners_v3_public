import streamlit as st
import pandas as pd
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from run_ic_screener import main as run_ic_screener
from run_csp_screener import main as run_csp_screener
from iron_screener.yfinance_client import monthly_expirations


def _ensure_session_messages(key: str) -> list[str]:
    if key not in st.session_state:
        st.session_state[key] = []
    return st.session_state[key]


def _add_diagnostic(key: str, message: str) -> None:
    messages = _ensure_session_messages(key)
    messages.append(message)


def _run_screener_with_diagnostics(
    run_fn,
    args,
    output_csv: Path,
    diag_key: str,
    screener_name: str,
) -> int:
    messages = _ensure_session_messages(diag_key)
    messages.clear()

    _add_diagnostic(diag_key, f"{screener_name}: output path = {output_csv}")

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        _add_diagnostic(diag_key, f"Output directory verified: {output_dir}")
        test_path = output_dir / ".write_test"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink()
        _add_diagnostic(diag_key, "Write permission check passed.")
    except Exception as exc:
        tb = traceback.format_exc()
        _add_diagnostic(diag_key, f"Output directory write check failed: {exc}\n{tb}")
        return -1

    try:
        exit_code = run_fn(args)
        _add_diagnostic(diag_key, f"Execution finished with exit code {exit_code}.")
    except Exception as exc:
        tb = traceback.format_exc()
        _add_diagnostic(diag_key, f"Execution exception: {exc}\n{tb}")
        return -1

    if not output_csv.exists():
        _add_diagnostic(diag_key, f"Output CSV not found: {output_csv}")
    elif output_csv.stat().st_size == 0:
        _add_diagnostic(diag_key, f"Output CSV exists but is empty: {output_csv}")
    else:
        _add_diagnostic(
            diag_key,
            f"Output CSV written successfully: {output_csv} ({output_csv.stat().st_size} bytes)",
        )

    return exit_code

# Set page config
st.set_page_config(
    page_title="Options Screener",
    page_icon="📈",
    layout="wide"
)

APP_VERSION = "1.2"

# Header
st.title("Options Screener")
st.caption(f"App version: {APP_VERSION}")

tab_ic, tab_csp = st.tabs(["Iron Condor Screener", "Cash Secured Put Screener"])

# Use a temporary directory for output because Streamlit Community Cloud may mount the app source as read-only.
output_dir = Path(tempfile.gettempdir()) / "screeners_v3"
output_dir.mkdir(parents=True, exist_ok=True)
output_ic_csv = output_dir / "ic_opportunities.csv"
output_csp_csv = output_dir / "csp_opportunities.csv"

with tab_ic:
    st.header("Iron Condor Screener")
    
    with st.expander("Screener Inputs", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            ic_symbols = st.text_input(
                "Tickers (comma-separated)", 
                value="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
                help="Enter symbols separated by commas.",
                key="ic_symbols_input"
            )
            ic_distances = st.text_input(
                "Distances (% or fraction)", 
                value="3,5,8,10,15,20",
                help="Target distances for strikes.",
                key="ic_distances_input"
            )
        with col2:
            ic_wing_widths = st.text_input(
                "Wing Widths ($)", 
                value="2.5, 5.0, 10.0",
                help="Comma-separated wing widths to scan simultaneously.",
                key="ic_wing_widths_input"
            )
            ic_dte_range = st.slider(
                "Days to Expiry (DTE) Range",
                min_value=0,
                max_value=120,
                value=(15, 45),
                step=1,
                help="Filter for options expiring within this many days.",
                key="ic_dte_range_input"
            )
        with col3:
            st.markdown("<br><br>", unsafe_allow_html=True)
            ic_monthly_only = st.toggle(
                "Major Monthly Expiries Only",
                value=False,
                help="Only scan the 3rd Friday standard monthly expirations.",
                key="ic_monthly_only_input"
            )

        if st.button("🚀 Execute IC Screener", use_container_width=True, key="ic_execute_btn"):
            with st.spinner("Fetching data from API and executing IC screener... Please wait."):
                ic_args = [
                    "--symbols", ic_symbols,
                    "--distances", ic_distances,
                    "--wing-widths", ic_wing_widths,
                    "--min-dte", str(ic_dte_range[0]),
                    "--max-dte", str(ic_dte_range[1]),
                    "--output", str(output_ic_csv)
                ]
                if ic_monthly_only:
                    ic_args.append("--monthly-only")
                    
                exit_code_ic = _run_screener_with_diagnostics(
                    run_ic_screener,
                    ic_args,
                    output_ic_csv,
                    "ic_diagnostics",
                    "IC Screener",
                )

                if exit_code_ic == 0 and output_ic_csv.exists() and output_ic_csv.stat().st_size > 0:
                    st.success("IC Screener execution completed and generated output.")
                elif exit_code_ic == -1:
                    st.error("IC Screener failed during execution. See diagnostics below.")
                else:
                    st.warning("IC Screener finished but did not produce valid output. See diagnostics below.")

    # Display Results
    st.markdown("### Results")
    if output_ic_csv.exists() and output_ic_csv.stat().st_size > 0:
        try:
            df = pd.read_csv(output_ic_csv)
            if df.empty:
                st.warning("The screener ran successfully, but no opportunities were found matching your criteria.")
            else:
                last_modified_time = output_ic_csv.stat().st_mtime
                last_updated = datetime.fromtimestamp(last_modified_time).strftime('%Y-%m-%d %H:%M:%S')
                st.caption(f"Last Updated: {last_updated}")

                st.markdown("#### Filters")
                filtered_df = df.copy()
                filter_left, filter_right, _ = st.columns([2, 2, 1])

                with filter_left:
                    if 'Stock' in filtered_df.columns:
                        stock_options = sorted(filtered_df['Stock'].dropna().unique().tolist())
                        selected_stocks = st.multiselect("Select Stock(s)", options=stock_options, default=stock_options, key="ic_stocks")
                        filtered_df = filtered_df[filtered_df['Stock'].isin(selected_stocks)]

                    if not filtered_df.empty and 'DTE' in filtered_df.columns:
                        dte_options = sorted(filtered_df['DTE'].dropna().unique().tolist())
                        selected_dtes = st.multiselect("Select DTE(s)", options=dte_options, default=dte_options, key="ic_dtes")
                        filtered_df = filtered_df[filtered_df['DTE'].isin(selected_dtes)]

                    major_only = st.toggle(
                        "Major monthly expirations only",
                        value=False,
                        help="Filter results to only show standard monthly expirations from yfinance.",
                        key="ic_major_only"
                    )
                    if major_only and 'Expiration' in filtered_df.columns:
                        expiry_values = filtered_df['Expiration'].astype(str).tolist()
                        monthly_set = set(monthly_expirations(expiry_values, None))
                        filtered_df = filtered_df[filtered_df['Expiration'].astype(str).isin(monthly_set)]

                with filter_right:
                    # % Distance slider - updated after previous filters
                    if not filtered_df.empty and '% Distance' in filtered_df.columns:
                        min_dist = float(filtered_df['% Distance'].min())
                        max_dist = float(filtered_df['% Distance'].max())
                        current_dist = st.session_state.get('ic_dist', (min_dist, max_dist))
                        # Clamp current values to new range
                        clamped_dist = (max(min_dist, current_dist[0]), min(max_dist, current_dist[1]))
                        if min_dist >= max_dist:
                            dist_range = st.slider("% Distance Range", min_value=0.0, max_value=max_dist + 10.0, value=clamped_dist, key="ic_dist")
                        else:
                            dist_range = st.slider("% Distance Range", min_value=min_dist, max_value=max_dist, value=clamped_dist, key="ic_dist")
                        filtered_df = filtered_df[(filtered_df['% Distance'] >= dist_range[0]) & (filtered_df['% Distance'] <= dist_range[1])]
                    
                    # Premium/Wing Ratio slider - updated after % Distance filter
                    if not filtered_df.empty and 'Premium/Wing Ratio' in filtered_df.columns:
                        valid_ratios = filtered_df['Premium/Wing Ratio'].dropna()
                        if not valid_ratios.empty:
                            min_pw = float(valid_ratios.min())
                            max_pw = float(valid_ratios.max())
                            current_pw = st.session_state.get('ic_pw', (min_pw, max_pw))
                            clamped_pw = (max(min_pw, current_pw[0]), min(max_pw, current_pw[1]))
                            if min_pw >= max_pw:
                                pw_range = st.slider("Premium/Wing Ratio", min_value=0.0, max_value=max_pw + 0.1, value=clamped_pw, key="ic_pw")
                            else:
                                pw_range = st.slider("Premium/Wing Ratio", min_value=min_pw, max_value=max_pw, value=clamped_pw, key="ic_pw")
                            filtered_df = filtered_df[(filtered_df['Premium/Wing Ratio'] >= pw_range[0]) & (filtered_df['Premium/Wing Ratio'] <= pw_range[1])]

                    # Max Risk/Premium slider - updated after Premium/Wing Ratio filter
                    if not filtered_df.empty and 'Max Risk/Premium' in filtered_df.columns:
                        valid_risk_premiums = filtered_df['Max Risk/Premium'].dropna()
                        if not valid_risk_premiums.empty:
                            min_rr = float(valid_risk_premiums.min())
                            max_rr = float(valid_risk_premiums.max())
                            current_rr = st.session_state.get('ic_rr', (min_rr, max_rr))
                            clamped_rr = (max(min_rr, current_rr[0]), min(max_rr, current_rr[1]))
                            if min_rr >= max_rr:
                                rr_range = st.slider("Max Risk/Premium", min_value=min_rr, max_value=max_rr + 0.1, value=clamped_rr, key="ic_rr")
                            else:
                                rr_range = st.slider("Max Risk/Premium", min_value=min_rr, max_value=max_rr, value=clamped_rr, key="ic_rr")
                            filtered_df = filtered_df[(filtered_df['Max Risk/Premium'] >= rr_range[0]) & (filtered_df['Max Risk/Premium'] <= rr_range[1])]

                    # Smart filter toggle - applied last
                    smart_filter = st.toggle(
                        "Smart filter",
                        value=False,
                        help="If enabled, only show rows with Max Risk/Premium < 20, Premium/Wing Ratio between 0.2 and 0.4, and Distance > 5%.",
                        key="ic_smart_filter"
                    )
                    if smart_filter:
                        if not filtered_df.empty:
                            filtered_df = filtered_df[
                                (filtered_df['Max Risk/Premium'] < 20) &
                                (filtered_df['Premium/Wing Ratio'] >= 0.2) &
                                (filtered_df['Premium/Wing Ratio'] <= 0.4) &
                                (filtered_df['% Distance'] > 5.0)
                            ]

                st.markdown("#### Display Options")
                show_more_information = st.toggle("Show more information", value=False, key="ic_more_info")
                columns_to_hide = ["LP Mid", "SP Mid", "LC Mid", "SC Mid", "ATR", "Support", "Resistance"]
                if not show_more_information:
                    filtered_df = filtered_df.drop(columns=[col for col in columns_to_hide if col in filtered_df.columns])

                st.dataframe(filtered_df, use_container_width=True)
                if filtered_df.empty:
                    st.info("No matching results with the current filters.")
        except Exception as e:
            st.error(f"Error reading results file: {e}")
    else:
        st.info("No IC results to display yet. Click 'Execute IC Screener' to generate data.")

    with st.expander("IC Diagnostics", expanded=False):
        for message in st.session_state.get("ic_diagnostics", []):
            st.text(message)

with tab_csp:
    st.header("Cash Secured Put Screener")
    
    with st.expander("Screener Inputs", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            csp_symbols = st.text_input(
                "Tickers (comma-separated)", 
                value="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
                help="Enter symbols separated by commas.",
                key="csp_symbols_input"
            )
            csp_distances = st.text_input(
                "Distances (% or fraction)", 
                value="3,5,8,10,15,20",
                help="Target distances for strikes.",
                key="csp_distances_input"
            )
        with col2:
            csp_dte_range = st.slider(
                "Days to Expiry (DTE) Range",
                min_value=0,
                max_value=120,
                value=(15, 45),
                step=1,
                help="Filter for options expiring within this many days.",
                key="csp_dte_range_input"
            )
        with col3:
            st.markdown("<br><br>", unsafe_allow_html=True)
            csp_monthly_only = st.toggle(
                "Major Monthly Expiries Only",
                value=False,
                help="Only scan the 3rd Friday standard monthly expirations.",
                key="csp_monthly_only_input"
            )

        if st.button("🚀 Execute CSP Screener", use_container_width=True, key="csp_execute_btn"):
            with st.spinner("Fetching data from API and executing CSP screener... Please wait."):
                csp_args = [
                    "--symbols", csp_symbols,
                    "--distances", csp_distances,
                    "--min-dte", str(csp_dte_range[0]),
                    "--max-dte", str(csp_dte_range[1]),
                    "--output", str(output_csp_csv)
                ]
                if csp_monthly_only:
                    csp_args.append("--monthly-only")
                    
                exit_code_csp = _run_screener_with_diagnostics(
                    run_csp_screener,
                    csp_args,
                    output_csp_csv,
                    "csp_diagnostics",
                    "CSP Screener",
                )

                if exit_code_csp == 0 and output_csp_csv.exists() and output_csp_csv.stat().st_size > 0:
                    st.success("CSP Screener execution completed and generated output.")
                elif exit_code_csp == -1:
                    st.error("CSP Screener failed during execution. See diagnostics below.")
                else:
                    st.warning("CSP Screener finished but did not produce valid output. See diagnostics below.")

    # Display Results
    st.markdown("### Results")
    if output_csp_csv.exists() and output_csp_csv.stat().st_size > 0:
        try:
            df_csp = pd.read_csv(output_csp_csv)
            if df_csp.empty:
                st.warning("The screener ran successfully, but no opportunities were found matching your criteria.")
            else:
                last_modified_time = output_csp_csv.stat().st_mtime
                last_updated = datetime.fromtimestamp(last_modified_time).strftime('%Y-%m-%d %H:%M:%S')
                st.caption(f"Last Updated: {last_updated}")

                st.markdown("#### Filters")
                filtered_csp_df = df_csp.copy()
                filter_left, filter_right = st.columns(2)

                with filter_left:
                    if 'Stock' in filtered_csp_df.columns:
                        stock_options = sorted(filtered_csp_df['Stock'].dropna().unique().tolist())
                        selected_stocks = st.multiselect("Select Stock(s)", options=stock_options, default=stock_options, key="csp_stocks")
                        filtered_csp_df = filtered_csp_df[filtered_csp_df['Stock'].isin(selected_stocks)]
                
                    if not filtered_csp_df.empty and 'DTE' in filtered_csp_df.columns:
                        dte_options = sorted(filtered_csp_df['DTE'].dropna().unique().tolist())
                        selected_dtes = st.multiselect("Select DTE(s)", options=dte_options, default=dte_options, key="csp_dtes")
                        filtered_csp_df = filtered_csp_df[filtered_csp_df['DTE'].isin(selected_dtes)]

                    major_only_csp = st.toggle(
                        "Major monthly expirations only",
                        value=False,
                        help="Filter CSP results to only show standard monthly expirations from yfinance.",
                        key="csp_major_only"
                    )
                    if major_only_csp and 'Expiration' in filtered_csp_df.columns:
                        expiry_values = filtered_csp_df['Expiration'].astype(str).tolist()
                        monthly_set = set(monthly_expirations(expiry_values, None))
                        filtered_csp_df = filtered_csp_df[filtered_csp_df['Expiration'].astype(str).isin(monthly_set)]

                    if not filtered_csp_df.empty and 'Delta' in filtered_csp_df.columns:
                        valid_deltas = filtered_csp_df['Delta'].dropna()
                        if not valid_deltas.empty:
                            min_delta = float(valid_deltas.min())
                            max_delta = float(valid_deltas.max())
                            if min_delta < max_delta:
                                delta_range = st.slider("Safety Level (Delta) Range", min_value=min_delta, max_value=max_delta, value=(min_delta, max_delta), key="csp_delta")
                                filtered_csp_df = filtered_csp_df[(filtered_csp_df['Delta'] >= delta_range[0]) & (filtered_csp_df['Delta'] <= delta_range[1])]

                with filter_right:
                    if not filtered_csp_df.empty and '% Distance' in filtered_csp_df.columns:
                        valid_dists = filtered_csp_df['% Distance'].dropna()
                        if not valid_dists.empty:
                            min_dist = float(valid_dists.min())
                            max_dist = float(valid_dists.max())
                            if min_dist < max_dist:
                                dist_range = st.slider("% Distance Range", min_value=min_dist, max_value=max_dist, value=(min_dist, max_dist), key="csp_dist")
                                filtered_csp_df = filtered_csp_df[(filtered_csp_df['% Distance'] >= dist_range[0]) & (filtered_csp_df['% Distance'] <= dist_range[1])]
                    
                    if not filtered_csp_df.empty and 'RSI 14' in filtered_csp_df.columns:
                        valid_rsis = filtered_csp_df['RSI 14'].dropna()
                        if not valid_rsis.empty:
                            min_rsi = float(valid_rsis.min())
                            max_rsi = float(valid_rsis.max())
                            if min_rsi < max_rsi:
                                rsi_range = st.slider("RSI 14 Range", min_value=min_rsi, max_value=max_rsi, value=(min_rsi, max_rsi), key="csp_rsi")
                                filtered_csp_df = filtered_csp_df[(filtered_csp_df['RSI 14'] >= rsi_range[0]) & (filtered_csp_df['RSI 14'] <= rsi_range[1])]

                st.markdown("#### Display Options")
                show_more_information = st.toggle("Show more information", value=False, key="csp_more_info")
                columns_to_hide = ["Lower BB", "SMA 200", "Stock Price"]
                if not show_more_information:
                    filtered_csp_df = filtered_csp_df.drop(columns=[col for col in columns_to_hide if col in filtered_csp_df.columns])

                st.dataframe(filtered_csp_df, use_container_width=True)
                if filtered_csp_df.empty:
                    st.info("No matching results with the current filters.")
        except Exception as e:
            st.error(f"Error reading results file: {e}")
    else:
        st.info("No CSP results to display yet. Click 'Execute CSP Screener' to generate data.")

    with st.expander("CSP Diagnostics", expanded=False):
        for message in st.session_state.get("csp_diagnostics", []):
            st.text(message)
