from __future__ import annotations
import streamlit as st
import pandas as pd
from dateutil import parser
from pathlib import Path
import plotly.express as px
from categorize import MerchantCategorizer, DEFAULT_CATEGORIES, OnlineGuesser

st.set_page_config(page_title="SpendWise", page_icon="💸", layout="wide")

st.title("SpendWise 💸 – Upload, Categorize, Analyze")
st.caption("Auto-categorize merchants (online + saved map), ask only when unsure, track shared expenses, and see totals.")

with st.sidebar:
    st.header("Settings")
    map_path = st.text_input("Merchant map file", value="data/merchant_map.csv")
    enable_online = st.checkbox("Enable online auto-categorization (OSM + Wikipedia)", value=True)
    st.write("Online hints are best-effort; your saved map always wins.")

cat = MerchantCategorizer(Path(map_path))
web = OnlineGuesser()

uploaded = st.file_uploader("Upload your statement CSV", type=["csv"])

st.subheader("Map your CSV columns")
col1, col2, col3, col4 = st.columns(4)
with col1:
    date_col = st.text_input("Date column", value="Date")
with col2:
    desc_col = st.text_input("Description column", value="Description")
with col3:
    amt_col = st.text_input("Amount column", value="Amount")
with col4:
    st.checkbox("Treat all as not shared by default", value=True, key="shared_default")  # placeholder

if uploaded is not None:
    df_raw = pd.read_csv(uploaded)
    for c in [date_col, desc_col, amt_col]:
        if c not in df_raw.columns:
            st.error(f"Missing column: {c}. Please fix names above.")
            st.stop()

    df = pd.DataFrame({
        "date": pd.to_datetime(df_raw[date_col].apply(lambda x: parser.parse(str(x), dayfirst=False, fuzzy=True)), errors="coerce"),
        "merchant": df_raw[desc_col].astype(str).str.strip(),
        "amount": pd.to_numeric(df_raw[amt_col], errors="coerce"),
    }).dropna(subset=["date", "merchant", "amount"])

    invert = st.checkbox("My CSV uses negative for spend (tick to invert)", value=False)
    if invert:
        df["amount"] = -df["amount"]

    # 1) Use saved map first
    df["category"] = df["merchant"].apply(lambda m: cat.get_category(m))

    # 2) For still-unknown, try online guesser
    if enable_online:
        unknown_idx = df["category"].isna()
        if unknown_idx.any():
            guesses = df.loc[unknown_idx, "merchant"].apply(lambda m: web.guess(m))
            df.loc[unknown_idx, "category"] = guesses

    # Ask you only if still unknown
    st.subheader("Assign categories for remaining unknown merchants")
    unknown_mask = df["category"].isna()
    if unknown_mask.any():
        unk_df = df.loc[unknown_mask, ["merchant"]].drop_duplicates().reset_index(drop=True)
        for i, row in unk_df.iterrows():
            with st.expander(f"{row['merchant']}"):
                guess = web.guess(row["merchant"]) if enable_online else None
                options = DEFAULT_CATEGORIES + ["Other"]
                preselect = options.index(guess) if guess in options else 0
                new_cat = st.selectbox("Choose a category", options, index=preselect, key=f"sel_{i}")
                if guess:
                    st.caption(f"Suggested by online lookup: **{guess}**")
                if st.button("Save mapping", key=f"save_{i}"):
                    cat.learn(row["merchant"], new_cat)
                    st.success(f"Saved: {row['merchant']} → {new_cat}")
        st.info("After saving new mappings, click **Rerun** in the top-right.")
    else:
        st.success("All merchants recognized! ✅")

    # Shared-expense editing
    df["is_shared"] = False
    df["your_share"] = df["amount"]
    edited = st.data_editor(
        df[["date", "merchant", "category", "amount", "is_shared", "your_share"]],
        column_config={
            "date": st.column_config.DateColumn("Date"),
            "amount": st.column_config.NumberColumn("Amount", help="Positive = spend; negative = refund"),
            "is_shared": st.column_config.CheckboxColumn("Shared?"),
            "your_share": st.column_config.NumberColumn("Your share", help="Portion that applies to you"),
        },
        hide_index=True,
        num_rows="dynamic",
    )
    edited["your_share"] = pd.to_numeric(edited["your_share"], errors="coerce").fillna(0.0)

    # Totals + chart
    total_spend = edited["amount"].sum()
    total_yours = edited["your_share"].sum()
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Total transactions (sum of Amount)", f"{total_spend:,.2f}")
    with c2:
        st.metric("Your total (sum of Your share)", f"{total_yours:,.2f}")

    st.divider()
    edited["category"] = edited["category"].fillna("Uncategorized")
    by_cat = edited.groupby("category", as_index=False)["your_share"].sum().sort_values("your_share", ascending=False)
    st.subheader("Spend by category (your share)")
    st.dataframe(by_cat, use_container_width=True)
    fig = px.pie(by_cat, names="category", values="your_share", title="Your share by category")
    st.plotly_chart(fig, use_container_width=True)

    # Download
    st.subheader("Download results")
    out = edited.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    st.download_button("Download categorized CSV", data=out.to_csv(index=False), file_name="categorized_statement.csv", mime="text/csv")
